from __future__ import annotations

import asyncio
import os
import re
from typing import Any
from urllib.parse import urlsplit

from .execution_meter import record_provider_call, record_usage
from .fetcher import fetch_url
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
                record_usage("public_search_call")
                record_provider_call("brave")
                record = await brave_search(
                    f'"{e164}"',
                    kind=SearchKind.WEB,
                    count=limit,
                )
                evidence = _result_rows(record, limit)
                record_usage("public_search_result", len(evidence))
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


def _phone_digit_pattern(e164: str, national_number: str | None) -> re.Pattern[str]:
    candidates = []
    for raw in (e164, national_number or ""):
        digits = "".join(ch for ch in str(raw) if ch.isdigit())
        if len(digits) >= 7:
            candidates.append(digits)
    if not candidates:
        raise ValueError("normalized phone number is too short to corroborate")
    variants = []
    for digits in sorted(set(candidates), key=len, reverse=True):
        pieces = [re.escape(ch) for ch in digits]
        variants.append(r"(?:\D{0,3})".join(pieces))
    return re.compile(r"(?<!\d)(?:" + "|".join(variants) + r")(?!\d)")


def _confidence_for_confirmed_pages(rows: list[dict[str, Any]]) -> dict[str, Any]:
    confirmed = [row for row in rows if row.get("number_confirmed")]
    domains = {str(row.get("host") or "") for row in confirmed if row.get("host")}
    professional = sum(
        1 for row in confirmed if row.get("source_kind") == "professional_platform"
    )
    directory = sum(
        1 for row in confirmed if row.get("source_kind") == "directory_or_listing"
    )

    if len(domains) >= 3 or (len(domains) >= 2 and professional):
        level = "high"
        status = "corroborated_public_association"
    elif len(domains) >= 2:
        level = "medium"
        status = "multi_source_public_association"
    elif len(domains) == 1:
        level = "low"
        status = "single_source_public_association"
    else:
        level = "none"
        status = "insufficient_public_evidence"

    return {
        "status": status,
        "confidence": level,
        "confirmed_pages": len(confirmed),
        "independent_confirmed_domains": len(domains),
        "professional_sources": professional,
        "directory_sources": directory,
        "note": (
            "Confidence reflects corroborated public-page association only. "
            "It does not prove telecom subscriber ownership."
        ),
    }


async def investigate_caller_public_association(
    number: str,
    *,
    region: str | None = None,
    max_search_results: int = 10,
    max_pages: int = 4,
    concurrency: int = 3,
    telecom_external: bool = False,
    telecom_providers: list[str] | None = None,
) -> dict[str, Any]:
    discovery = await lookup_caller_intelligence(
        number,
        region=region,
        public_search=True,
        max_results=max_search_results,
        telecom_external=telecom_external,
        telecom_providers=telecom_providers,
    )
    telecom = discovery.get("number") or {}
    attribution = discovery.get("public_attribution") or {}
    leads = attribution.get("evidence") or []
    if not isinstance(leads, list):
        leads = []

    e164 = str((telecom.get("formats") or {}).get("e164") or number)
    national = str((telecom.get("number") or {}).get("national_number") or "")
    pattern = _phone_digit_pattern(e164, national)

    page_limit = max(1, min(int(max_pages), 12))
    unique: list[dict[str, Any]] = []
    seen_hosts: set[str] = set()
    for lead in leads:
        if not isinstance(lead, dict):
            continue
        host = str(lead.get("host") or "")
        url = str(lead.get("url") or "")
        if not host or not url or host in seen_hosts:
            continue
        seen_hosts.add(host)
        unique.append(lead)
        if len(unique) >= page_limit:
            break

    semaphore = asyncio.Semaphore(max(1, min(int(concurrency), 5)))

    async def inspect(lead: dict[str, Any]) -> dict[str, Any]:
        async with semaphore:
            url = str(lead["url"])
            record_usage("public_page_fetch")
            record_provider_call("nativeweb")
            try:
                fetched = await fetch_url(
                    url,
                    timeout=20.0,
                    max_bytes=750_000,
                    include_body=True,
                )
                body = fetched.body_text or ""
                confirmed = bool(pattern.search(body))
                if confirmed:
                    record_usage("public_page_confirmed")
                return {
                    "rank": lead.get("rank"),
                    "title": lead.get("title"),
                    "url": fetched.final_url,
                    "host": _host(fetched.final_url),
                    "source_kind": lead.get("source_kind"),
                    "http_status": fetched.status_code,
                    "content_type": fetched.content_type,
                    "number_confirmed": confirmed,
                    "content_sha256": fetched.sha256,
                    "captured_at": fetched.captured_at.isoformat(),
                }
            except Exception as exc:  # noqa: BLE001 - isolated public page fetch
                return {
                    "rank": lead.get("rank"),
                    "title": lead.get("title"),
                    "url": url,
                    "host": lead.get("host"),
                    "source_kind": lead.get("source_kind"),
                    "number_confirmed": False,
                    "fetch_error": f"{type(exc).__name__}: {exc}"[:300],
                }

    pages = await asyncio.gather(*(inspect(lead) for lead in unique))
    correlation = _confidence_for_confirmed_pages(pages)
    public_labels = sorted(
        {
            str(row.get("title") or "").strip()
            for row in pages
            if row.get("number_confirmed") and row.get("title")
        }
    )[:12]

    return {
        "number": telecom,
        "discovery": {
            "search_status": attribution.get("status"),
            "searched_results": len(leads),
            "selected_pages": len(unique),
        },
        "corroboration": correlation,
        "public_labels": public_labels,
        "pages": pages,
        "policy": {
            "private_subscriber_identity": False,
            "private_address": False,
            "secrets": False,
            "public_professional_or_business_evidence": True,
            "raw_page_body_returned": False,
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
            "tool_count": 2,
            "public_search_configured": bool(
                os.getenv("BRAVE_SEARCH_API_KEY", "").strip()
            ),
        }

    async def search(self, query: str, *, limit: int = 10) -> list[ToolDescriptor]:
        words = [word for word in query.casefold().split() if word]
        rows: list[tuple[int, ToolDescriptor]] = []
        for tool_id in ("lookup", "investigate"):
            descriptor = await self.describe(tool_id)
            haystack = " ".join(
                [descriptor.tool_id, descriptor.name, descriptor.description, *descriptor.tags]
            ).casefold()
            score = sum(1 for word in words if word in haystack)
            if score or not words:
                rows.append((score, descriptor))
        rows.sort(key=lambda row: (-row[0], row[1].tool_id))
        return [descriptor for _, descriptor in rows[: max(1, min(limit, 10))]]

    async def describe(self, tool_id: str) -> ToolDescriptor:
        common = {
            "number": {"type": "string", "minLength": 3, "maxLength": 64},
            "region": {"type": "string", "minLength": 2, "maxLength": 2},
            "telecom_external": {"type": "boolean"},
            "telecom_providers": {
                "type": "array",
                "items": {
                    "type": "string",
                    "enum": ["veriphone", "abstract", "numverify", "twilio"],
                },
                "maxItems": 4,
            },
        }
        if tool_id == "lookup":
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
                        **common,
                        "public_search": {"type": "boolean"},
                        "max_results": {"type": "integer", "minimum": 1, "maximum": 20},
                    },
                    "additionalProperties": False,
                },
                output_schema={},
                tags=["phone", "caller", "unknown-call", "osint", "public-web", "telecom"],
                requires_auth=False,
                side_effecting=False,
                metadata={
                    "configured": True,
                    "public_only": True,
                    "private_subscriber_identity": False,
                },
            )
        if tool_id == "investigate":
            return ToolDescriptor(
                ref="callerintel:investigate",
                provider=self.name,
                tool_id="investigate",
                name="Unknown caller corroboration",
                description=(
                    "Search and fetch a bounded set of public pages, verify that the number "
                    "actually appears on them, and score independent public corroboration."
                ),
                input_schema={
                    "type": "object",
                    "required": ["number"],
                    "properties": {
                        **common,
                        "max_search_results": {
                            "type": "integer",
                            "minimum": 1,
                            "maximum": 20,
                        },
                        "max_pages": {"type": "integer", "minimum": 1, "maximum": 12},
                        "concurrency": {"type": "integer", "minimum": 1, "maximum": 5},
                    },
                    "additionalProperties": False,
                },
                output_schema={},
                tags=[
                    "phone",
                    "caller",
                    "investigate",
                    "corroborate",
                    "public-web",
                    "osint",
                ],
                requires_auth=False,
                side_effecting=False,
                metadata={
                    "configured": True,
                    "public_only": True,
                    "private_subscriber_identity": False,
                    "raw_page_body_returned": False,
                },
            )
        raise ValueError(f"unknown callerintel tool: {tool_id}")

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
        if tool_id == "lookup":
            data = await lookup_caller_intelligence(
                number,
                region=str(arguments.get("region") or "").strip() or None,
                public_search=bool(arguments.get("public_search", True)),
                max_results=int(arguments.get("max_results", 8)),
                telecom_external=bool(arguments.get("telecom_external", False)),
                telecom_providers=providers,
            )
        else:
            data = await investigate_caller_public_association(
                number,
                region=str(arguments.get("region") or "").strip() or None,
                max_search_results=int(arguments.get("max_search_results", 10)),
                max_pages=int(arguments.get("max_pages", 4)),
                concurrency=int(arguments.get("concurrency", 3)),
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
