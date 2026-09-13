from __future__ import annotations

import time
from dataclasses import asdict, dataclass, field
from typing import Any

from .tool_mesh import ToolMesh


@dataclass(frozen=True, slots=True)
class CapabilityCandidate:
    provider: str
    ref: str | None = None
    search: str | None = None
    priority: int = 100
    argument_map: dict[str, str] = field(default_factory=dict)
    defaults: dict[str, Any] = field(default_factory=dict)
    note: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True, slots=True)
class Capability:
    id: str
    name: str
    description: str
    pack: str
    tags: tuple[str, ...]
    candidates: tuple[CapabilityCandidate, ...]
    read_only: bool = True

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "name": self.name,
            "description": self.description,
            "pack": self.pack,
            "tags": list(self.tags),
            "read_only": self.read_only,
            "candidates": [candidate.to_dict() for candidate in self.candidates],
        }


class CapabilityRegistry:
    """Semantic capabilities that resolve to ranked Tool Mesh candidates."""

    def __init__(self, mesh: ToolMesh, capabilities: list[Capability]) -> None:
        self.mesh = mesh
        self.capabilities = {capability.id: capability for capability in capabilities}

    def list(
        self,
        *,
        query: str | None = None,
        pack: str | None = None,
        limit: int = 50,
    ) -> dict[str, Any]:
        words = [word for word in (query or "").casefold().split() if word]
        rows: list[tuple[int, Capability]] = []
        for capability in self.capabilities.values():
            if pack and capability.pack != pack:
                continue
            haystack = " ".join(
                [
                    capability.id,
                    capability.name,
                    capability.description,
                    capability.pack,
                    *capability.tags,
                ]
            ).casefold()
            score = sum(
                5 if word in capability.name.casefold() else 1
                for word in words
                if word in haystack
            )
            if score or not words:
                rows.append((score, capability))
        rows.sort(key=lambda row: (-row[0], row[1].id))
        return {
            "capabilities": [
                capability.to_dict() for _, capability in rows[: max(1, min(limit, 100))]
            ]
        }

    async def resolve(self, capability_id: str) -> dict[str, Any]:
        capability = self._get(capability_id)
        statuses = await self.mesh.provider_status()
        resolved: list[dict[str, Any]] = []
        for candidate in sorted(capability.candidates, key=lambda item: item.priority):
            status = statuses.get(candidate.provider, {})
            if not status.get("searchable") and not status.get("executable"):
                resolved.append(
                    {
                        "candidate": candidate.to_dict(),
                        "available": False,
                        "reason": "provider unavailable",
                    }
                )
                continue
            try:
                ref = await self._resolve_candidate(candidate)
                descriptor = await self.mesh.describe(ref)
                resolved.append(
                    {
                        "candidate": candidate.to_dict(),
                        "available": bool(status.get("executable", True)),
                        "ref": ref,
                        "tool": descriptor,
                    }
                )
            except Exception as exc:  # noqa: BLE001 - third-party provider boundary
                resolved.append(
                    {
                        "candidate": candidate.to_dict(),
                        "available": False,
                        "reason": str(exc),
                    }
                )
        return {"capability": capability.to_dict(), "resolved": resolved}

    async def execute(
        self,
        capability_id: str,
        arguments: dict[str, Any],
        *,
        provider_preference: str | None = None,
        dry_run: bool = False,
        wait_seconds: int = 30,
        timeout_seconds: int = 60,
    ) -> dict[str, Any]:
        capability = self._get(capability_id)
        candidates = sorted(capability.candidates, key=lambda item: item.priority)
        if provider_preference:
            preferred = [item for item in candidates if item.provider == provider_preference]
            others = [item for item in candidates if item.provider != provider_preference]
            candidates = preferred + others

        attempts: list[dict[str, Any]] = []
        started = time.time()
        for candidate in candidates:
            try:
                ref = await self._resolve_candidate(candidate)
                descriptor = await self.mesh.describe(ref)
                if descriptor.get("side_effecting") and capability.read_only:
                    raise PermissionError("read-only capability resolved to a side-effecting tool")
                mapped = self._map_arguments(arguments, candidate)
                execution = await self.mesh.execute(
                    ref,
                    mapped,
                    wait_seconds=wait_seconds,
                    timeout_seconds=timeout_seconds,
                    dry_run=dry_run,
                )
                attempts.append(
                    {
                        "provider": candidate.provider,
                        "ref": ref,
                        "status": execution.get("status"),
                        "error": execution.get("error"),
                    }
                )
                if execution.get("status") != "failed":
                    return {
                        "capability": capability_id,
                        "selected": ref,
                        "attempts": attempts,
                        "execution": execution,
                        "duration_ms": max(0, int((time.time() - started) * 1000)),
                    }
                if not capability.read_only or descriptor.get("side_effecting"):
                    break
            except Exception as exc:  # noqa: BLE001 - read-only provider fallback boundary
                attempts.append(
                    {
                        "provider": candidate.provider,
                        "ref": candidate.ref,
                        "status": "failed",
                        "error": str(exc),
                    }
                )
                if not capability.read_only:
                    break

        return {
            "capability": capability_id,
            "selected": None,
            "attempts": attempts,
            "execution": None,
            "duration_ms": max(0, int((time.time() - started) * 1000)),
            "error": "no capability candidate completed successfully",
        }

    def _get(self, capability_id: str) -> Capability:
        try:
            return self.capabilities[capability_id]
        except KeyError as exc:
            raise ValueError(f"unknown capability: {capability_id}") from exc

    async def _resolve_candidate(self, candidate: CapabilityCandidate) -> str:
        if candidate.ref:
            return candidate.ref
        if not candidate.search:
            raise ValueError("capability candidate must define ref or search")
        result = await self.mesh.search(
            candidate.search,
            providers=[candidate.provider],
            limit=5,
        )
        tools = result.get("tools") or []
        if not tools:
            errors = result.get("errors") or {}
            raise LookupError(errors.get(candidate.provider) or "no matching tool")
        for tool in tools:
            if not tool.get("side_effecting"):
                return str(tool["ref"])
        raise LookupError("search returned no read-only tools")

    @staticmethod
    def _map_arguments(
        arguments: dict[str, Any], candidate: CapabilityCandidate
    ) -> dict[str, Any]:
        mapped = dict(candidate.defaults)
        if candidate.argument_map:
            for source, target in candidate.argument_map.items():
                if source in arguments:
                    mapped[target] = arguments[source]
            for name, value in arguments.items():
                if name not in candidate.argument_map:
                    mapped[name] = value
        else:
            mapped.update(arguments)
        return mapped


def _apify_capabilities() -> list[Capability]:
    return [
        Capability(
            id="web.search.google",
            name="Google SERP search",
            description="Search Google and return structured organic/paid/search metadata.",
            pack="web",
            tags=("web", "search", "google", "serp"),
            candidates=(
                CapabilityCandidate(
                    provider="apify",
                    ref="apify:apify/google-search-scraper",
                    priority=10,
                ),
            ),
        ),
        Capability(
            id="web.fetch.page",
            name="Resilient page fetch",
            description=(
                "Fetch a public web page with JavaScript rendering and anti-bot-capable extraction."
            ),
            pack="web",
            tags=("web", "fetch", "markdown", "browser"),
            candidates=(
                CapabilityCandidate(
                    provider="apify",
                    ref="apify:apify/web-fetch",
                    priority=10,
                ),
            ),
        ),
        Capability(
            id="web.research.rag",
            name="RAG web research",
            description="Search the web, fetch top pages, and return clean content for an agent.",
            pack="web",
            tags=("web", "research", "rag", "search"),
            candidates=(
                CapabilityCandidate(
                    provider="apify",
                    ref="apify:apify/rag-web-browser",
                    priority=10,
                ),
            ),
        ),
        Capability(
            id="social.instagram.scrape",
            name="Instagram public data scrape",
            description="Extract public Instagram posts, reels, profiles, hashtags, and comments.",
            pack="social",
            tags=("social", "instagram", "posts", "profiles", "reels"),
            candidates=(
                CapabilityCandidate(
                    provider="apify",
                    ref="apify:apify/instagram-scraper",
                    priority=10,
                ),
            ),
        ),
        Capability(
            id="social.tiktok.scrape",
            name="TikTok public data scrape",
            description="Extract public TikTok videos, profiles, hashtags, and search results.",
            pack="social",
            tags=("social", "tiktok", "videos", "profiles", "hashtags"),
            candidates=(
                CapabilityCandidate(
                    provider="apify",
                    ref="apify:clockworks/tiktok-scraper",
                    priority=10,
                ),
            ),
        ),
        Capability(
            id="social.x.scrape",
            name="X public data scrape",
            description="Search and extract public X/Twitter posts, profiles, lists, and threads.",
            pack="social",
            tags=("social", "x", "twitter", "posts", "profiles"),
            candidates=(
                CapabilityCandidate(
                    provider="apify",
                    ref="apify:apidojo/tweet-scraper",
                    priority=10,
                ),
            ),
        ),
        Capability(
            id="jobs.linkedin.search",
            name="LinkedIn public jobs search",
            description="Search public LinkedIn job listings and retrieve structured job details.",
            pack="jobs",
            tags=("jobs", "linkedin", "companies", "career"),
            candidates=(
                CapabilityCandidate(
                    provider="apify",
                    ref="apify:curious_coder/linkedin-jobs-scraper",
                    priority=10,
                ),
            ),
        ),
        Capability(
            id="ads.meta.library",
            name="Meta Ads Library research",
            description="Collect public Facebook/Meta Ads Library records for research.",
            pack="ads",
            tags=("ads", "facebook", "meta", "marketing"),
            candidates=(
                CapabilityCandidate(
                    provider="apify",
                    ref="apify:curious_coder/facebook-ads-library-scraper",
                    priority=10,
                ),
            ),
        ),
    ]


def _mlbb_capabilities() -> list[Capability]:
    return [
        Capability(
            id="mlbb.player.lookup",
            name="MLBB player lookup",
            description=(
                "Resolve public/community Mobile Legends player information with a detailed "
                "RapidAPI source first and a nickname-only public fallback."
            ),
            pack="mlbb",
            tags=("mlbb", "mobile-legends", "player", "profile"),
            candidates=(
                CapabilityCandidate(
                    provider="rapidapi",
                    ref="rapidapi:mlbb-player-lookup",
                    priority=10,
                    note="Detailed community player lookup; requires RAPIDAPI_KEY.",
                ),
                CapabilityCandidate(
                    provider="publicapi",
                    ref="publicapi:mlbb-nickname-lookup",
                    priority=50,
                    argument_map={"id": "id", "zone": "server"},
                    note="Nickname-only fallback; requires player id and zone.",
                ),
            ),
        ),
        Capability(
            id="mlbb.nickname.lookup",
            name="MLBB nickname lookup",
            description="Resolve an MLBB nickname from player and zone identifiers.",
            pack="mlbb",
            tags=("mlbb", "mobile-legends", "nickname"),
            candidates=(
                CapabilityCandidate(
                    provider="publicapi",
                    ref="publicapi:mlbb-nickname-lookup",
                    priority=10,
                    argument_map={"id": "id", "zone": "server"},
                ),
                CapabilityCandidate(
                    provider="rapidapi",
                    ref="rapidapi:mlbb-player-lookup",
                    priority=30,
                ),
            ),
        ),
        Capability(
            id="mlbb.hero.list",
            name="MLBB hero list",
            description="Find a public OpenAPI operation that lists Mobile Legends heroes.",
            pack="mlbb",
            tags=("mlbb", "heroes", "game-data"),
            candidates=(
                CapabilityCandidate(
                    provider="openapi", search="rone-mlbb heroes list", priority=10
                ),
            ),
        ),
        Capability(
            id="mlbb.hero.detail",
            name="MLBB hero detail",
            description="Find a public OpenAPI operation for detailed MLBB hero data.",
            pack="mlbb",
            tags=("mlbb", "hero", "detail", "game-data"),
            candidates=(
                CapabilityCandidate(
                    provider="openapi", search="rone-mlbb hero detail", priority=10
                ),
            ),
        ),
        Capability(
            id="mlbb.hero.analytics",
            name="MLBB hero analytics",
            description="Resolve current community hero statistics and analytics operations.",
            pack="mlbb",
            tags=("mlbb", "hero", "analytics", "stats"),
            candidates=(
                CapabilityCandidate(
                    provider="openapi",
                    search="rone-mlbb hero analytics statistics",
                    priority=10,
                ),
            ),
        ),
        Capability(
            id="mlbb.academy.items",
            name="MLBB academy items",
            description="Resolve public MLBB item/reference data from the academy API group.",
            pack="mlbb",
            tags=("mlbb", "academy", "items", "builds"),
            candidates=(
                CapabilityCandidate(
                    provider="openapi", search="rone-mlbb academy items", priority=10
                ),
            ),
        ),
        Capability(
            id="mlbb.academy.spells",
            name="MLBB academy spells",
            description="Resolve public MLBB battle-spell reference data.",
            pack="mlbb",
            tags=("mlbb", "academy", "spells"),
            candidates=(
                CapabilityCandidate(
                    provider="openapi", search="rone-mlbb academy spells", priority=10
                ),
            ),
        ),
        Capability(
            id="mlbb.academy.emblems",
            name="MLBB academy emblems",
            description="Resolve public MLBB emblem/reference data.",
            pack="mlbb",
            tags=("mlbb", "academy", "emblems"),
            candidates=(
                CapabilityCandidate(
                    provider="openapi", search="rone-mlbb academy emblems", priority=10
                ),
            ),
        ),
        Capability(
            id="mlbb.rank.reference",
            name="MLBB rank reference",
            description="Resolve public rank/reference data from the MLBB OpenAPI catalog.",
            pack="mlbb",
            tags=("mlbb", "rank", "academy", "reference"),
            candidates=(
                CapabilityCandidate(
                    provider="openapi", search="rone-mlbb ranks academy", priority=10
                ),
            ),
        ),
    ]


def build_default_capabilities() -> list[Capability]:
    return [*_apify_capabilities(), *_mlbb_capabilities()]
