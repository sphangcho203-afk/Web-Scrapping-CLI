from __future__ import annotations

import asyncio
import dataclasses
import socket
from pathlib import Path
from urllib.parse import urlsplit
from urllib.robotparser import RobotFileParser

from .adapters import capture_with_backend
from .browser import render_page
from .crawler import _robots_for
from .discovery import discover_frontier_urls
from .extractor import extract_document
from .fetcher import DEFAULT_UA, fetch_url
from .frontier import DEFAULT_FRONTIER_DB, FrontierJob, FrontierStore, JobState
from .hunt import HuntScope, _rendered_fetch, _same_scope, _should_render, canonicalize_url
from .object_store import S3ObjectStore
from .policy import validate_public_http_url
from .postgres_frontier import PostgresFrontier
from .postgres_store import PostgresCaptureStore
from .rate_limit import DistributedHostLimiter
from .storage import DEFAULT_DB, DEFAULT_OBJECTS, Store
from .telemetry import NullTelemetry, TelemetrySink

EXTERNAL_BACKENDS = {"crawlee", "crawlee-http", "crawl4ai", "scrapy"}


@dataclasses.dataclass(frozen=True, slots=True)
class WorkerBatchResult:
    worker_id: str
    leased: int
    completed: int
    retried: int
    dead: int
    deferred_circuit: int
    discovered: int
    browser_pages: int
    errors: list[str]


class _PostgresHostLimiter:
    def __init__(self, frontier: PostgresFrontier) -> None:
        self.frontier = frontier

    def reserve(self, host: str, *, min_delay_seconds: float) -> float:
        return self.frontier.reserve_host_slot(host, min_delay_seconds=min_delay_seconds)


class FrontierWorker:
    def __init__(
        self,
        worker_id: str | None = None,
        *,
        frontier_db: Path = DEFAULT_FRONTIER_DB,
        postgres_dsn: str | None = None,
        content_db: Path = DEFAULT_DB,
        content_postgres_dsn: str | None = None,
        objects_root: Path = DEFAULT_OBJECTS,
        s3_bucket: str | None = None,
        s3_prefix: str = "internet-hands/objects",
        s3_endpoint_url: str | None = None,
        s3_region: str | None = None,
        s3_access_key_id: str | None = None,
        s3_secret_access_key: str | None = None,
        s3_session_token: str | None = None,
        telemetry: TelemetrySink | None = None,
        backend: str = "native",
        allow_external_network: bool = False,
        max_depth: int = 5,
        lease_seconds: int = 120,
        respect_robots: bool = True,
        browser_fallback: bool = False,
        browser_text_threshold: int = 200,
        per_host_delay: float = 0.35,
        circuit_threshold: int = 5,
        circuit_cooldown_seconds: int = 60,
    ) -> None:
        self.worker_id = worker_id or f"{socket.gethostname()}-{id(self):x}"
        normalized_backend = backend.strip().lower()
        if normalized_backend not in {"native", *EXTERNAL_BACKENDS}:
            raise ValueError(f"Unsupported worker backend: {backend}")
        if normalized_backend in EXTERNAL_BACKENDS and not allow_external_network:
            raise ValueError(
                "External worker backends require allow_external_network=True and should run "
                "inside a public-egress-restricted environment"
            )
        if not 0 <= max_depth <= 50:
            raise ValueError("max_depth must be between 0 and 50")
        if not 0.0 <= per_host_delay <= 3600.0:
            raise ValueError("per_host_delay must be between 0 and 3600")

        self.backend = normalized_backend
        self.allow_external_network = allow_external_network
        self.max_depth = max_depth
        self.lease_seconds = lease_seconds
        self.respect_robots = respect_robots
        self.browser_fallback = browser_fallback
        self.browser_text_threshold = browser_text_threshold
        self.per_host_delay = per_host_delay
        self.circuit_threshold = circuit_threshold
        self.circuit_cooldown_seconds = circuit_cooldown_seconds
        self.telemetry = telemetry or NullTelemetry()

        if postgres_dsn:
            postgres_frontier = PostgresFrontier(postgres_dsn)
            self.frontier = postgres_frontier
            self.limiter = _PostgresHostLimiter(postgres_frontier)
        else:
            self.frontier = FrontierStore(frontier_db)
            self.limiter = DistributedHostLimiter(frontier_db)

        if content_postgres_dsn:
            if not s3_bucket:
                raise ValueError(
                    "Distributed Postgres capture storage requires s3_bucket so raw objects are "
                    "shared across worker nodes"
                )
            object_store = S3ObjectStore(
                bucket=s3_bucket,
                prefix=s3_prefix,
                endpoint_url=s3_endpoint_url,
                region_name=s3_region,
                access_key_id=s3_access_key_id,
                secret_access_key=s3_secret_access_key,
                session_token=s3_session_token,
            )
            self.store = PostgresCaptureStore(content_postgres_dsn, object_store=object_store)
        else:
            self.store = Store(content_db, objects_root)

    async def run_once(self, *, batch_size: int = 8) -> WorkerBatchResult:
        jobs = self.frontier.lease(
            self.worker_id,
            limit=batch_size,
            lease_seconds=self.lease_seconds,
        )
        if not jobs:
            result = WorkerBatchResult(
                worker_id=self.worker_id,
                leased=0,
                completed=0,
                retried=0,
                dead=0,
                deferred_circuit=0,
                discovered=0,
                browser_pages=0,
                errors=[],
            )
            self._emit("worker_idle", payload={"batch_size": batch_size})
            return result

        self._emit("batch_started", payload={"leased": len(jobs), "batch_size": batch_size})
        results = await asyncio.gather(*(self._process(job) for job in jobs))
        completed = sum(item[0] == "completed" for item in results)
        retried = sum(item[0] == "retried" for item in results)
        dead = sum(item[0] == "dead" for item in results)
        deferred = sum(item[0] == "circuit" for item in results)
        discovered = sum(item[1] for item in results)
        browser_pages = sum(item[2] for item in results)
        errors = [item[3] for item in results if item[3] is not None]
        result = WorkerBatchResult(
            worker_id=self.worker_id,
            leased=len(jobs),
            completed=completed,
            retried=retried,
            dead=dead,
            deferred_circuit=deferred,
            discovered=discovered,
            browser_pages=browser_pages,
            errors=errors,
        )
        self._emit(
            "batch_completed",
            payload={
                "leased": result.leased,
                "completed": result.completed,
                "retried": result.retried,
                "dead": result.dead,
                "deferred_circuit": result.deferred_circuit,
                "discovered": result.discovered,
                "browser_pages": result.browser_pages,
                "errors": len(result.errors),
            },
        )
        return result

    async def drain(
        self,
        *,
        batch_size: int = 8,
        max_batches: int = 1000,
        idle_sleep: float = 0.0,
    ) -> list[WorkerBatchResult]:
        output: list[WorkerBatchResult] = []
        for _ in range(max_batches):
            batch = await self.run_once(batch_size=batch_size)
            output.append(batch)
            if batch.leased == 0:
                break
            if idle_sleep > 0:
                await asyncio.sleep(idle_sleep)
        return output

    async def _process(self, job: FrontierJob) -> tuple[str, int, int, str | None]:
        host = (urlsplit(job.url).hostname or "").lower()
        circuit_key = f"{self.backend}:{host}"
        self._emit("job_started", job=job, payload={"attempt": job.attempts})

        if not self.frontier.circuit_allows(circuit_key):
            state = self.frontier.fail(
                job.id,
                self.worker_id,
                "backend/host circuit open",
                base_backoff_seconds=float(self.circuit_cooldown_seconds),
                max_backoff_seconds=float(self.circuit_cooldown_seconds),
            )
            status = "dead" if state == JobState.DEAD else "circuit"
            self._emit(
                "job_deferred_circuit",
                job=job,
                payload={"circuit_key": circuit_key, "state": status},
            )
            return status, 0, 0, "backend/host circuit open"

        try:
            robots = await self._robots_for(job.url)
            if robots is not None and not robots.can_fetch(DEFAULT_UA, job.url):
                self.frontier.ack(job.id, self.worker_id)
                self._emit("job_skipped_robots", job=job)
                return "completed", 0, 0, None

            await self._wait_for_host(host)
            if self.backend == "native":
                result = await fetch_url(job.url, include_body=True)
            else:
                result = await capture_with_backend(
                    self.backend,
                    job.url,
                    allow_external_network=self.allow_external_network,
                )
            document = extract_document(result)
            browser_pages = int(self.backend == "crawl4ai")
            if (
                self.backend == "native"
                and self.browser_fallback
                and _should_render(
                    result,
                    document,
                    text_threshold=self.browser_text_threshold,
                )
            ):
                await self._wait_for_host((urlsplit(result.final_url).hostname or "").lower())
                rendered = await render_page(result.final_url)
                result = _rendered_fetch(result, rendered)
                document = extract_document(result)
                browser_pages = 1

            capture_id = self.store.save_fetch(result, document)
            self._emit(
                "capture_saved",
                job=job,
                url=result.final_url,
                payload={
                    "capture_id": capture_id,
                    "status_code": result.status_code,
                    "content_length": result.content_length,
                    "sha256": result.sha256,
                },
            )
            machine_links = discover_frontier_urls(
                result.body_text or "",
                result.final_url,
                content_type=result.content_type,
                limit=5000,
            )
            links = list(dict.fromkeys([*document.links, *machine_links]))
            discovered = self._enqueue_children(job, links, parent=result.final_url)
            self.frontier.circuit_success(circuit_key)
            self.frontier.ack(job.id, self.worker_id)
            self._emit(
                "job_completed",
                job=job,
                url=result.final_url,
                payload={"discovered": discovered, "browser_page": bool(browser_pages)},
            )
            return "completed", discovered, browser_pages, None
        except Exception as exc:  # noqa: BLE001 -- worker persists failures as queue state
            error = f"{type(exc).__name__}: {exc}"
            opened = self.frontier.circuit_failure(
                circuit_key,
                error,
                threshold=self.circuit_threshold,
                cooldown_seconds=self.circuit_cooldown_seconds,
            )
            state = self.frontier.fail(
                job.id,
                self.worker_id,
                error,
                base_backoff_seconds=(
                    float(self.circuit_cooldown_seconds) if opened else 2.0
                ),
                max_backoff_seconds=300.0,
            )
            final_state = "dead" if state == JobState.DEAD else "retried"
            self._emit(
                "job_failed",
                job=job,
                payload={"error": error, "state": final_state, "circuit_opened": opened},
            )
            return final_state, 0, 0, error

    async def _wait_for_host(self, host: str) -> None:
        if not host:
            return
        wait = self.limiter.reserve(host, min_delay_seconds=self.per_host_delay)
        if wait > 0:
            await asyncio.sleep(wait)

    async def _robots_for(self, url: str) -> RobotFileParser | None:
        if not self.respect_robots:
            return None
        parts = urlsplit(url)
        origin = f"{parts.scheme}://{parts.netloc}"
        if origin not in self._robots:
            try:
                self._robots[origin] = await _robots_for(url)
            except Exception:  # noqa: BLE001 -- unavailable robots metadata is non-fatal
                self._robots[origin] = None
        return self._robots[origin]

    def _enqueue_children(self, job: FrontierJob, links: list[str], *, parent: str) -> int:
        if job.depth >= self.max_depth:
            return 0
        try:
            scope = HuntScope(job.scope)
        except ValueError:
            scope = HuntScope.ORIGIN
        added = 0
        for raw in links:
            try:
                link = canonicalize_url(raw)
                if not _same_scope(job.root_url, link, scope):
                    continue
                validate_public_http_url(link)
            except (ValueError, OSError):
                continue
            added += int(
                self.frontier.enqueue(
                    link,
                    root_url=job.root_url,
                    scope=scope.value,
                    depth=job.depth + 1,
                    parent=parent,
                    priority=max(job.priority - 1, -1000),
                    max_attempts=job.max_attempts,
                )
            )
        return added

    def _emit(
        self,
        event_type: str,
        *,
        job: FrontierJob | None = None,
        url: str | None = None,
        payload: dict[str, object] | None = None,
    ) -> None:
        try:
            self.telemetry.emit(
                event_type,
                worker_id=self.worker_id,
                backend=self.backend,
                job_id=job.id if job else None,
                url=url or (job.url if job else None),
                payload=dict(payload or {}),
            )
        except Exception:  # noqa: BLE001 -- telemetry must never break crawl correctness
            return
