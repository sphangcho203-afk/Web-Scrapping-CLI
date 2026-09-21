from __future__ import annotations

from contextvars import ContextVar
from dataclasses import dataclass, field
from typing import Any


@dataclass(slots=True)
class ExecutionUsage:
    counters: dict[str, int] = field(default_factory=dict)
    provider_calls: dict[str, int] = field(default_factory=dict)

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

    def to_dict(self) -> dict[str, Any]:
        return {
            "counters": dict(sorted(self.counters.items())),
            "provider_calls": dict(sorted(self.provider_calls.items())),
        }


_current_usage: ContextVar[ExecutionUsage | None] = ContextVar(
    "internet_hands_execution_usage",
    default=None,
)


def start_execution_meter():
    return _current_usage.set(ExecutionUsage())


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


def execution_usage_snapshot() -> dict[str, Any]:
    usage = _current_usage.get()
    if usage is None:
        return {"counters": {}, "provider_calls": {}}
    return usage.to_dict()
