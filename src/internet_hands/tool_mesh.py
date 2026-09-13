from __future__ import annotations

import asyncio
import fnmatch
import json
import os
import time
import uuid
from dataclasses import asdict, dataclass, field
from typing import Any, Protocol

_RESTRICTED_MARKETPLACE_TERMS = (
    "ammunition",
    "casino",
    "cannabis",
    "cigarette",
    "firearm",
    "gambling",
    "liquor",
    "marijuana",
    "nicotine",
    "pornography",
    "sportsbook",
    "taser",
    "tobacco",
    "vape",
    "weapon",
    "betting",
    "prediction market",
    "pepper spray",
    "adult sexual",
)


@dataclass(slots=True)
class ToolDescriptor:
    ref: str
    provider: str
    tool_id: str
    name: str
    description: str = ""
    input_schema: dict[str, Any] = field(default_factory=dict)
    output_schema: dict[str, Any] = field(default_factory=dict)
    tags: list[str] = field(default_factory=list)
    requires_auth: bool = True
    side_effecting: bool = False
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(slots=True)
class ToolExecution:
    execution_id: str
    provider: str
    ref: str
    status: str
    started_at: float
    finished_at: float | None = None
    duration_ms: int | None = None
    job_id: str | None = None
    result_id: str | None = None
    data: Any = None
    error: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    def finish(
        self,
        *,
        status: str,
        data: Any = None,
        error: str | None = None,
        job_id: str | None = None,
        result_id: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> ToolExecution:
        finished = time.time()
        self.status = status
        self.finished_at = finished
        self.duration_ms = max(0, int((finished - self.started_at) * 1000))
        self.data = data
        self.error = error
        self.job_id = job_id
        self.result_id = result_id
        if metadata:
            self.metadata.update(metadata)
        return self

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class ToolProvider(Protocol):
    name: str

    async def status(self) -> dict[str, Any]: ...

    async def search(self, query: str, *, limit: int = 10) -> list[ToolDescriptor]: ...

    async def describe(self, tool_id: str) -> ToolDescriptor: ...

    async def execute(
        self,
        tool_id: str,
        arguments: dict[str, Any],
        *,
        account: str | None = None,
        wait_seconds: int = 30,
        timeout_seconds: int = 60,
        options: dict[str, Any] | None = None,
    ) -> dict[str, Any]: ...

    async def job_status(
        self, job_id: str, *, wait_seconds: int = 0
    ) -> dict[str, Any]: ...

    async def result_page(
        self, result_id: str, *, offset: int = 0, limit: int = 100
    ) -> dict[str, Any]: ...


class ToolMesh:
    def __init__(
        self,
        providers: list[ToolProvider],
        *,
        max_batch: int | None = None,
        max_response_bytes: int | None = None,
    ) -> None:
        self.providers = {provider.name: provider for provider in providers}
        self.max_batch = max_batch or int(os.getenv("INTERNET_HANDS_TOOL_MAX_BATCH", "20"))
        self.max_response_bytes = max_response_bytes or int(
            os.getenv("INTERNET_HANDS_TOOL_MAX_RESPONSE_BYTES", "1000000")
        )
        self.allow_patterns = self._patterns("INTERNET_HANDS_TOOL_ALLOW")
        self.deny_patterns = self._patterns("INTERNET_HANDS_TOOL_DENY")

    @staticmethod
    def _patterns(name: str) -> list[str]:
        return [item.strip() for item in os.getenv(name, "").split(",") if item.strip()]

    @staticmethod
    def _safe_text(value: str) -> bool:
        normalized = value.casefold().replace("_", "-")
        return not any(term in normalized for term in _RESTRICTED_MARKETPLACE_TERMS)

    def _allowed(self, ref: str) -> bool:
        if not self._safe_text(ref):
            return False
        if self.deny_patterns and any(
            fnmatch.fnmatch(ref, pattern) for pattern in self.deny_patterns
        ):
            return False
        if self.allow_patterns:
            return any(fnmatch.fnmatch(ref, pattern) for pattern in self.allow_patterns)
        return True

    def _descriptor_allowed(self, descriptor: ToolDescriptor) -> bool:
        if not self._allowed(descriptor.ref):
            return False
        searchable = " ".join(
            [
                descriptor.name,
                descriptor.description,
                *descriptor.tags,
                json.dumps(descriptor.metadata, default=str),
            ]
        )
        return self._safe_text(searchable)

    @staticmethod
    def _split_ref(ref: str) -> tuple[str, str]:
        provider, separator, tool_id = ref.partition(":")
        if not separator or not provider or not tool_id:
            raise ValueError("tool ref must use provider:tool_id")
        return provider, tool_id

    def _provider(self, name: str) -> ToolProvider:
        try:
            return self.providers[name]
        except KeyError as exc:
            raise ValueError(f"unknown tool provider: {name}") from exc

    def _bounded(self, value: Any) -> Any:
        raw = json.dumps(value, default=str, separators=(",", ":")).encode()
        if len(raw) <= self.max_response_bytes:
            return value
        return {
            "truncated": True,
            "bytes": len(raw),
            "max_bytes": self.max_response_bytes,
            "preview": raw[: self.max_response_bytes].decode("utf-8", errors="replace"),
        }

    async def provider_status(self) -> dict[str, Any]:
        async def one(name: str, provider: ToolProvider) -> tuple[str, dict[str, Any]]:
            try:
                value = await provider.status()
            except Exception as exc:  # noqa: BLE001 - isolate external provider failures
                value = {"configured": False, "error": str(exc)}
            return name, value

        rows = await asyncio.gather(
            *(one(name, provider) for name, provider in self.providers.items())
        )
        return {name: value for name, value in rows}

    async def search(
        self,
        query: str,
        *,
        providers: list[str] | None = None,
        limit: int = 10,
    ) -> dict[str, Any]:
        query = query.strip()
        if not query:
            raise ValueError("query is required")
        limit = max(1, min(limit, 50))
        names = providers or list(self.providers)
        unknown = [name for name in names if name not in self.providers]
        if unknown:
            raise ValueError(f"unknown providers: {', '.join(unknown)}")

        async def one(name: str) -> tuple[str, list[ToolDescriptor], str | None]:
            try:
                rows = await self.providers[name].search(query, limit=limit)
                return name, [row for row in rows if self._descriptor_allowed(row)], None
            except Exception as exc:  # noqa: BLE001 - isolate external catalog failures
                return name, [], str(exc)

        groups = await asyncio.gather(*(one(name) for name in names))
        buckets: dict[str, list[ToolDescriptor]] = {}
        errors: dict[str, str] = {}
        for name, rows, error in groups:
            buckets[name] = rows
            if error:
                errors[name] = error

        tools: list[dict[str, Any]] = []
        for index in range(limit):
            added = False
            for name in names:
                rows = buckets.get(name, [])
                if index < len(rows):
                    tools.append(rows[index].to_dict())
                    added = True
                    if len(tools) >= limit:
                        break
            if len(tools) >= limit or not added:
                break
        return {"query": query, "tools": tools, "errors": errors}

    async def describe(self, ref: str) -> dict[str, Any]:
        if not self._allowed(ref):
            raise PermissionError(f"tool blocked by mesh policy: {ref}")
        provider_name, tool_id = self._split_ref(ref)
        descriptor = await self._provider(provider_name).describe(tool_id)
        descriptor.ref = ref
        if not self._descriptor_allowed(descriptor):
            raise PermissionError(f"tool blocked by marketplace safety policy: {ref}")
        return descriptor.to_dict()

    async def execute(
        self,
        ref: str,
        arguments: dict[str, Any],
        *,
        account: str | None = None,
        wait_seconds: int = 30,
        timeout_seconds: int = 60,
        options: dict[str, Any] | None = None,
        dry_run: bool = False,
    ) -> dict[str, Any]:
        if not self._allowed(ref):
            raise PermissionError(f"tool blocked by mesh policy: {ref}")
        provider_name, tool_id = self._split_ref(ref)
        provider = self._provider(provider_name)
        descriptor = await provider.describe(tool_id)
        descriptor.ref = ref
        if not self._descriptor_allowed(descriptor):
            raise PermissionError(f"tool blocked by marketplace safety policy: {ref}")

        execution = ToolExecution(
            execution_id=uuid.uuid4().hex,
            provider=provider_name,
            ref=ref,
            status="running",
            started_at=time.time(),
        )
        if dry_run:
            return execution.finish(
                status="dry_run",
                data={
                    "tool": descriptor.to_dict(),
                    "arguments": arguments,
                    "account": account,
                    "options": options or {},
                },
            ).to_dict()

        try:
            result = await provider.execute(
                tool_id,
                arguments,
                account=account,
                wait_seconds=max(0, min(wait_seconds, 300)),
                timeout_seconds=max(1, min(timeout_seconds, 600)),
                options=options,
            )
        except Exception as exc:  # noqa: BLE001 - normalize provider execution failures
            return execution.finish(status="failed", error=str(exc)).to_dict()

        return execution.finish(
            status=str(result.get("status") or "completed"),
            data=self._bounded(result.get("data")),
            error=result.get("error"),
            job_id=result.get("job_id"),
            result_id=result.get("result_id"),
            metadata=result.get("metadata") or {},
        ).to_dict()

    async def batch_execute(
        self,
        calls: list[dict[str, Any]],
        *,
        max_concurrency: int = 5,
    ) -> dict[str, Any]:
        if not calls:
            return {"results": []}
        if len(calls) > self.max_batch:
            raise ValueError(f"batch exceeds configured limit of {self.max_batch}")
        semaphore = asyncio.Semaphore(max(1, min(max_concurrency, 20)))

        async def one(index: int, call: dict[str, Any]) -> dict[str, Any]:
            async with semaphore:
                try:
                    result = await self.execute(
                        str(call["ref"]),
                        dict(call.get("arguments") or {}),
                        account=call.get("account"),
                        wait_seconds=int(call.get("wait_seconds", 30)),
                        timeout_seconds=int(call.get("timeout_seconds", 60)),
                        options=dict(call.get("options") or {}),
                        dry_run=bool(call.get("dry_run", False)),
                    )
                except Exception as exc:  # noqa: BLE001 - isolate batch item failures
                    now = time.time()
                    result = {
                        "execution_id": uuid.uuid4().hex,
                        "provider": "",
                        "ref": str(call.get("ref") or ""),
                        "status": "failed",
                        "started_at": now,
                        "finished_at": now,
                        "duration_ms": 0,
                        "error": str(exc),
                    }
                return {"index": index, **result}

        results = await asyncio.gather(
            *(one(index, call) for index, call in enumerate(calls))
        )
        results.sort(key=lambda item: item["index"])
        return {"results": results}

    async def job_status(
        self,
        provider: str,
        job_id: str,
        *,
        wait_seconds: int = 0,
    ) -> dict[str, Any]:
        return self._bounded(
            await self._provider(provider).job_status(
                job_id, wait_seconds=max(0, min(wait_seconds, 300))
            )
        )

    async def result_page(
        self,
        provider: str,
        result_id: str,
        *,
        offset: int = 0,
        limit: int = 100,
    ) -> dict[str, Any]:
        return self._bounded(
            await self._provider(provider).result_page(
                result_id,
                offset=max(0, offset),
                limit=max(1, min(limit, 1000)),
            )
        )
