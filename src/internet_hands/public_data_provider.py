"""Structured public documents and source-grounded, bounded research.

Uses the existing SSRF-safe fetcher and optional main-text extractor. Discovery
consumes published links only; it does not infer private endpoints or credentials.
"""
from __future__ import annotations

import asyncio
import csv
import io
import json
import re
import time
import xml.etree.ElementTree as ET
from collections import deque
from html.parser import HTMLParser
from typing import Any
from urllib.parse import urldefrag, urljoin, urlsplit
from urllib.robotparser import RobotFileParser

from .capability_packs import Capability, CapabilityCandidate
from .discovery import discover_from_html, discover_frontier_urls
from .execution_meter import record_usage
from .extractor import extract_document
from .federated_search import federated_search, validate_search
from .fetcher import DEFAULT_UA, extract_links, fetch_url
from .models import FetchResult
from .tool_mesh import ToolDescriptor


class _Tables(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.tables: list[list[list[str]]] = []
        self.table = None
        self.row = None
        self.cell = None

    def handle_starttag(self, tag, attrs):
        if tag == "table" and self.table is None and len(self.tables) < 10:
            self.table = []
        elif tag == "tr" and self.table is not None:
            self.row = []
        elif tag in {"td", "th"} and self.row is not None:
            self.cell = ""

    def handle_data(self, data):
        if self.cell is not None:
            self.cell = (self.cell + data)[:1000]

    def handle_endtag(self, tag):
        if tag in {"td", "th"} and self.cell is not None:
            if self.row is not None and len(self.row) < 30:
                self.row.append(" ".join(self.cell.split()))
            self.cell = None
        elif tag == "tr" and self.row is not None:
            if self.table is not None and len(self.table) < 100:
                self.table.append(self.row)
            self.row = None
        elif tag == "table" and self.table is not None:
            self.tables.append(self.table)
            self.table = self.row = self.cell = None


def public_link(base: str, link: str) -> str | None:
    try:
        if len(link) > 4096:
            return None
        url = urldefrag(urljoin(base, link.strip()))[0]
        parts = urlsplit(url)
        if parts.scheme in {"https", "http"} and parts.hostname and not parts.username and not parts.password:
            return url
    except ValueError:
        pass
    return None


def structured_document(result: FetchResult) -> dict[str, Any]:
    if not 200 <= result.status_code < 300:
        raise RuntimeError(f"Public source returned HTTP {result.status_code}")
    body = result.body_text
    if body is None:
        raise ValueError("This source is not a supported text document")
    mime = (result.content_type or "").split(";", 1)[0].lower()
    output: dict[str, Any] = {
        "source_url": result.final_url, "requested_url": result.request_url,
        "captured_at": result.captured_at.isoformat(), "sha256": result.sha256,
        "content_type": mime, "links": [], "text": "", "title": None,
    }
    if "json" in mime or body.lstrip().startswith(("{", "[")):
        data = json.loads(body)
        output.update(format="json", data=data, text=json.dumps(data, ensure_ascii=False)[:20000])
        output["links"] = discover_frontier_urls(body, result.final_url, content_type="application/json", limit=200)
    elif "csv" in mime or "tab-separated" in mime:
        reader = csv.reader(io.StringIO(body), delimiter="\t" if "tab-separated" in mime else ",")
        rows = []
        for row in reader:
            rows.append([cell[:1000] for cell in row[:30]])
            if len(rows) > 100:
                break
        output.update(format="table", rows=rows[:100], truncated=len(rows) > 100,
                      text="\n".join(" | ".join(row) for row in rows[:100])[:20000])
    elif "html" not in mime and ("xml" in mime or body.lstrip().startswith("<?xml")):
        # Reject entity/DTD declarations before parsing; never resolve external entities.
        if re.search(r"<!\s*(?:DOCTYPE|ENTITY)\b", body, re.IGNORECASE):
            raise ValueError("XML DTDs and entities are not supported")
        root = ET.fromstring(body)
        local = lambda tag: tag.rsplit("}", 1)[-1]
        kind = local(root.tag)
        items = []
        for element in root.iter():
            if local(element.tag) not in {"item", "entry", "url", "sitemap"}:
                continue
            item = {}
            for child in element:
                key = local(child.tag)
                if key in {"title", "link", "loc", "description", "summary", "published", "updated", "pubDate", "lastmod", "guid", "id"}:
                    item[key] = (child.attrib.get("href") or "".join(child.itertext()).strip())[:2000]
            items.append(item)
            if len(items) >= 200:
                break
        output.update(format="sitemap" if kind in {"urlset", "sitemapindex"} else "feed" if kind in {"rss", "feed", "RDF"} else "xml",
                      items=items, text="\n".join(" | ".join(item.values()) for item in items)[:20000])
        output["links"] = discover_frontier_urls(body, result.final_url, content_type="application/xml", limit=200)
    elif "html" in mime or re.search(r"<(?:html|body|head|!doctype html)\b", body[:1000], re.IGNORECASE):
        doc = extract_document(result)
        interfaces = discover_from_html(body, result.final_url)
        tables = _Tables()
        tables.feed(body)
        output.update(format="html", title=doc.title, description=doc.description,
                      text=doc.text[:20000], text_truncated=len(doc.text) > 20000,
                      headings=doc.headings[:100], tables=tables.tables,
                      json_ld=interfaces["json_ld"][:50], interfaces=interfaces["candidates"][:100],
                      links=extract_links(result).links[:200])
    else:
        output.update(format="text", text=body[:20000], text_truncated=len(body) > 20000)
    output["links"] = list(dict.fromkeys(link for raw in output["links"] if (link := public_link(result.final_url, raw))))
    return output


def request_budget(operation: str, arguments: dict[str, Any]) -> int:
    if operation == "search":
        return len(validate_search(arguments)[1])
    if operation not in {"extract", "discover", "research"}:
        raise ValueError("Unknown public data operation")
    allowed = {"url"} if operation != "research" else {"urls", "query", "max_pages"}
    if set(arguments) - allowed:
        raise ValueError("Unexpected public data arguments")
    if operation != "research":
        if not isinstance(arguments.get("url"), str) or not public_link("", arguments["url"]):
            raise ValueError("url must be a public HTTP(S) URL")
        return 1
    urls = arguments.get("urls")
    pages = arguments.get("max_pages", 5)
    if isinstance(pages, bool) or not isinstance(pages, int) or not 1 <= pages <= 20:
        raise ValueError("max_pages must be an integer between 1 and 20")
    if not isinstance(urls, list) or not 1 <= len(urls) <= min(pages, 10):
        raise ValueError("urls must contain 1 to 10 seed URLs within the page budget")
    if any(not isinstance(url, str) or not public_link("", url) for url in urls):
        raise ValueError("Each seed must be an HTTP(S) URL without credentials")
    query = arguments.get("query", "")
    if not isinstance(query, str) or len(query) > 500:
        raise ValueError("query must be text of at most 500 characters")
    return pages * 2  # At most one robots request per attempted page origin.


async def _fetch(url: str, *, url_guard=None) -> FetchResult:
    record_usage("public_data_requests")
    return await fetch_url(url, timeout=10, max_bytes=1_000_000, max_redirects=3, url_guard=url_guard)


async def research(arguments: dict[str, Any], *, timeout: float) -> dict[str, Any]:
    request_budget("research", arguments)
    seeds = list(dict.fromkeys(public_link("", url) for url in arguments["urls"]))
    origin = lambda url: (urlsplit(url).scheme, urlsplit(url).netloc.lower())
    origins = {origin(url) for url in seeds}
    pending = deque(seeds)
    seen = set()
    policies: dict[tuple[str, str], RobotFileParser | None] = {}
    evidence, errors = [], []
    terms = set(re.findall(r"\w+", arguments.get("query", "").casefold()))
    max_pages = arguments.get("max_pages", 5)
    reason = "frontier_exhausted"
    try:
        async with asyncio.timeout(max(0.01, min(timeout, 45))):
            while pending and len(seen) < max_pages:
                url = pending.popleft()
                if url in seen:
                    continue
                seen.add(url)
                try:
                    site = origin(url)
                    if site not in policies:
                        robots_url = f"{site[0]}://{site[1]}/robots.txt"
                        robots = await _fetch(robots_url, url_guard=lambda target, site=site: origin(target) == site)
                        policy = RobotFileParser(robots_url)
                        if robots.status_code in {404, 410}:
                            policy.parse([])
                        elif robots.status_code in {401, 403}:
                            policy.parse(["User-agent: *", "Disallow: /"])
                        elif 200 <= robots.status_code < 300 and robots.body_text is not None:
                            policy.parse(robots.body_text.splitlines())
                        else:
                            raise RuntimeError("Could not establish the site's crawl policy")
                        policies[site] = policy
                    policy = policies[site]
                    if policy is None or not policy.can_fetch(DEFAULT_UA, url):
                        errors.append({"url": url, "code": "robots_disallowed"})
                        continue
                    delay = max(0.25, policy.crawl_delay(DEFAULT_UA) or 0)
                    rate = policy.request_rate(DEFAULT_UA)
                    if rate:
                        delay = max(delay, rate.seconds / rate.requests)
                    if delay:
                        await asyncio.sleep(min(delay, 46))
                    result = await _fetch(url, url_guard=lambda target, site=site, policy=policy: origin(target) == site and policy.can_fetch(DEFAULT_UA, target))
                    doc = structured_document(result)
                    links = doc["links"]
                    doc.pop("data", None)  # Research returns bounded evidence, not full datasets.
                    doc.pop("tables", None)
                    doc.pop("json_ld", None)
                    doc.pop("items", None)
                    text = doc["text"]
                    paragraphs = re.split(r"\n+|(?<=[.!?])\s+", text)
                    ranked = sorted(enumerate(paragraphs), key=lambda p: (-sum(term in p[1].casefold() for term in terms), p[0]))
                    snippets = [p[:1200] for _, p in ranked[:5] if p.strip()]
                    doc.update(text=text[:8000], text_truncated=doc.get("text_truncated", False) or len(text) > 8000, snippets=snippets,
                               matched_terms=sorted(term for term in terms if term in text.casefold()), links=links[:40])
                    evidence.append(doc)
                    # Seed origins are the scope boundary. Redirect targets do not expand it.
                    if origin(result.final_url) in origins:
                        discovered = [*links, *(item["url"] for item in doc.get("interfaces", []))]
                        for link in discovered:
                            link = public_link(result.final_url, link)
                            if link and origin(link) in origins and link not in seen and link not in pending and len(pending) < 200:
                                pending.append(link)
                except Exception as exc:  # noqa: BLE001 - isolate public-source failures
                    policies.setdefault(origin(url), None)
                    errors.append({"url": url, "code": type(exc).__name__, "message": str(exc)[:300]})
            if pending:
                reason = "page_budget"
    except TimeoutError:
        reason = "time_budget"
    return {"query": arguments.get("query", ""), "scope": "seed_origins", "evidence": evidence,
            "errors": errors, "pages_attempted": len(seen), "pages_collected": len(evidence),
            "stop_reason": reason, "partial": bool(errors) or reason != "frontier_exhausted",
            "synthesis": "Extracted source evidence; no unsupported answer synthesis."}


class PublicDataProvider:
    name = "publicdata"

    async def status(self):
        return {"configured": True, "searchable": True, "executable": True, "network": "public-http-only"}

    async def describe(self, tool_id: str) -> ToolDescriptor:
        descriptions = {
            "search": "Search independent public indexes and return normalized, deduplicated results with source evidence.",
            "extract": "Extract public HTML, tables, JSON-LD, JSON, CSV, RSS, Atom and sitemaps with source evidence.",
            "discover": "Inspect a public document for published links, feeds, sitemaps and machine-readable interfaces.",
            "research": "Collect ranked evidence from supplied public URLs and same-origin links with robots, page and time bounds. No search API key required.",
        }
        if tool_id not in descriptions:
            raise ValueError("Unknown public data operation")
        properties = {"url": {"type": "string"}}
        if tool_id == "search":
            properties = {"query": {"type": "string", "minLength": 2, "maxLength": 200},
                          "sources": {"type": "array", "items": {"type": "string", "enum": ["wikipedia", "openalex", "crossref"]}, "uniqueItems": True, "minItems": 1, "maxItems": 3},
                          "limit": {"type": "integer", "minimum": 1, "maximum": 10, "default": 5}}
        if tool_id == "research":
            properties = {"urls": {"type": "array", "items": {"type": "string"}, "minItems": 1, "maxItems": 10},
                          "query": {"type": "string", "maxLength": 500},
                          "max_pages": {"type": "integer", "minimum": 1, "maximum": 20, "default": 5}}
        return ToolDescriptor(ref=f"publicdata:{tool_id}", provider=self.name, tool_id=tool_id,
                              name=f"Public data {tool_id}", description=descriptions[tool_id],
                              input_schema={"type": "object", "properties": properties,
                                            "required": ["query" if tool_id == "search" else "urls" if tool_id == "research" else "url"], "additionalProperties": False},
                              tags=["web", "public", "data", tool_id], side_effecting=False,
                              requires_auth=False, metadata={"method": "GET"})

    async def search(self, query: str, *, limit=10):
        descriptors = [await self.describe(op) for op in ("extract", "discover", "research", "search")]
        words = query.casefold().split()
        return [item for item in descriptors if not words or any(word in f"{item.name} {item.description}".casefold() for word in words)][:limit]

    async def execute(self, tool_id, arguments, *, account=None, wait_seconds=30, timeout_seconds=60, options=None):
        request_budget(tool_id, arguments)
        started = time.monotonic()
        if tool_id == "search":
            data = await federated_search(arguments, fetch=_fetch, timeout=timeout_seconds)
            if len(data["errors"]) == len(data["sources_attempted"]):
                return {"status": "failed", "data": data, "error": "All public indexes are unavailable; inspect source errors."}
        elif tool_id == "research":
            data = await research(arguments, timeout=timeout_seconds)
            if not data["evidence"]:
                return {"status": "failed", "data": data, "error": "No public source could be collected; inspect source errors."}
        else:
            async with asyncio.timeout(max(1, min(timeout_seconds, 30))):
                data = structured_document(await _fetch(arguments["url"]))
            if tool_id == "discover":
                data = {key: value for key, value in data.items() if key in {"source_url", "captured_at", "sha256", "format", "links", "interfaces", "title"}}
        return {"status": "completed", "data": {**data, "elapsed_ms": int((time.monotonic() - started) * 1000)}}

    async def job_status(self, job_id, *, wait_seconds=0):
        raise ValueError("Public data operations complete inline")

    async def result_page(self, result_id, *, offset=0, limit=100):
        raise ValueError("Public data operations return bounded inline results")


def build_public_data_capabilities() -> list[Capability]:
    return ([Capability(id=f"web.public.{op}", name=f"Public data {op}",
                       description=description, pack="public-data", tags=("web", "public", "data", op),
                       candidates=(CapabilityCandidate(provider="publicdata", ref=f"publicdata:{op}", priority=10,
                                                       passthrough_arguments=True),),
                       input_schema={"type": "object", "required": ["urls" if op == "research" else "url"],
                                     "properties": {"urls": {"type": "array", "items": {"type": "string"}, "minItems": 1, "maxItems": 10},
                                                    "query": {"type": "string", "maxLength": 500},
                                                    "max_pages": {"type": "integer", "minimum": 1, "maximum": 20, "default": 5}}
                                     if op == "research" else {"url": {"type": "string"}}, "additionalProperties": False})
            for op, description in (("extract", "Extract structured public documents with provenance."),
                                    ("discover", "Discover published data interfaces, feeds and links."),
                                    ("research", "Research supplied URLs and same-origin links without a search API key."))]
            + [Capability(id="web.public.search", name="Federated public search",
                          description="Search public knowledge and scholarly indexes with source evidence.",
                          pack="public-data", tags=("web", "public", "search", "research"),
                          candidates=(CapabilityCandidate(provider="publicdata", ref="publicdata:search", priority=10),),
                          input_schema={"type": "object", "required": ["query"], "properties": {
                              "query": {"type": "string", "minLength": 2, "maxLength": 200},
                              "sources": {"type": "array", "items": {"type": "string", "enum": ["wikipedia", "openalex", "crossref"]}, "minItems": 1, "maxItems": 3, "uniqueItems": True},
                              "limit": {"type": "integer", "minimum": 1, "maximum": 10, "default": 5}},
                              "additionalProperties": False},
                          output_schema={"type": "object", "required": ["query", "results", "sources_attempted", "errors", "partial"],
                                         "properties": {"results": {"type": "array", "items": {"type": "object", "required": ["title", "url", "sources", "evidence"]}},
                                                        "sources_attempted": {"type": "array", "items": {"type": "string"}},
                                                        "partial": {"type": "boolean"}, "errors": {"type": "array"}}})])
