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
    when: dict[str, Any] = field(default_factory=dict)
    passthrough_arguments: bool = True
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
    input_schema: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "name": self.name,
            "description": self.description,
            "pack": self.pack,
            "tags": list(self.tags),
            "read_only": self.read_only,
            "input_schema": self.input_schema,
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
                        "available": bool(status.get("executable", True))
                        and (descriptor.get("metadata") or {}).get("configured", True) is not False,
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
        account: str | None = None,
        allow_side_effects: bool = False,
        dry_run: bool = False,
        wait_seconds: int = 30,
        timeout_seconds: int = 60,
    ) -> dict[str, Any]:
        capability = self._get(capability_id)
        if not capability.read_only and not dry_run and not allow_side_effects:
            raise PermissionError(
                "side-effecting capability requires allow_side_effects=true or dry_run=true"
            )
        candidates = sorted(capability.candidates, key=lambda item: item.priority)
        if provider_preference:
            preferred = [item for item in candidates if item.provider == provider_preference]
            others = [item for item in candidates if item.provider != provider_preference]
            candidates = preferred + others

        attempts: list[dict[str, Any]] = []
        started = time.time()
        statuses = await self.mesh.provider_status()

        for candidate in candidates:
            if not self._candidate_matches(arguments, candidate):
                attempts.append(
                    {
                        "provider": candidate.provider,
                        "ref": candidate.ref,
                        "status": "skipped",
                        "error": "candidate conditions did not match",
                    }
                )
                continue

            provider_status = statuses.get(candidate.provider, {})
            provider_ready = bool(provider_status.get("executable"))
            dry_run_ready = bool(
                provider_status.get("searchable")
                or provider_status.get("executable")
                or provider_status.get("configured")
            )
            if not provider_ready and not (dry_run and dry_run_ready):
                attempts.append(
                    {
                        "provider": candidate.provider,
                        "ref": candidate.ref,
                        "status": "skipped",
                        "error": "provider is not executable",
                    }
                )
                continue

            # Resolution and schema inspection are preflight-only operations. It is safe
            # to try a later provider when this stage fails, even for write capabilities.
            try:
                ref = await self._resolve_candidate(candidate)
                descriptor = await self.mesh.describe(ref)
            except Exception as exc:  # noqa: BLE001 - provider preflight boundary
                attempts.append(
                    {
                        "provider": candidate.provider,
                        "ref": candidate.ref,
                        "status": "preflight_failed",
                        "error": str(exc),
                    }
                )
                continue

            if descriptor.get("side_effecting") and capability.read_only:
                attempts.append(
                    {
                        "provider": candidate.provider,
                        "ref": ref,
                        "status": "preflight_failed",
                        "error": "read-only capability resolved to a side-effecting tool",
                    }
                )
                continue

            configured = (descriptor.get("metadata") or {}).get("configured", True)
            if configured is False and not dry_run:
                attempts.append(
                    {
                        "provider": candidate.provider,
                        "ref": ref,
                        "status": "skipped",
                        "error": "tool is not configured",
                    }
                )
                continue

            mapped = self._map_arguments(arguments, candidate)
            try:
                execution = await self.mesh.execute(
                    ref,
                    mapped,
                    account=account,
                    wait_seconds=wait_seconds,
                    timeout_seconds=timeout_seconds,
                    dry_run=dry_run,
                )
            except Exception as exc:  # noqa: BLE001 - provider execution boundary
                execution = {"status": "failed", "error": str(exc)}

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

            # After a side-effecting execution has actually started we fail closed.
            # Retrying another backend could duplicate an action whose outcome is unknown.
            if not capability.read_only or descriptor.get("side_effecting"):
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
    def _candidate_matches(
        arguments: dict[str, Any], candidate: CapabilityCandidate
    ) -> bool:
        return all(arguments.get(name) == value for name, value in candidate.when.items())

    @staticmethod
    def _map_arguments(
        arguments: dict[str, Any], candidate: CapabilityCandidate
    ) -> dict[str, Any]:
        mapped = dict(candidate.defaults)
        if candidate.argument_map:
            for source, target in candidate.argument_map.items():
                if source in arguments:
                    mapped[target] = arguments[source]
            if candidate.passthrough_arguments:
                for name, value in arguments.items():
                    if name not in candidate.argument_map and name not in candidate.when:
                        mapped[name] = value
        elif candidate.passthrough_arguments:
            for name, value in arguments.items():
                if name not in candidate.when:
                    mapped[name] = value
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



def _phone_capabilities() -> list[Capability]:
    return [
        Capability(
            id="phone.number.lookup",
            name="Phone number intelligence",
            description=(
                "Inspect a phone number for validity, country/region, carrier, line type, "
                "formatting, time zones, MCC/MNC and configured telecom risk signals "
                "without identifying a private subscriber."
            ),
            pack="phone",
            tags=("phone", "telecom", "carrier", "line-type", "sim-swap", "lookup"),
            input_schema={
                "type": "object",
                "required": ["number"],
                "properties": {
                    "number": {"type": "string"},
                    "region": {"type": "string"},
                    "external": {"type": "boolean"},
                    "providers": {
                        "type": "array",
                        "items": {
                            "type": "string",
                            "enum": ["veriphone", "abstract", "numverify", "twilio"],
                        },
                    },
                },
            },
            candidates=(
                CapabilityCandidate(
                    provider="phoneintel",
                    ref="phoneintel:lookup",
                    priority=10,
                    argument_map={
                        "number": "number",
                        "region": "region",
                        "external": "external",
                        "providers": "providers",
                    },
                    passthrough_arguments=False,
                    note="First-party phone intelligence provider with local libphonenumber fallback.",
                ),
            ),
        ),
    ]


def _caller_capabilities() -> list[Capability]:
    return [
        Capability(
            id="phone.caller.lookup",
            name="Unknown caller public intelligence",
            description=(
                "Combine phone-network metadata with bounded exact-number public-web "
                "evidence for an unknown caller without exposing private subscriber records."
            ),
            pack="phone",
            tags=("phone", "caller", "unknown-call", "osint", "public-web"),
            input_schema={
                "type": "object",
                "required": ["number"],
                "properties": {
                    "number": {"type": "string"},
                    "region": {"type": "string"},
                    "public_search": {"type": "boolean"},
                    "max_results": {"type": "integer", "minimum": 1, "maximum": 20},
                    "telecom_external": {"type": "boolean"},
                    "telecom_providers": {
                        "type": "array",
                        "items": {
                            "type": "string",
                            "enum": ["veriphone", "abstract", "numverify", "twilio"],
                        },
                    },
                },
            },
            candidates=(
                CapabilityCandidate(
                    provider="callerintel",
                    ref="callerintel:lookup",
                    priority=10,
                    argument_map={
                        "number": "number",
                        "region": "region",
                        "public_search": "public_search",
                        "max_results": "max_results",
                        "telecom_external": "telecom_external",
                        "telecom_providers": "telecom_providers",
                    },
                    passthrough_arguments=False,
                    note="First-party bounded public caller-attribution provider.",
                ),
            ),
        ),
        Capability(
            id="phone.caller.investigate",
            name="Deep unknown-caller public investigation",
            description=(
                "Corroborate an unknown phone number across bounded public web sources, "
                "fetch selected evidence pages, and report confidence without exposing "
                "private subscriber records or raw page content."
            ),
            pack="phone",
            tags=("phone", "caller", "investigation", "osint", "public-web", "corroboration"),
            input_schema={"type": "object", "required": ["number"], "properties": {
                "number": {"type": "string"}, "region": {"type": "string"},
                "max_sources": {"type": "integer", "minimum": 1, "maximum": 12},
                "telecom_external": {"type": "boolean"},
                "telecom_providers": {"type": "array", "items": {"type": "string", "enum": ["veriphone", "abstract", "numverify", "twilio"]}},
            }},
            candidates=(CapabilityCandidate(
                provider="callerresearch", ref="callerresearch:investigate", priority=10,
                argument_map={"number": "number", "region": "region", "max_sources": "max_sources", "telecom_external": "telecom_external", "telecom_providers": "telecom_providers"},
                passthrough_arguments=False,
                note="First-party bounded public corroboration engine with source verification.",
            ),),
        ),
    ]


def _connected_capabilities() -> list[Capability]:
    return [
        Capability(
            id="browser.navigate",
            name="Browser navigation task",
            description=(
                "Run a natural-language browser task without exposing the underlying browser vendor."
            ),
            pack="connected",
            tags=("browser", "automation", "navigate", "connected"),
            read_only=False,
            input_schema={
                "type": "object",
                "required": ["goal"],
                "properties": {
                    "goal": {"type": "string"},
                    "url": {"type": "string"},
                    "session_id": {"type": "string"},
                    "secrets": {"type": "object"},
                },
            },
            candidates=(
                CapabilityCandidate(
                    provider="composio",
                    ref="composio:BROWSER_TOOL_CREATE_TASK",
                    priority=10,
                    argument_map={
                        "goal": "task",
                        "url": "startUrl",
                        "session_id": "sessionId",
                        "secrets": "secrets",
                    },
                    passthrough_arguments=False,
                    note="Composio cloud browser task.",
                ),
            ),
        ),
        Capability(
            id="browser.task.status",
            name="Browser task status",
            description="Inspect progress and results from a semantic browser task.",
            pack="connected",
            tags=("browser", "automation", "status", "connected"),
            input_schema={
                "type": "object",
                "required": ["task_id"],
                "properties": {
                    "task_id": {"type": "string"},
                    "last_step_seen": {"type": "integer"},
                },
            },
            candidates=(
                CapabilityCandidate(
                    provider="composio",
                    ref="composio:BROWSER_TOOL_WATCH_TASK",
                    priority=10,
                    argument_map={
                        "task_id": "taskId",
                        "last_step_seen": "lastStepSeen",
                    },
                    passthrough_arguments=False,
                ),
            ),
        ),
        Capability(
            id="automation.workflow",
            name="Workflow execution",
            description="Execute an automation workflow without exposing n8n-specific field names.",
            pack="connected",
            tags=("automation", "workflow", "n8n", "connected"),
            read_only=False,
            input_schema={
                "type": "object",
                "required": ["workflow_id"],
                "properties": {
                    "workflow_id": {"type": "string"},
                    "mode": {"enum": ["manual", "production"]},
                    "inputs": {"type": "object"},
                    "trigger": {"type": "string"},
                },
            },
            candidates=(
                CapabilityCandidate(
                    provider="composio",
                    ref="composio:CUSTOM_N8N_EXECUTE_WORKFLOW",
                    priority=10,
                    argument_map={
                        "workflow_id": "workflowId",
                        "mode": "executionMode",
                        "inputs": "inputs",
                        "trigger": "triggerNodeName",
                    },
                    defaults={"executionMode": "manual"},
                    passthrough_arguments=False,
                    note="Connected n8n workflow execution.",
                ),
            ),
        ),
        Capability(
            id="automation.workflow.status",
            name="Workflow execution status",
            description="Inspect an automation workflow execution and optionally include node data.",
            pack="connected",
            tags=("automation", "workflow", "status", "n8n", "connected"),
            input_schema={
                "type": "object",
                "required": ["workflow_id", "execution_id"],
                "properties": {
                    "workflow_id": {"type": "string"},
                    "execution_id": {"type": "string"},
                    "include_data": {"type": "boolean"},
                    "node_names": {"type": "array", "items": {"type": "string"}},
                    "truncate_data": {"type": "integer"},
                },
            },
            candidates=(
                CapabilityCandidate(
                    provider="composio",
                    ref="composio:CUSTOM_N8N_GET_WORKFLOW_EXECUTION",
                    priority=10,
                    argument_map={
                        "workflow_id": "workflowId",
                        "execution_id": "executionId",
                        "include_data": "includeData",
                        "node_names": "nodeNames",
                        "truncate_data": "truncateData",
                    },
                    passthrough_arguments=False,
                ),
            ),
        ),
        Capability(
            id="messaging.send",
            name="Send connected message",
            description="Send a message through a supported connected messaging backend.",
            pack="connected",
            tags=("messaging", "telegram", "discord", "send", "connected"),
            read_only=False,
            input_schema={
                "type": "object",
                "required": ["platform", "target", "message"],
                "properties": {
                    "platform": {"enum": ["telegram", "discord"]},
                    "target": {"type": ["string", "integer"]},
                    "message": {"type": "string"},
                    "parse_mode": {"type": "string"},
                    "silent": {"type": "boolean"},
                    "reply_to_message_id": {"type": ["string", "integer"]},
                },
            },
            candidates=(
                CapabilityCandidate(
                    provider="composio",
                    ref="composio:TELEGRAM_SEND_MESSAGE",
                    priority=10,
                    when={"platform": "telegram"},
                    argument_map={
                        "target": "chat_id",
                        "message": "text",
                        "parse_mode": "parse_mode",
                        "silent": "disable_notification",
                        "reply_to_message_id": "reply_to_message_id",
                    },
                    passthrough_arguments=False,
                ),
                CapabilityCandidate(
                    provider="composio",
                    ref="composio:DISCORDBOT_CREATE_MESSAGE",
                    priority=10,
                    when={"platform": "discord"},
                    argument_map={
                        "target": "channel_id",
                        "message": "content",
                        "reply_to_message_id": "message_reference",
                    },
                    passthrough_arguments=False,
                    note="reply_to_message_id should use a full message_reference for advanced replies.",
                ),
            ),
        ),
        Capability(
            id="code.execute",
            name="Isolated code execution",
            description=(
                "Execute a shell command in an isolated connected cloud sandbox."
            ),
            pack="connected",
            tags=("code", "shell", "sandbox", "execute", "connected"),
            read_only=False,
            input_schema={
                "type": "object",
                "required": ["command"],
                "properties": {
                    "command": {"type": "string"},
                    "timeout_seconds": {"type": "integer"},
                    "background": {"type": "boolean"},
                    "restart": {"type": "boolean"},
                },
            },
            candidates=(
                CapabilityCandidate(
                    provider="composio",
                    ref="composio:HIGGSFIELD_MCP_SANDBOX_EXEC",
                    priority=10,
                    argument_map={
                        "command": "command",
                        "timeout_seconds": "timeout_seconds",
                        "background": "background",
                        "restart": "restart",
                    },
                    passthrough_arguments=False,
                    note="Ephemeral isolated Higgsfield Linux sandbox.",
                ),
                CapabilityCandidate(
                    provider="nativesandbox",
                    ref="nativesandbox:exec",
                    priority=50,
                    argument_map={
                        "command": "command",
                        "timeout_seconds": "timeout_seconds",
                        "background": "background",
                        "restart": "restart",
                    },
                    passthrough_arguments=False,
                    note="First-party Vercel Sandbox fallback selected only during preflight.",
                ),
            ),
        ),
    ]


def _github_capabilities() -> list[Capability]:
    return [
        Capability(
            id="repo.search", name="Find public source repositories",
            description="Search public GitHub repositories by topic and inspect source, license and freshness.",
            pack="repositories", tags=("github", "repository", "search", "public"),
            candidates=(CapabilityCandidate(provider="githubpublic", ref="githubpublic:search"),),
        ),
        Capability(
            id="repo.inspect", name="Inspect public repository",
            description="Inspect a public repository tree and documented API specifications without executing its code.",
            pack="repositories", tags=("github", "repository", "openapi", "oauth", "public"),
            candidates=(CapabilityCandidate(provider="githubpublic", ref="githubpublic:inspect"),),
        ),
    ]


def build_default_capabilities() -> list[Capability]:
    return [*_apify_capabilities(), *_mlbb_capabilities(), *_phone_capabilities(), *_caller_capabilities(), *_connected_capabilities(), *_github_capabilities()]
