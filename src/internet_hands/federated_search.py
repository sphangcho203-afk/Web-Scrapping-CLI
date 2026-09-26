"""Bounded, query-first discovery over documented public indexes.

Source definitions own request construction and normalization. The federation
owns concurrency, partial failure, provenance, and cross-index DOI deduplication.
"""
from __future__ import annotations

import asyncio
import json
import re
from collections.abc import Callable
from dataclasses import dataclass
from html import unescape
from typing import Any
from urllib.parse import quote, urlencode, urlsplit

from .models import FetchResult


@dataclass(frozen=True, slots=True)
class SearchSource:
    id: str
    endpoint: str
    query_field: str
    fixed_params: tuple[tuple[str, str], ...]
    parse: Callable[[dict[str, Any]], list[dict[str, Any]]]

    def url(self, query: str, limit: int) -> str:
        return self.endpoint + "?" + urlencode([*self.fixed_params, (self.query_field, query),
                                                  ("per-page" if self.id == "openalex" else
                                                   "rows" if self.id == "crossref" else "srlimit", str(limit))])


def _text(value: Any, limit: int = 400) -> str:
    if isinstance(value, list):
        value = value[0] if value else ""
    return " ".join(unescape(re.sub(r"<[^>]*>", " ", str(value or ""))).split())[:limit]


def _wikipedia(data: dict[str, Any]) -> list[dict[str, Any]]:
    rows = data.get("query", {}).get("search", [])
    return [{"title": _text(row.get("title")), "url": "https://en.wikipedia.org/wiki/" +
             quote(str(row["title"]).replace(" ", "_")), "snippet": _text(row.get("snippet"), 800),
             "published_at": row.get("timestamp"), "canonical_id": "wikipedia:" + str(row["pageid"])}
            for row in rows if isinstance(row, dict) and row.get("title") and row.get("pageid")]


def _doi(value: Any) -> str | None:
    if not isinstance(value, str):
        return None
    value = re.sub(r"^https?://(?:dx\.)?doi\.org/", "", value.strip(), flags=re.IGNORECASE).lower()
    return value if re.fullmatch(r"10\.\d{4,9}/\S{1,200}", value) else None


def _openalex(data: dict[str, Any]) -> list[dict[str, Any]]:
    rows = data.get("results", [])
    result = []
    for row in rows:
        if not isinstance(row, dict) or not row.get("title"):
            continue
        doi = _doi(row.get("doi"))
        location = row.get("primary_location") or {}
        source = (location.get("source") or {}) if isinstance(location, dict) else {}
        result.append({"title": _text(row["title"]), "url": "https://doi.org/" + quote(doi, safe="/") if doi else row.get("id"),
                       "snippet": _text(source.get("display_name") if isinstance(source, dict) else ""),
                       "published_at": row.get("publication_date"), "canonical_id": "doi:" + doi if doi else row.get("id")})
    return result


def _crossref(data: dict[str, Any]) -> list[dict[str, Any]]:
    rows = data.get("message", {}).get("items", [])
    result = []
    for row in rows:
        if not isinstance(row, dict) or not row.get("title"):
            continue
        doi = _doi(row.get("DOI"))
        if not doi:
            continue
        result.append({"title": _text(row["title"]), "url": "https://doi.org/" + quote(doi, safe="/"),
                       "snippet": _text(row.get("publisher")), "published_at": None,
                       "canonical_id": "doi:" + doi})
    return result


SOURCES = {
    source.id: source for source in (
        SearchSource("wikipedia", "https://en.wikipedia.org/w/api.php", "srsearch",
                     (("action", "query"), ("list", "search"), ("format", "json"), ("formatversion", "2")), _wikipedia),
        SearchSource("openalex", "https://api.openalex.org/works", "search",
                     (("select", "id,title,doi,publication_date,primary_location"),), _openalex),
        SearchSource("crossref", "https://api.crossref.org/works", "query.bibliographic",
                     (("select", "DOI,title,publisher"),), _crossref),
    )
}


def validate_search(arguments: dict[str, Any]) -> tuple[str, tuple[str, ...], int]:
    if set(arguments) - {"query", "sources", "limit"}:
        raise ValueError("Unexpected public search arguments")
    query = arguments.get("query")
    if not isinstance(query, str) or not 2 <= len(query.strip()) <= 200:
        raise ValueError("query must contain 2 to 200 characters")
    sources = arguments.get("sources", list(SOURCES))
    if not isinstance(sources, list) or not sources or len(sources) > len(SOURCES) or len(set(map(str, sources))) != len(sources) or any(not isinstance(source, str) or source not in SOURCES for source in sources):
        raise ValueError("sources must be distinct registered public indexes")
    limit = arguments.get("limit", 5)
    if isinstance(limit, bool) or not isinstance(limit, int) or not 1 <= limit <= 10:
        raise ValueError("limit must be an integer between 1 and 10 per index")
    return query.strip(), tuple(sources), limit


async def federated_search(arguments: dict[str, Any], *, fetch: Callable[..., Any], timeout: int = 25) -> dict[str, Any]:
    query, source_ids, limit = validate_search(arguments)

    async def one(source_id: str) -> tuple[str, list[dict[str, Any]], str | None]:
        source = SOURCES[source_id]
        url = source.url(query, limit)
        # A published search endpoint is fixed; redirects cannot broaden scope.
        host = urlsplit(source.endpoint).hostname
        guard = lambda target: urlsplit(target).scheme == "https" and urlsplit(target).hostname == host
        try:
            async with asyncio.timeout(max(1, min(timeout, 12))):
                response: FetchResult = await fetch(url, url_guard=guard)
            if not 200 <= response.status_code < 300:
                raise RuntimeError(f"HTTP {response.status_code}")
            data = json.loads(response.body_text or "")
            if not isinstance(data, dict):
                raise TypeError("Expected a JSON object")
            rows = source.parse(data)
            return source_id, [{**row, "source": source_id, "retrieved_at": response.captured_at.isoformat(),
                                "source_endpoint": source.endpoint} for row in rows[:limit]], None
        except Exception as exc:  # noqa: BLE001 - isolate independent source failures
            return source_id, [], f"{type(exc).__name__}: {str(exc)[:200]}"

    batches = await asyncio.gather(*(one(source_id) for source_id in source_ids))
    combined: dict[str, dict[str, Any]] = {}
    errors = []
    for source_id, rows, error in batches:
        if error:
            errors.append({"source": source_id, "message": error})
        for row in rows:
            url = row.get("url")
            if not isinstance(url, str) or urlsplit(url).scheme != "https" or not urlsplit(url).hostname or urlsplit(url).username or urlsplit(url).password:
                continue
            key = str(row.get("canonical_id") or url).casefold()
            if key in combined:
                combined[key]["sources"].append(source_id)
                combined[key]["evidence"].append({"source": source_id, "source_endpoint": row["source_endpoint"],
                                                   "retrieved_at": row["retrieved_at"]})
            else:
                combined[key] = {**row, "sources": [source_id], "evidence": [
                    {"source": source_id, "source_endpoint": row["source_endpoint"], "retrieved_at": row["retrieved_at"]}]}
    terms = set(re.findall(r"\w+", query.casefold()))
    ranked = sorted(combined.values(), key=lambda row: (-len(row["sources"]),
                    -len(terms.intersection(re.findall(r"\w+", row["title"].casefold()))), row["title"].casefold()))
    return {"query": query, "results": ranked[:20], "sources_attempted": list(source_ids),
            "errors": errors, "partial": bool(errors), "result_count": len(ranked),
            "ranking": "cross-index corroboration, then title term overlap"}
