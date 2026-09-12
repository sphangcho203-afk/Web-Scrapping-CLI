from __future__ import annotations

import asyncio
import dataclasses
import socket
from pathlib import Path
from urllib.parse import urlsplit
from urllib.robotparser import RobotFileParser

from .browser import render_page
from .crawler import _robots_for
from .discovery import discover_frontier_urls
from .extractor import extract_document
from .fetcher import DEFAULT_UA, fetch_url
from .frontier import DEFAULT_FRONTIER_DB, FrontierJob, FrontierStore, JobState
from .hunt import HuntScope, _rendered_fetch, _same_scope, _should_render, canonicalize_url
from .policy import validate_public_http_url
from .rate_limit import DistributedHostLimiter
from .storage import DEFAULT_DB, Store


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


class FrontierWorker:
    def __init__(
        self,
        worker_id: str | None = None,
        *,
        frontier_db: Path = DEFAULT_FRONTIER_DB,
        content_db: Path = DEFAULT_DB,
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
        if not 0 <= max_depth <= 50:
            raise ValueError("max_depth must be between 0 and 50")
        if not 0.0 <= per_host_delay <= 3600.0:
            raise ValueError("per_host_delay must be between 0 and 3600")
        self.max_depth = max_depth
        self.lease_seconds = lease_seconds
        self.respect_robots = respect_robots
        self.browser_fallback = browser_fallback
        self.browser_text_threshold = browser_text_threshold
        self.per_host_delay = per_host_delay
        self.circuit_threshold = circuit_threshold
        self.circuit_cooldown_seconds = circuit_cooldown_seconds
        self.frontier = FrontierStore(frontier_db)
        self.limiter = DistributedHostLimiter(frontier_db)
        self.store = Store(content_db)
        self._robots: dict[str, RobotFileParser | None] = {}

    async def run_once(self, *, batch_size: int = 8) -> WorkerBatchResult:
        jobs = self.frontier.lease(
            self.worker_id,
            limit=batch_size,
            lease_seconds=self.lease_seconds,
        )
        if not jobs:
            return WorkerBatchResult(
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

        results = await asyncio.gather(*(self._process(job) for job in jobs))
        completed = sum(item[0] == "completed" for item in results)
        retried = sum(item[0] == "retried" for item in results)
        dead = sum(item[0] == "dead" for item in results)
        deferred = sum(item[0] == "circuit" for item in results)
        discovered = sum(item[1] for item in results)
        browser_pages = sum(item[2] for item in results)
        errors = [item[3] for item in results if item[3] is not None]
        return WorkerBatchResult(
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
        circuit_key = f"http:{host}"
        if not self.frontier.circuit_allows(circuit_key):
            state = self.frontier.fail(
                job.id,
                self.worker_id,
                "host circuit open",
                base_backoff_seconds=float(self.circuit_cooldown_seconds),
                max_backoff_seconds=float(self.circuit_cooldown_seconds),
            )
            status = "dead" if state == JobState.DEAD else "circuit"
            return status, 0, 0, "host circuit open"

        try:
            robots = await self._robots_for(job.url)
            if robots is not None and not robots.can_fetch(DEFAULT_UA, job.url):
                self.frontier.ack(job.id, self.worker_id)
                return "completed", 0, 0, None

            await self._wait_for_host(host)
            result = await fetch_url(job.url, include_body=True)
            document = extract_document(result)
            browser_pages = 0
            if self.browser_fallback and _should_render(
                result,
                document,
                text_threshold=self.browser_text_threshold,
            ):
                await self._wait_for_host((urlsplit(result.final_url).hostname or "").lower())
                rendered = await render_page(result.final_url)
                result = _rendered_fetch(result, rendered)
                document = extract_document(result)
                browser_pages = 1

            self.store.save_fetch(result, document)
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
            return ("dead" if state == JobState.DEAD else "retried"), 0, 0, error

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
