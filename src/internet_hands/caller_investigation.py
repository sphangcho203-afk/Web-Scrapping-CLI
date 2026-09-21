from __future__ import annotations

import asyncio
from collections import defaultdict
import re
from typing import Any
from urllib.parse import urlsplit

from .caller_intelligence import lookup_caller_intelligence
from .execution_meter import record_provider_call, record_usage
from .fetcher import fetch_url
from .tool_mesh import ToolDescriptor


_SEPARATORS = re.compile(r"\s+(?:\||-|—|–|·)\s+")
_PHONE_CHUNK = re.compile(r"\+?\d[\d\s().-]{6,}\d")
_GENERIC_LABELS = {
    "contact",
    "contact us",
    "home",
    "profile",
    "phone",
    "directory",
    "listing",
    "linkedin",
    "github",
    "gitlab",
    "facebook",
    "instagram",
    "x",
    "twitter",
}


def _digits(value: str) -> str:
    return "".join(ch for ch in value if ch.isdigit())


def _phone_variants(phone_data: dict[str, Any]) -> set[str]:
    formats = phone_data.get("formats") or {}
    number = phone_data.get("number") or {}
    candidates = {
        _digits(str(formats.get("e164") or "")),
        _digits(str(number.get("national_number") or "")),
    }
    return {value for value in candidates if len(value) >= 7}


def _body_mentions_phone(text: str | None, variants: set[str]) -> bool:
    if not text or not variants:
        return False
    for match in _PHONE_CHUNK.finditer(text):
        candidate = _digits(match.group(0))
        if candidate in variants:
            return True
    return False


def _public_label(title: str, source_kind: str) -> str | None:
    title = " ".join(str(title or "").split())
    if not title:
        return None

    parts = [part.strip(" -|—–·") for part in _SEPARATORS.split(title)]
    candidates: list[str] = []
    if source_kind == "professional_platform":
        candidates = parts[:2]
    else:
        candidates = parts

    for candidate in candidates:
        lowered = candidate.casefold()
        if lowered in _GENERIC_LABELS:
            continue
        if any(token in lowered for token in ("linkedin", "github", "facebook", "instagram")):
            continue
        if not (2 <= len(candidate) <= 80):
            continue
        if any(ch.isdigit() for ch in candidate):
            continue
        if "http://" in lowered or "https://" in lowered or "@" in candidate:
            continue
        if not any(ch.isalpha() for ch in candidate):
            continue
        return candidate
    return None


def _select_evidence(
    evidence: list[dict[str, Any]],
    *,
    max_sources: int,
) -> list[dict[str, Any]]:
    selected: list[dict[str, Any]] = []
    deferred: list[dict[str, Any]] = []
    seen_hosts: set[str] = set()

    for item in evidence:
        host = str(item.get("host") or "").casefold()
        if not host:
            host = (urlsplit(str(item.get("url") or "")).hostname or "").casefold()
        if host and host not in seen_hosts:
            selected.append(item)
            seen_hosts.add(host)
        else:
            deferred.append(item)
        if len(selected) >= max_sources:
            return selected

    for item in deferred:
        selected.append(item)
        if len(selected) >= max_sources:
            break
    return selected


def _confidence(
    corroborated: list[dict[str, Any]],
    associations: list[dict[str, Any]],
) -> str:
    domains = {str(item.get("host") or "") for item in corroborated if item.get("host")}
    if not corroborated:
        return "none"

    strong_labels = [
        item
        for item in associations
        if int(item.get("independent_domains") or 0) >= 2
    ]
    if strong_labels and len(domains) >= 2:
        return "high"
    if len(domains) >= 2:
        return "medium"
    return "low"


async def investigate_caller(
    number: str,
    *,
    region: str | None = None,
    max_sources: int = 4,
    telecom_external: bool = False,
    telecom_providers: list[str] | None = None,
    fetch_timeout_seconds: float = 12.0,
    max_bytes_per_source: int = 750_000,
) -> dict[str, Any]:
    source_limit = max(1, min(int(max_sources), 12))
    search_limit = max(5, min(source_limit * 2, 20))

    basic = await lookup_caller_intelligence(
        number,
        region=region,
        public_search=True,
        max_results=search_limit,
        telecom_external=telecom_external,
        telecom_providers=telecom_providers,
    )
    phone_data = dict(basic.get("number") or {})
    variants = _phone_variants(phone_data)
    public = dict(basic.get("public_attribution") or {})
    evidence = [
        dict(item)
        for item in public.get("evidence") or []
        if isinstance(item, dict) and item.get("url")
    ]
    selected = _select_evidence(evidence, max_sources=source_limit)

    semaphore = asyncio.Semaphore(min(3, source_limit))

    async def inspect(item: dict[str, Any]) -> dict[str, Any]:
        url = str(item.get("url") or "")
        host = str(item.get("host") or "")
        source_kind = str(item.get("source_kind") or "public_web")
        label = _public_label(str(item.get("title") or ""), source_kind)

        record_usage("caller_source_fetch")
        record_provider_call("nativeweb")
        async with semaphore:
            try:
                result = await fetch_url(
                    url,
                    timeout=max(2.0, min(float(fetch_timeout_seconds), 30.0)),
                    max_bytes=max(50_000, min(int(max_bytes_per_source), 1_500_000)),
                    include_body=True,
                    max_redirects=5,
                )
            except Exception as exc:  # noqa: BLE001 - public source boundary
                return {
                    "url": url,
                    "host": host,
                    "source_kind": source_kind,
                    "fetch_status": "failed",
                    "phone_mentioned": False,
                    "public_label": None,
                    "error": f"{type(exc).__name__}: {exc}"[:180],
                }

        record_usage("caller_source_fetch_success")
        mentioned = _body_mentions_phone(result.body_text, variants)
        if mentioned:
            record_usage("caller_source_corroborated")
        return {
            "url": url,
            "host": host,
            "source_kind": source_kind,
            "fetch_status": "completed",
            "http_status": int(result.status_code),
            "phone_mentioned": mentioned,
            "public_label": label if mentioned else None,
        }

    rows = await asyncio.gather(*(inspect(item) for item in selected))
    corroborated = [item for item in rows if item.get("phone_mentioned")]

    label_domains: dict[str, set[str]] = defaultdict(set)
    label_display: dict[str, str] = {}
    label_sources: dict[str, list[str]] = defaultdict(list)
    for item in corroborated:
        label = str(item.get("public_label") or "").strip()
        if not label:
            continue
        key = label.casefold()
        label_display.setdefault(key, label)
        if item.get("host"):
            label_domains[key].add(str(item["host"]))
        label_sources[key].append(str(item["url"]))

    associations = [
        {
            "label": label_display[key],
            "independent_domains": len(label_domains[key]),
            "evidence_count": len(label_sources[key]),
            "sources": label_sources[key],
        }
        for key in sorted(
            label_display,
            key=lambda value: (
                -len(label_domains[value]),
                -len(label_sources[value]),
                value,
            ),
        )
    ]

    corroborated_domains = sorted(
        {str(item.get("host") or "") for item in corroborated if item.get("host")}
    )
    confidence = _confidence(corroborated, associations)

    return {
        "number": phone_data,
        "investigation": {
            "status": (
                "corroborated_public_association"
                if corroborated
                else "no_corroborated_public_association"
            ),
            "confidence": confidence,
            "searched_results": len(evidence),
            "sources_selected": len(selected),
            "sources_fetched": sum(item.get("fetch_status") == "completed" for item in rows),
            "corroborated_sources": len(corroborated),
            "independent_corroborated_domains": len(corroborated_domains),
            "domains": corroborated_domains,
            "public_associations": associations,
            "evidence": rows,
            "interpretation": (
                "A corroborated public association means the exact normalized phone number "
                "was observed on the cited public page. It does not prove telecom subscriber "
                "ownership or expose private carrier records."
            ),
        },
        "policy": {
            "public_web_only": True,
            "raw_page_content_returned": False,
            "search_snippets_returned": False,
            "private_subscriber_identity": False,
            "private_address": False,
            "secrets": False,
        },
    }


class CallerInvestigationProvider:
    name = "callerresearch"

    async def status(self) -> dict[str, Any]:
        return {
            "configured": True,
            "searchable": True,
            "executable": True,
            "kind": "caller-public-investigation",
            "tool_count": 1,
            "fetch_backend": "native-public-http",
        }

    async def search(self, query: str, *, limit: int = 10) -> list[ToolDescriptor]:
        descriptor = await self.describe("investigate")
        words = [word for word in query.casefold().split() if word]
        haystack = " ".join(
            [descriptor.tool_id, descriptor.name, descriptor.description, *descriptor.tags]
        ).casefold()
        if words and not any(word in haystack for word in words):
            return []
        return [descriptor][: max(1, min(limit, 10))]

    async def describe(self, tool_id: str) -> ToolDescriptor:
        if tool_id != "investigate":
            raise ValueError(f"unknown callerresearch tool: {tool_id}")
        return ToolDescriptor(
            ref="callerresearch:investigate",
            provider=self.name,
            tool_id="investigate",
            name="Deep unknown-caller public investigation",
            description=(
                "Search and corroborate bounded public web sources for an unknown phone "
                "number without returning raw page content or private subscriber records."
            ),
            input_schema={
                "type": "object",
                "required": ["number"],
                "properties": {
                    "number": {"type": "string", "minLength": 3, "maxLength": 64},
                    "region": {"type": "string", "minLength": 2, "maxLength": 2},
                    "max_sources": {"type": "integer", "minimum": 1, "maximum": 12},
                    "telecom_external": {"type": "boolean"},
                    "telecom_providers": {
                        "type": "array",
                        "items": {
                            "type": "string",
                            "enum": ["veriphone", "abstract", "numverify", "twilio"],
                        },
                        "maxItems": 4,
                    },
                },
                "additionalProperties": False,
            },
            output_schema={},
            tags=[
                "phone",
                "caller",
                "investigation",
                "osint",
                "public-web",
                "corroboration",
            ],
            requires_auth=False,
            side_effecting=False,
            metadata={
                "configured": True,
                "public_only": True,
                "private_subscriber_identity": False,
            },
        )

    async def execute(
        self,
        tool_id: str,
        arguments: dict[str, Any],
        *,
        account: str | None = None,
        wait_seconds: int = 30,
        timeout_seconds: int = 60,
        options: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        del account, wait_seconds, options
        await self.describe(tool_id)
        number = str(arguments.get("number") or "").strip()
        if not number:
            raise ValueError("number is required")
        providers_raw = arguments.get("telecom_providers")
        providers = (
            [str(item) for item in providers_raw]
            if isinstance(providers_raw, list)
            else None
        )
        data = await investigate_caller(
            number,
            region=str(arguments.get("region") or "").strip() or None,
            max_sources=int(arguments.get("max_sources", 4)),
            telecom_external=bool(arguments.get("telecom_external", False)),
            telecom_providers=providers,
            fetch_timeout_seconds=min(max(float(timeout_seconds), 2.0), 30.0),
        )
        return {
            "status": "completed",
            "data": data,
            "metadata": {
                "provider": self.name,
                "public_only": True,
                "fetch_backend": "native-public-http",
            },
        }

    async def job_status(self, job_id: str, *, wait_seconds: int = 0) -> dict[str, Any]:
        del job_id, wait_seconds
        raise ValueError("caller investigation completes synchronously")

    async def result_page(
        self, result_id: str, *, offset: int = 0, limit: int = 100
    ) -> dict[str, Any]:
        del result_id, offset, limit
        raise ValueError("caller investigation returns bounded inline results")
