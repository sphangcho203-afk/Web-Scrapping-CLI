from __future__ import annotations

import os
from typing import Any
from urllib.parse import urlsplit

from .phone_intelligence import lookup_phone_intelligence
from .tool_mesh import ToolDescriptor
from .web_search import SearchKind, brave_search


class CallerIntelligenceError(RuntimeError):
    pass


_PROFESSIONAL_HOSTS = (
    "linkedin.com",
    "github.com",
    "gitlab.com",
    "about.me",
)

_DIRECTORY_TOKENS = (
    "directory",
    "listing",
    "contact",
    "business",
    "company",
    "profile",
)


def _host(url: str) -> str:
    return (urlsplit(url).hostname or "").casefold().removeprefix("www.")


def _source_kind(url: str, title: str) -> str:
    host = _host(url)
    if any(host == domain or host.endswith("." + domain) for domain in _PROFESSIONAL_HOSTS):
        return "professional_platform"
    haystack = f"{host} {title}".casefold()
    if any(token in haystack for token in _DIRECTORY_TOKENS):
        return "directory_or_listing"
    return "public_web"


def _result_rows(record: dict[str, Any], limit: int) -> list[dict[str, Any]]:
    data = record.get("data") or {}
    response = data.get("response") if isinstance(data, dict) else {}
    if not isinstance(response, dict):
        return []
    web = response.get("web")
    if not isinstance(web, dict):
        return []
    results = web.get("results")
    if not isinstance(results, list):
        return []

    rows: list[dict[str, Any]] = []
    seen: set[str] = set()
    for index, item in enumerate(results):
        if not isinstance(item, dict):
            continue
        url = str(item.get("url") or "").strip()
        title = " ".join(str(item.get("title") or "").split())[:240]
        if not url or not title:
            continue
        if url in seen:
            continue
        seen.add(url)
        rows.append(
            {
                "rank": index + 1,
                "title": title,
                "url": url,
                "host": _host(url),
                "source_kind": _source_kind(url, title),
            }
        )
        if len(rows) >= limit:
            break
    return rows


def _footprint_strength(evidence: list[dict[str, Any]]) -> str:
    domains = {str(item.get("host") or "") for item in evidence if item.get("host")}
    count = len(domains)
    if count >= 4:
        return "broad"
    if count >= 2:
        return "multiple_sources"
    if count == 1:
        return "single_source"
    return "none"


async def lookup_caller_intelligence(
    number: str,
    *,
    region: str | None = None,
    public_search: bool = True,
    max_results: int = 8,
    telecom_external: bool = False,
    telecom_providers: list[str] | None = None,
) -> dict[str, Any]:
    limit = max(1, min(int(max_results), 20))
    telecom = await lookup_phone_intelligence(
        number,
        default_region=region,
        external=telecom_external,
        providers=telecom_providers,
    )
    e164 = str((telecom.get("formats") or {}).get("e164") or number)

    evidence: list[dict[str, Any]] = []
    search_status = "disabled"
    search_error: str | None = None

    if public_search:
        if not os.getenv("BRAVE_SEARCH_API_KEY", "").strip():
            search_status = "unavailable"
            search_error = "BRAVE_SEARCH_API_KEY is not configured"
        else:
            search_status = "completed"
            try:
                record = await brave_search(
                    f'"{e164}"',
                    kind=SearchKind.WEB,
                    count=limit,
                )
                evidence = _result_rows(record, limit)
            except Exception as exc:  # noqa: BLE001 - public search provider boundary
                search_status = "failed"
                search_error = f"{type(exc).__name__}: {exc}"[:300]

    domains = sorted(
        {str(item.get("host") or "") for item in evidence if item.get("host")}
    )

    return {
        "number": telecom,
        "public_attribution": {
            "status": (
                "public_evidence_found"
                if evidence
                else "no_public_evidence"
                if search_status == "completed"
                else search_status
            ),
            "footprint_strength": _footprint_strength(evidence),
            "independent_domains": len(domains),
            "domains": domains,
            "evidence": evidence,
            "search_error": search_error,
            "interpretation": (
                "Search results are public attribution leads, not proof of subscriber identity. "
                "A deeper investigation should fetch and corroborate independent pages before "
                "assigning a person or organization."
            ),
        },
        "policy": {
            "private_subscriber_identity": False,
            "private_address": False,
            "secrets": False,
            "public_professional_or_business_evidence": True,
        },
    }


class CallerIntelligenceProvider:
    name = "callerintel"

    async def status(self) -> dict[str, Any]:
        return {
            "configured": True,
            "searchable": True,
            "executable": True,
            "kind": "caller-intelligence",
            "tool_count": 1,
            "public_search_configured": bool(
                os.getenv("BRAVE_SEARCH_API_KEY", "").strip()
            ),
        }

    async def search(self, query: str, *, limit: int = 10) -> list[ToolDescriptor]:
        descriptor = await self.describe("lookup")
        words = [word for word in query.casefold().split() if word]
        haystack = " ".join(
            [descriptor.tool_id, descriptor.name, descriptor.description, *descriptor.tags]
        ).casefold()
        if words and not any(word in haystack for word in words):
            return []
        return [descriptor][: max(1, min(limit, 10))]

    async def describe(self, tool_id: str) -> ToolDescriptor:
        if tool_id != "lookup":
            raise ValueError(f"unknown callerintel tool: {tool_id}")
        return ToolDescriptor(
            ref="callerintel:lookup",
            provider=self.name,
            tool_id="lookup",
            name="Unknown caller public intelligence",
            description=(
                "Combine telecom metadata with exact-number public-web evidence for an "
                "unknown caller. Returns public evidence leads, not private subscriber records."
            ),
            input_schema={
                "type": "object",
                "required": ["number"],
                "properties": {
                    "number": {"type": "string", "minLength": 3, "maxLength": 64},
                    "region": {"type": "string", "minLength": 2, "maxLength": 2},
                    "public_search": {"type": "boolean"},
                    "max_results": {"type": "integer", "minimum": 1, "maximum": 20},
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
                "unknown-call",
                "osint",
                "public-web",
                "telecom",
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
        del account, wait_seconds, timeout_seconds, options
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
        data = await lookup_caller_intelligence(
            number,
            region=str(arguments.get("region") or "").strip() or None,
            public_search=bool(arguments.get("public_search", True)),
            max_results=int(arguments.get("max_results", 8)),
            telecom_external=bool(arguments.get("telecom_external", False)),
            telecom_providers=providers,
        )
        return {
            "status": "completed",
            "data": data,
            "metadata": {
                "provider": "callerintel",
                "public_only": True,
            },
        }

    async def job_status(self, job_id: str, *, wait_seconds: int = 0) -> dict[str, Any]:
        del job_id, wait_seconds
        raise ValueError("caller intelligence lookups complete synchronously")

    async def result_page(
        self, result_id: str, *, offset: int = 0, limit: int = 100
    ) -> dict[str, Any]:
        del result_id, offset, limit
        raise ValueError("caller intelligence returns bounded inline results")
