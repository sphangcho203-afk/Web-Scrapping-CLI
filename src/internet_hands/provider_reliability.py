from __future__ import annotations

import os
import threading
import time
from dataclasses import asdict, dataclass
from typing import Any

from .provider_reliability_store import shared_provider_reliability

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
    last_error_class: str | None = None
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

    def __init__(self, shared_store: Any | None = None) -> None:
        self._rows: dict[str, ProviderReliability] = {}
        self._lock = threading.Lock()
        self._shared = (
            shared_provider_reliability
            if shared_store is None
            else shared_store
        )
        self._shared_cache: dict[str, dict[str, Any]] = {}
        self._shared_cache_at = 0.0
        self._shared_lock = threading.Lock()
        self._shared_error: str | None = None

    @staticmethod
    def enabled() -> bool:
        return _enabled()

    def shared_configured(self) -> bool:
        return bool(getattr(self._shared, "configured", False))

    @staticmethod
    def _shared_refresh_seconds() -> int:
        return _env_int(
            "OPENCRAWL_PROVIDER_SHARED_REFRESH_SECONDS",
            15,
            minimum=1,
            maximum=300,
        )

    def _refresh_shared(
        self,
        *,
        now: float | None = None,
        force: bool = False,
    ) -> dict[str, dict[str, Any]]:
        current = time.time() if now is None else now
        if not self.shared_configured():
            return {}
        if (
            not force
            and self._shared_cache_at > 0
            and current - self._shared_cache_at < self._shared_refresh_seconds()
        ):
            return self._shared_cache
        with self._shared_lock:
            if (
                not force
                and self._shared_cache_at > 0
                and current - self._shared_cache_at < self._shared_refresh_seconds()
            ):
                return self._shared_cache
            try:
                rows = self._shared.snapshot()
            except Exception as exc:  # noqa: BLE001 - shared health must not break execution
                self._shared_error = f"{type(exc).__name__}: {exc}"[:500]
                return self._shared_cache
            self._shared_cache = dict(rows or {})
            self._shared_cache_at = current
            self._shared_error = None
            return self._shared_cache

    @staticmethod
    def _shared_public(row: dict[str, Any], now: float) -> dict[str, Any]:
        state = ProviderReliability(
            provider=str(row.get("provider") or ""),
            successes=int(row.get("successes") or 0),
            failures=int(row.get("failures") or 0),
            neutral=int(row.get("neutral") or 0),
            consecutive_failures=int(row.get("consecutive_failures") or 0),
            ewma_latency_ms=(
                float(row["ewma_latency_ms"])
                if row.get("ewma_latency_ms") is not None
                else None
            ),
            last_success_at=row.get("last_success_at"),
            last_failure_at=row.get("last_failure_at"),
            last_error=row.get("last_error"),
            last_error_class=row.get("last_error_class"),
            circuit_open_until=float(row.get("circuit_open_until") or 0.0),
        )
        public = state.to_public_dict(now)
        public["scope"] = "shared"
        return public

    @staticmethod
    def _merge_public(
        local: dict[str, Any],
        shared: dict[str, Any] | None,
        *,
        now: float,
    ) -> dict[str, Any]:
        if shared is None:
            return local
        shared_public = ProviderReliabilityTracker._shared_public(shared, now)
        local_has_signal = bool(
            int(local.get("samples") or 0)
            or int(local.get("neutral") or 0)
        )
        shared_has_signal = bool(
            int(shared_public.get("samples") or 0)
            or int(shared_public.get("neutral") or 0)
        )
        scores = [
            int(row["score"])
            for row in (local, shared_public)
            if int(row.get("samples") or 0) > 0
        ]
        effective = dict(shared_public if shared_has_signal else local)
        effective.update(
            {
                "provider": local.get("provider") or shared_public.get("provider"),
                "score": min(scores) if scores else 75,
                "routing_penalty": max(
                    int(local.get("routing_penalty") or 0),
                    int(shared_public.get("routing_penalty") or 0),
                ),
                "circuit_open": bool(local.get("circuit_open"))
                or bool(shared_public.get("circuit_open")),
                "circuit_remaining_seconds": max(
                    int(local.get("circuit_remaining_seconds") or 0),
                    int(shared_public.get("circuit_remaining_seconds") or 0),
                ),
                "consecutive_failures": max(
                    int(local.get("consecutive_failures") or 0),
                    int(shared_public.get("consecutive_failures") or 0),
                ),
                "samples": max(
                    int(local.get("samples") or 0),
                    int(shared_public.get("samples") or 0),
                ),
                "scope": "runtime+shared" if local_has_signal else "shared",
                "local": local,
                "shared": shared_public,
            }
        )
        return effective

    def diagnostics(self) -> dict[str, Any]:
        return {
            "enabled": self.enabled(),
            "shared_configured": self.shared_configured(),
            "shared_refresh_seconds": self._shared_refresh_seconds(),
            "shared_last_refresh_at": self._shared_cache_at or None,
            "shared_error": self._shared_error,
        }

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
        error_class: str | None = None,
        now: float | None = None,
    ) -> dict[str, Any]:
        if not _enabled():
            current = time.time() if now is None else now
            return ProviderReliability(
                provider=provider.strip().lower()
            ).to_public_dict(current)
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
                row.last_error_class = None
                row.circuit_open_until = 0.0
            else:
                row.failures += 1
                row.consecutive_failures += 1
                row.last_failure_at = current
                row.last_error = (str(error or normalized_status).strip() or normalized_status)[:500]
                row.last_error_class = (
                    str(error_class).strip().lower()[:80]
                    if error_class
                    else None
                )
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
        shared_rows = self._refresh_shared(now=current)
        with self._lock:
            if provider is not None:
                normalized = provider.strip().lower()
                row = self._rows.get(normalized)
                local = (
                    row.to_public_dict(current)
                    if row is not None
                    else ProviderReliability(provider=normalized).to_public_dict(current)
                )
                return self._merge_public(
                    local,
                    shared_rows.get(normalized),
                    now=current,
                )

            names = set(self._rows) | set(shared_rows)
            result: dict[str, Any] = {}
            for name in sorted(names):
                row = self._rows.get(name)
                local = (
                    row.to_public_dict(current)
                    if row is not None
                    else ProviderReliability(provider=name).to_public_dict(current)
                )
                result[name] = self._merge_public(
                    local,
                    shared_rows.get(name),
                    now=current,
                )
            return result

    def routing_state(self, provider: str, *, now: float | None = None) -> dict[str, Any]:
        if not self.enabled():
            current = time.time() if now is None else now
            snapshot = ProviderReliability(
                provider=provider.strip().lower()
            ).to_public_dict(current)
        else:
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
        if self.shared_configured():
            self._shared.reset(provider)
        with self._shared_lock:
            if provider is None:
                self._shared_cache.clear()
            else:
                self._shared_cache.pop(provider.strip().lower(), None)
            self._shared_cache_at = 0.0


provider_reliability = ProviderReliabilityTracker()
