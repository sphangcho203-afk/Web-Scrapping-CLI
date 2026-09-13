from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path
from typing import Any

from .backends import DEFAULT_BACKEND_ROOT, backend_status, module_available


class BackendIntent(StrEnum):
    STATIC = "static"
    DYNAMIC = "dynamic"
    INTERACTIVE = "interactive"
    THROUGHPUT = "throughput"
    ARTICLE = "article"
    LLM_EXTRACTION = "llm-extraction"


@dataclass(frozen=True, slots=True)
class RouteCandidate:
    name: str
    state: str
    reason: str

    @property
    def runtime_ready(self) -> bool:
        return self.state in {"native", "runtime-ready"}


ROUTES: dict[BackendIntent, tuple[tuple[str, str], ...]] = {
    BackendIntent.STATIC: (
        ("native-http", "Fastest path with exact-byte provenance and policy enforcement."),
        ("crawlee-python", "Useful when queueing, retries, and crawl autoscaling are needed."),
        ("scrapy", "Good high-throughput HTTP fallback for large crawl jobs."),
    ),
    BackendIntent.DYNAMIC: (
        ("native-playwright", "Guarded Playwright renderer integrated with Internet Hands."),
        ("crawl4ai", "Browser-oriented extraction for LLM-focused collection."),
        ("crawlee-python", "PlaywrightCrawler can scale browser crawling when installed."),
    ),
    BackendIntent.INTERACTIVE: (
        ("playwright-mcp", "Persistent agent/browser loop with accessibility snapshots."),
        ("native-playwright", "Local rendered-page fallback without an MCP client."),
    ),
    BackendIntent.THROUGHPUT: (
        ("crawlee-python", "Request queues, retries, sessions, concurrency, and crawl limits."),
        ("scrapy", "Mature asynchronous crawling for large HTTP workloads."),
        ("native-http", "Built-in bounded concurrent hunt frontier."),
    ),
    BackendIntent.ARTICLE: (
        ("trafilatura", "Main-text and metadata extraction from already captured HTML."),
        ("native-http", "Native parser remains the always-available fallback."),
        ("crawl4ai", "Useful when article extraction also needs browser rendering."),
    ),
    BackendIntent.LLM_EXTRACTION: (
        ("crawl4ai", "LLM-oriented extraction and browser collection."),
        ("trafilatura", "Deterministic content cleanup before downstream model analysis."),
        ("native-playwright", "Render dynamic HTML before deterministic/model extraction."),
    ),
}


def route_backend(
    intent: BackendIntent,
    *,
    root: Path = DEFAULT_BACKEND_ROOT,
) -> dict[str, Any]:
    candidates = [
        _candidate(name, reason, root=root)
        for name, reason in ROUTES[intent]
    ]
    selected = next((item.name for item in candidates if item.runtime_ready), None)
    return {
        "intent": intent.value,
        "selected": selected,
        "candidates": [
            {
                "name": item.name,
                "state": item.state,
                "runtime_ready": item.runtime_ready,
                "reason": item.reason,
            }
            for item in candidates
        ],
        "note": (
            "Staged source is not treated as executable. Install/configure a backend before "
            "the router reports it runtime-ready."
        ),
    }


def _candidate(name: str, reason: str, *, root: Path) -> RouteCandidate:
    if name == "native-http":
        return RouteCandidate(name, "native", reason)
    if name == "native-playwright":
        ready = module_available("playwright")
        return RouteCandidate(name, "runtime-ready" if ready else "unavailable", reason)
    if name == "trafilatura" and module_available("trafilatura"):
        return RouteCandidate(name, "runtime-ready", reason)

    status = backend_status(name, root=root)
    if status.get("command_ready") or status.get("import_ready"):
        state = "runtime-ready"
    elif status.get("cloned"):
        state = "staged-source"
    elif status.get("integration") == "external-service":
        state = "external-service"
    else:
        state = "unavailable"
    return RouteCandidate(name, state, reason)
