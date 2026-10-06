from __future__ import annotations

from contextvars import ContextVar
from dataclasses import dataclass, field
from typing import Any

from .provider_cost_reports import normalize_reports


@dataclass(slots=True)
class ExecutionUsage:
    counters: dict[str, int] = field(default_factory=dict)
    provider_calls: dict[str, int] = field(default_factory=dict)
    provider_events: list[dict[str, Any]] = field(default_factory=list)
    provider_cost_reports: list[dict[str, Any]] = field(default_factory=list)

    def add(self, name: str, amount: int = 1) -> None:
        amount = int(amount)
        if amount <= 0:
            return
        self.counters[name] = self.counters.get(name, 0) + amount

    def add_provider_call(self, provider: str, amount: int = 1) -> None:
        provider = provider.strip().lower()
        amount = int(amount)
        if not provider or amount <= 0:
            return
        self.provider_calls[provider] = self.provider_calls.get(provider, 0) + amount

    def add_provider_event(
        self,
        provider: str,
        *,
        ref: str,
        status: str,
        duration_ms: int | None,
        error: str | None,
        error_class: str | None,
        retryable: bool,
        attempt: int,
    ) -> None:
        provider = provider.strip().lower()
        if not provider:
            return
        self.provider_events.append(
            {
                "provider": provider,
                "ref": str(ref or "")[:200],
                "status": str(status or "unknown")[:40],
                "duration_ms": (
                    max(0, int(duration_ms))
                    if duration_ms is not None
                    else None
                ),
                "error": (str(error).strip()[:500] if error else None),
                "error_class": (
                    str(error_class).strip().lower()[:80]
                    if error_class
                    else None
                ),
                "retryable": bool(retryable),
                "attempt": max(1, int(attempt)),
            }
        )

    def to_dict(self) -> dict[str, Any]:
        result = {
            "counters": dict(sorted(self.counters.items())),
            "provider_calls": dict(sorted(self.provider_calls.items())),
            "provider_events": list(self.provider_events),
        }
        if self.provider_cost_reports:
            result['provider_cost_reports'] = [dict(item) for item in self.provider_cost_reports]
        return result


_current_usage: ContextVar[ExecutionUsage | None] = ContextVar(
    "internet_hands_execution_usage",
    default=None,
)


def start_execution_meter(initial: dict[str, Any] | None = None):
    usage = ExecutionUsage()
    if initial:
        for name, value in (initial.get("counters") or {}).items():
            usage.add(name, value)
        for name, value in (initial.get("provider_calls") or {}).items():
            usage.add_provider_call(name, value)
        usage.provider_events = [dict(event) for event in initial.get("provider_events") or []]
        usage.provider_cost_reports = normalize_reports(initial.get('provider_cost_reports'))
    return _current_usage.set(usage)


def reset_execution_meter(token: Any) -> None:
    _current_usage.reset(token)


def record_usage(name: str, amount: int = 1) -> None:
    usage = _current_usage.get()
    if usage is not None:
        usage.add(name, amount)


def record_provider_call(provider: str, amount: int = 1) -> None:
    usage = _current_usage.get()
    if usage is not None:
        usage.add_provider_call(provider, amount)


def record_provider_cost_report(report: dict[str, Any]) -> None:
    usage = _current_usage.get()
    if usage is not None:
        usage.provider_cost_reports.extend(normalize_reports([report]))


def record_provider_outcome(
    provider: str,
    *,
    ref: str,
    status: str,
    duration_ms: int | None = None,
    error: str | None = None,
    error_class: str | None = None,
    retryable: bool = False,
    attempt: int = 1,
) -> None:
    usage = _current_usage.get()
    if usage is not None:
        usage.add_provider_event(
            provider,
            ref=ref,
            status=status,
            duration_ms=duration_ms,
            error=error,
            error_class=error_class,
            retryable=retryable,
            attempt=attempt,
        )


def execution_usage_snapshot() -> dict[str, Any]:
    usage = _current_usage.get()
    if usage is None:
        return {"counters": {}, "provider_calls": {}, "provider_events": []}
    return usage.to_dict()
