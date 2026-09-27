from __future__ import annotations

import os
import threading
import time
from dataclasses import asdict, dataclass
from typing import Any

_SUCCESS_STATUSES = {
    "completed",
    "complete",
    "ok",
    "success",
    "succeeded",
    "running",
    "queued",
    "pending",
    "accepted",
}
_NEUTRAL_STATUSES = {"blocked", "dry_run", "cancelled", "canceled"}


def _env_int(name: str, default: int, *, minimum: int, maximum: int) -> int:
    try:
        value = int(os.getenv(name, str(default)))
    except (TypeError, ValueError):
        value = default
    return max(minimum, min(value, maximum))


def _enabled() -> bool:
    return os.getenv("OPENCRAWL_PROVIDER_RELIABILITY", "true").strip().lower() not in {
        "0",
        "false",
        "no",
        "off",
    }


@dataclass(slots=True)
class ProviderReliability:
    provider: str
    successes: int = 0
    failures: int = 0
    neutral: int = 0
    consecutive_failures: int = 0
    ewma_latency_ms: float | None = None
    last_success_at: float | None = None
    last_failure_at: float | None = None
    last_error: str | None = None
    circuit_open_until: float = 0.0

    @property
    def samples(self) -> int:
        return self.successes + self.failures

    def score(self) -> int:
        # Small Bayesian prior prevents a single sample from dominating routing.
        reliability = (self.successes + 3) / (self.samples + 4)
        latency_penalty = 0
        if self.ewma_latency_ms is not None:
            latency_penalty = min(15, int(self.ewma_latency_ms // 2000))
        return max(0, min(100, round(reliability * 100) - latency_penalty))

    def circuit_open(self, now: float | None = None) -> bool:
        current = time.time() if now is None else now
        return self.circuit_open_until > current

    def routing_penalty(self, now: float | None = None) -> int:
        if self.circuit_open(now):
            return 100_000
        if self.samples == 0:
            return 0
        return self.consecutive_failures * 25 + max(0, 70 - self.score())

    def to_public_dict(self, now: float | None = None) -> dict[str, Any]:
        current = time.time() if now is None else now
        return {
            **asdict(self),
            "samples": self.samples,
            "score": self.score(),
            "routing_penalty": self.routing_penalty(current),
            "circuit_open": self.circuit_open(current),
            "circuit_remaining_seconds": (
                max(0, int(self.circuit_open_until - current))
                if self.circuit_open(current)
                else 0
            ),
            "scope": "runtime-local",
        }


class ProviderReliabilityTracker:
    """Small runtime-local health model used only to improve safe fallback ordering."""

    def __init__(self) -> None:
        self._rows: dict[str, ProviderReliability] = {}
        self._lock = threading.Lock()

    @staticmethod
    def enabled() -> bool:
        return _enabled()

    @staticmethod
    def _threshold() -> int:
        return _env_int(
            "OPENCRAWL_PROVIDER_CIRCUIT_FAILURES",
            3,
            minimum=2,
            maximum=20,
        )

    @staticmethod
    def _base_cooldown() -> int:
        return _env_int(
            "OPENCRAWL_PROVIDER_CIRCUIT_COOLDOWN_SECONDS",
            45,
            minimum=5,
            maximum=900,
        )

    @staticmethod
    def _max_cooldown() -> int:
        return _env_int(
            "OPENCRAWL_PROVIDER_CIRCUIT_MAX_COOLDOWN_SECONDS",
            300,
            minimum=30,
            maximum=3600,
        )

    def _row(self, provider: str) -> ProviderReliability:
        normalized = provider.strip().lower()
        if not normalized:
            raise ValueError("provider is required")
        row = self._rows.get(normalized)
        if row is None:
            row = ProviderReliability(provider=normalized)
            self._rows[normalized] = row
        return row

    def record(
        self,
        provider: str,
        *,
        status: str,
        duration_ms: int | None = None,
        error: str | None = None,
        now: float | None = None,
    ) -> dict[str, Any]:
        if not _enabled():
            return self.snapshot(provider, now=now)
        current = time.time() if now is None else now
        normalized_status = str(status or "failed").strip().lower()
        latency = None if duration_ms is None else max(0, int(duration_ms))

        with self._lock:
            row = self._row(provider)
            if latency is not None:
                if row.ewma_latency_ms is None:
                    row.ewma_latency_ms = float(latency)
                else:
                    row.ewma_latency_ms = row.ewma_latency_ms * 0.8 + latency * 0.2

            if normalized_status in _NEUTRAL_STATUSES:
                row.neutral += 1
            elif normalized_status in _SUCCESS_STATUSES:
                row.successes += 1
                row.consecutive_failures = 0
                row.last_success_at = current
                row.last_error = None
                row.circuit_open_until = 0.0
            else:
                row.failures += 1
                row.consecutive_failures += 1
                row.last_failure_at = current
                row.last_error = (str(error or normalized_status).strip() or normalized_status)[:500]
                threshold = self._threshold()
                if row.consecutive_failures >= threshold:
                    exponent = min(4, row.consecutive_failures - threshold)
                    cooldown = min(
                        self._max_cooldown(),
                        self._base_cooldown() * (2**exponent),
                    )
                    row.circuit_open_until = max(row.circuit_open_until, current + cooldown)

            return row.to_public_dict(current)

    def snapshot(
        self,
        provider: str | None = None,
        *,
        now: float | None = None,
    ) -> dict[str, Any]:
        current = time.time() if now is None else now
        with self._lock:
            if provider is not None:
                normalized = provider.strip().lower()
                row = self._rows.get(normalized)
                if row is None:
                    return ProviderReliability(provider=normalized).to_public_dict(current)
                return row.to_public_dict(current)
            return {
                name: row.to_public_dict(current)
                for name, row in sorted(self._rows.items())
            }

    def routing_state(self, provider: str, *, now: float | None = None) -> dict[str, Any]:
        snapshot = self.snapshot(provider, now=now)
        return {
            "provider": snapshot["provider"],
            "score": snapshot["score"],
            "routing_penalty": snapshot["routing_penalty"],
            "circuit_open": snapshot["circuit_open"],
            "circuit_remaining_seconds": snapshot["circuit_remaining_seconds"],
            "samples": snapshot["samples"],
            "consecutive_failures": snapshot["consecutive_failures"],
        }

    def reset(self, provider: str | None = None) -> None:
        with self._lock:
            if provider is None:
                self._rows.clear()
            else:
                self._rows.pop(provider.strip().lower(), None)


provider_reliability = ProviderReliabilityTracker()
