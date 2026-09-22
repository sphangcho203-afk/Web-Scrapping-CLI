from __future__ import annotations

import asyncio
import json
import math
import re
import time
import uuid
from urllib.parse import urlsplit, urlunsplit
from typing import Any

from fastapi import APIRouter, HTTPException, Request

from .auth import authenticate_secret
from .control_api import _require_user
from .control_store import AuthIdentity, ControlError, ControlStore
from .crawler import crawl
from .extractor import extract_document
from .fetcher import fetch_url
from .firecrawl_provider import FirecrawlToolProvider
from .policy import PolicyError, ResolutionUnavailable, validate_public_http_url
from .web_search import SearchKind, brave_search

router = APIRouter()
store = ControlStore()

_SAFE_EXCLUDES = (
    "*/logout*",
    "*/signout*",
    "*/sign-out*",
    "*/delete*",
    "*/unsubscribe*",
    "*/checkout*",
)


def _http_error(exc: ControlError) -> HTTPException:
    return HTTPException(status_code=exc.status_code, detail={"code": exc.code, "message": exc.detail})


def _require_execute_scope(identity: AuthIdentity) -> AuthIdentity:
    scopes = set(identity.scopes or [])
    if "*" not in scopes and "mcp:execute" not in scopes:
        raise HTTPException(
            status_code=403,
            detail={"code": "scope_required", "message": "This API key needs the mcp:execute scope."},
        )
    return identity


def _request_credential(request: Request) -> str:
    supplied = str(request.headers.get("x-api-key") or "").strip()
    authorization = str(request.headers.get("authorization") or "").strip()
    if authorization.lower().startswith("bearer "):
        supplied = authorization[7:].strip()
    return supplied


def _playground_identity(request: Request, body: dict[str, Any]) -> AuthIdentity:
    supplied = _request_credential(request)
    if supplied:
        try:
            identity = authenticate_secret(store, supplied)
        except ControlError as exc:
            raise _http_error(exc) from exc
        if not identity:
            raise HTTPException(
                status_code=401,
                detail={"code": "invalid_api_key", "message": "A valid Internet Hands API key or access token is required."},
                headers={"WWW-Authenticate": "Bearer"},
            )
        selected_key_id = str(body.get("api_key_id") or "").strip()
        if selected_key_id and identity.api_key_id and selected_key_id != identity.api_key_id:
            raise HTTPException(
                status_code=403,
                detail={"code": "credential_mismatch", "message": "The selected API key does not match the supplied credential."},
            )
        return _require_execute_scope(identity)

    user = _require_user(request)
    key_id = str(body.get("api_key_id") or "").strip()
    if not key_id:
        raise HTTPException(
            status_code=409,
            detail={"code": "api_key_required", "message": "Create an API key in the API Keys section before using Playground."},
        )
    try:
        identity = store.api_key_identity_for_user(user["id"], key_id)
    except ControlError as exc:
        raise _http_error(exc) from exc
    if not identity:
        raise HTTPException(
            status_code=409,
            detail={"code": "api_key_required", "message": "That API key is unavailable or revoked. Create or select an active key."},
        )
    return _require_execute_scope(identity)


def _bounded_int(value: Any, name: str, default: int, minimum: int, maximum: int) -> int:
    if value in (None, ""):
        return default
    try:
        parsed = int(value)
    except (TypeError, ValueError) as exc:
        raise HTTPException(status_code=400, detail={"code": "invalid_input", "message": f"{name} must be an integer"}) from exc
    if parsed < minimum or parsed > maximum:
        raise HTTPException(
            status_code=400,
            detail={"code": "invalid_input", "message": f"{name} must be between {minimum} and {maximum}"},
        )
    return parsed


def _patterns(value: Any, name: str) -> list[str]:
    if value is None:
        return []
    if not isinstance(value, list) or not all(isinstance(item, str) for item in value):
        raise HTTPException(status_code=400, detail={"code": "invalid_input", "message": f"{name} must be a string array"})
    cleaned = [item.strip() for item in value if item.strip()]
    if len(cleaned) > 20 or any(len(item) > 200 for item in cleaned):
        raise HTTPException(status_code=400, detail={"code": "invalid_input", "message": f"{name} is too large"})
    return cleaned


def _canonical_source_url(value: str) -> str:
    parts = urlsplit(value.strip())
    path = parts.path or "/"
    if path != "/":
        path = path.rstrip("/")
    return urlunsplit((parts.scheme.lower(), parts.netloc.lower(), path, "", ""))


def _query_terms(query: str) -> set[str]:
    return {term for term in re.findall(r"[a-z0-9]{3,}", query.lower()) if term not in {"the","and","for","with","from","this","that","what","when","where","which","about"}}


def _rank_evidence(query: str, evidence: list[dict[str, Any]]) -> list[dict[str, Any]]:
    terms = _query_terms(query)
    ranked: list[dict[str, Any]] = []
    for index, item in enumerate(evidence):
        haystack = " ".join(str(item.get(k) or "") for k in ("title","description","text")).lower()
        hits = sum(1 for term in terms if term in haystack)
        coverage = hits / max(1, len(terms))
        search_rank = int(item.get("search_rank") or index + 1)
        score = round((coverage * 0.82) + (0.18 / max(1, math.sqrt(search_rank))), 4)
        copy = dict(item)
        copy["relevance_score"] = score
        copy["matched_terms"] = sorted(term for term in terms if term in haystack)[:12]
        ranked.append(copy)
    return sorted(ranked, key=lambda item: (-float(item.get("relevance_score") or 0), int(item.get("search_rank") or 999)))


def _needs_fallback(item: dict[str, Any]) -> bool:
    text = str(item.get("text") or "").strip()
    return bool(item.get("error")) or len(text) < 280


async def _firecrawl_fallback(evidence: list[dict[str, Any]], *, limit: int = 3) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    candidates = [item for item in evidence if _needs_fallback(item)][:max(0, limit)]
    if not candidates:
        return evidence, {"attempted": 0, "recovered": 0, "provider": None}
    provider = FirecrawlToolProvider()
    if not provider.api_key:
        return evidence, {"attempted": 0, "recovered": 0, "provider": "firecrawl", "available": False}
    by_url = {str(item.get("url")): dict(item) for item in evidence}
    recovered = 0
    for item in candidates:
        url = str(item.get("url") or "")
        if not url:
            continue
        try:
            validate_public_http_url(url)
            result = await provider.execute("scrape", {"url": url, "formats": ["markdown"], "onlyMainContent": True, "timeout": 15000}, timeout_seconds=20)
            data = result.get("data") or {}
            markdown = str(data.get("markdown") or data.get("content") or "").strip() if isinstance(data, dict) else ""
            if len(markdown) >= 280:
                replacement = dict(item)
                replacement.update({"text": markdown[:12000], "error": None, "source": "firecrawl", "fallback": True, "discovery_source": item.get("discovery_source")})
                metadata = data.get("metadata") if isinstance(data, dict) else None
                if isinstance(metadata, dict) and metadata.get("title"):
                    replacement["title"] = str(metadata["title"])
                by_url[url] = replacement
                recovered += 1
        except Exception as exc:  # noqa: BLE001 -- fallback is best-effort and source-local
            failed = dict(by_url[url])
            failed["fallback_error"] = f"{type(exc).__name__}: {exc}"
            by_url[url] = failed
    return [by_url[str(item.get("url"))] for item in evidence], {"attempted": len(candidates), "recovered": recovered, "provider": "firecrawl", "available": True}


def _synthesize_evidence(query: str, evidence: list[dict[str, Any]]) -> dict[str, Any]:
    ranked = _rank_evidence(query, evidence)
    findings: list[dict[str, Any]] = []
    terms = _query_terms(query)
    for source_index, item in enumerate(ranked[:6], start=1):
        text = str(item.get("text") or item.get("description") or "").strip()
        if not text:
            continue
        sentences = [s.strip() for s in re.split(r"(?<=[.!?])\s+", text) if len(s.strip()) >= 40]
        sentences.sort(key=lambda s: sum(1 for term in terms if term in s.lower()), reverse=True)
        excerpt = (sentences[0] if sentences else text[:500])[:700]
        findings.append({"text": excerpt, "citation": source_index, "url": item.get("url"), "title": item.get("title") or item.get("url"), "score": item.get("relevance_score")})
    return {"query": query, "method": "extractive", "findings": findings, "sources": [{"citation": i, "url": x.get("url"), "title": x.get("title") or x.get("url"), "score": x.get("relevance_score")} for i,x in enumerate(ranked[:6], start=1)]}


async def _discover_search_sources(query: str, *, count: int, timeout: float) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    try:
        search_payload = await brave_search(query, kind=SearchKind.WEB, count=min(max(count, 1), 20))
        raw_response = search_payload.get("response") or {}
        web_results = ((raw_response.get("web") or {}).get("results") or []) if isinstance(raw_response, dict) else []
        sources = [
            {
                "url": str(item.get("url") or "").strip(),
                "title": str(item.get("title") or ""),
                "description": str(item.get("description") or ""),
                "age": item.get("age"),
                "source": "brave",
            }
            for item in web_results
            if isinstance(item, dict) and str(item.get("url") or "").strip()
        ]
        return sources, {"provider": "brave", "fallback": False}
    except Exception as brave_exc:  # noqa: BLE001 -- Firecrawl is the bounded search fallback
        provider = FirecrawlToolProvider()
        if not provider.api_key:
            raise RuntimeError(
                f"web search unavailable: Brave failed ({type(brave_exc).__name__}) and Firecrawl is not configured"
            ) from brave_exc
        result = await provider.execute(
            "search",
            {
                "query": query,
                "limit": min(max(count, 1), 20),
                "scrapeOptions": {"formats": ["markdown"], "onlyMainContent": True},
            },
            timeout_seconds=max(5, min(int(timeout), 30)),
        )
        data = result.get("data") or {}
        web_results = data.get("web") or [] if isinstance(data, dict) else []
        sources = []
        for item in web_results:
            if not isinstance(item, dict):
                continue
            url = str(item.get("url") or "").strip()
            if not url:
                continue
            sources.append(
                {
                    "url": url,
                    "title": str(item.get("title") or ""),
                    "description": str(item.get("description") or ""),
                    "age": item.get("age"),
                    "source": "firecrawl_search",
                    "prefetched_text": str(item.get("markdown") or "").strip()[:12000],
                }
            )
        return sources, {
            "provider": "firecrawl",
            "fallback": True,
            "fallback_from": "brave",
            "fallback_reason": type(brave_exc).__name__,
            "credits_used": (result.get("metadata") or {}).get("credits_used"),
        }


async def _research_evidence(sources: list[dict[str, Any]], *, limit: int, timeout: float) -> list[dict[str, Any]]:
    semaphore = asyncio.Semaphore(min(4, max(1, limit)))
    async def one(source: dict[str, Any]) -> dict[str, Any]:
        async with semaphore:
            url = source["url"]
            prefetched = str(source.get("prefetched_text") or "").strip()
            if len(prefetched) >= 280:
                return {
                    "url": url,
                    "title": source.get("title") or "",
                    "description": source.get("description") or "",
                    "text": prefetched[:12000],
                    "status_code": 200,
                    "content_type": "text/markdown",
                    "source": "firecrawl_search",
                    "discovery_source": source.get("source") or "firecrawl_search",
                    "search_rank": source.get("rank"),
                }
            try:
                fetched = await fetch_url(url, timeout=timeout, max_bytes=1_000_000)
                document = extract_document(fetched)
                text = str(getattr(document, "text", "") or "").strip()
                return {
                    "url": url, "title": str(getattr(document, "title", "") or source.get("title") or ""),
                    "description": source.get("description") or "", "text": text[:12000],
                    "status_code": fetched.status_code, "content_type": fetched.content_type,
                    "source": "native", "discovery_source": source.get("source") or "web",
                    "search_rank": source.get("rank"),
                }
            except Exception as exc:  # noqa: BLE001 -- evidence failures remain source-local
                return {
                    "url": url, "title": source.get("title") or "", "description": source.get("description") or "",
                    "text": "", "error": f"{type(exc).__name__}: {exc}", "source": "native",
                    "discovery_source": source.get("source") or "web", "search_rank": source.get("rank"),
                }
    return await asyncio.gather(*(one(source) for source in sources[:limit]))


@router.post("/api/playground/run")
async def playground_run(request: Request):
    raw = await request.body()
    try:
        body = json.loads(raw or b"{}")
    except (json.JSONDecodeError, UnicodeDecodeError) as exc:
        raise HTTPException(status_code=400, detail={"code": "invalid_json", "message": "Request body must be valid JSON."}) from exc
    if not isinstance(body, dict):
        raise HTTPException(status_code=400, detail={"code": "invalid_input", "message": "Request body must be a JSON object."})

    identity = _playground_identity(request, body)
    operation = str(body.get("operation") or "crawl").strip().lower()
    if operation not in {"crawl", "search", "research", "auto"}:
        raise HTTPException(status_code=400, detail={"code": "unsupported_operation", "message": "Supported operations: crawl, search, research, auto."})

    query = str(body.get("query") or "").strip()
    url = str(body.get("url") or "").strip()
    if operation == "search" and not query:
        raise HTTPException(status_code=400, detail={"code": "query_required", "message": "Enter a web search query."})
    if operation in {"research", "auto"} and not (query or url):
        raise HTTPException(status_code=400, detail={"code": "query_required", "message": "Enter a research question or starting URL."})
    if operation == "crawl" and not url:
        raise HTTPException(status_code=400, detail={"code": "url_required", "message": "Enter a public HTTP(S) URL to crawl."})
    if url:
        try:
            validate_public_http_url(url)
        except ResolutionUnavailable as exc:
            raise HTTPException(status_code=503, detail={"code": "resolver_busy", "message": str(exc)}, headers={"Retry-After": "1"}) from exc
        except PolicyError as exc:
            raise HTTPException(status_code=400, detail={"code": "target_blocked", "message": str(exc)}) from exc

    max_pages = _bounded_int(body.get("max_pages"), "max_pages", 12, 1, 50)
    max_depth = _bounded_int(body.get("max_depth"), "max_depth", 2, 0, 4)
    concurrency = _bounded_int(body.get("concurrency"), "concurrency", 4, 1, 6)
    max_seconds = _bounded_int(body.get("max_seconds"), "max_seconds", 30, 5, 45)
    include_paths = _patterns(body.get("include_paths"), "include_paths")
    exclude_paths = [*_SAFE_EXCLUDES, *_patterns(body.get("exclude_paths"), "exclude_paths")]
    include_subdomains = bool(body.get("include_subdomains", False))
    preserve_query = bool(body.get("preserve_query", False))

    request_id = f"req_{uuid.uuid4().hex}"
    arguments = {
        "ref": f"playground:{operation}",
        "url": url,
        "query": query,
        "max_pages": max_pages,
        "max_depth": max_depth,
        "concurrency": concurrency,
        "max_seconds": max_seconds,
        "include_subdomains": include_subdomains,
        "preserve_query": preserve_query,
    }
    try:
        credits = store.charge_tool_call(
            identity=identity,
            request_id=request_id,
            tool_name=f"playground:{operation}",
            arguments=arguments,
            input_bytes=len(raw),
        )
    except ControlError as exc:
        raise _http_error(exc) from exc

    started = time.monotonic()
    status = "error"
    output_bytes = 0
    try:
        search_payload: dict[str, Any] | None = None
        search_sources: list[dict[str, Any]] = []
        search_meta: dict[str, Any] = {"provider": None, "fallback": False}
        if operation in {"search", "research", "auto"} and query:
            raw_sources, search_meta = await _discover_search_sources(
                query, count=min(max_pages, 20), timeout=min(float(max_seconds), 30.0)
            )
            for item in raw_sources:
                candidate = str(item.get("url") or "").strip()
                if not candidate:
                    continue
                try:
                    validate_public_http_url(candidate)
                except (PolicyError, ResolutionUnavailable):
                    continue
                search_sources.append(item)
            deduped: list[dict[str, Any]] = []
            seen_sources: set[str] = set()
            for source in search_sources:
                canonical = _canonical_source_url(source["url"])
                if canonical in seen_sources:
                    continue
                seen_sources.add(canonical)
                source["canonical_url"] = canonical
                source["rank"] = len(deduped) + 1
                deduped.append(source)
            search_sources = deduped
            if operation == "search":
                payload = {"pages": [], "search_results": search_sources, "search": search_meta, "evidence": [], "discovered_urls": len(search_sources), "skipped_urls": 0, "duration_ms": 0, "truncated": False}
            elif not url and search_sources:
                url = search_sources[0]["url"]
            elif not url:
                payload = {"pages": [], "search_results": [], "discovered_urls": 0, "skipped_urls": 0, "duration_ms": 0, "truncated": False}

        evidence: list[dict[str, Any]] = []
        if operation in {"research", "auto"} and search_sources:
            evidence_limit = min(8, max(3, max_pages // 3))
            evidence = await _research_evidence(search_sources, limit=evidence_limit, timeout=min(float(max_seconds), 15.0))
            evidence = _rank_evidence(query, evidence)
            evidence, fallback = await _firecrawl_fallback(evidence, limit=min(3, evidence_limit))
            evidence = _rank_evidence(query, evidence)
        else:
            fallback = {"attempted": 0, "recovered": 0, "provider": None}

        synthesis = _synthesize_evidence(query, evidence) if query and evidence else {"query": query, "method": "extractive", "findings": [], "sources": []}

        if operation != "search" and url:
            result = await crawl(
                url,
                max_pages=max_pages,
                max_depth=max_depth,
                concurrency=concurrency,
                max_seconds=float(max_seconds),
                delay_seconds=0.10,
                respect_robots=True,
                include_paths=include_paths,
                exclude_paths=exclude_paths,
                include_subdomains=include_subdomains,
                preserve_query=preserve_query,
                max_bytes_per_page=2_000_000,
            )
            payload = result.model_dump(mode="json")
            payload["search_results"] = search_sources
            payload["search"] = search_meta
            payload["evidence"] = evidence
            payload["synthesis"] = synthesis
            payload["fallback"] = fallback
            payload["seed_url"] = url
        pages = payload.get("pages") or []
        summary = {
            "pages": len(pages),
            "successful": sum(1 for page in pages if page.get("status_code") and not page.get("error")),
            "failed": sum(1 for page in pages if page.get("error")),
            "links_found": sum(int(page.get("links_found") or 0) for page in pages),
            "discovered_urls": int(payload.get("discovered_urls") or 0),
            "skipped_urls": int(payload.get("skipped_urls") or 0),
            "duration_ms": int(payload.get("duration_ms") or 0),
            "truncated": bool(payload.get("truncated")),
            "search_results": len(payload.get("search_results") or []),
            "search_provider": (payload.get("search") or {}).get("provider"),
            "evidence_sources": len(payload.get("evidence") or []),
            "evidence_successful": sum(1 for item in (payload.get("evidence") or []) if item.get("text") and not item.get("error")),
            "fallback_attempted": int((payload.get("fallback") or {}).get("attempted") or 0),
            "fallback_recovered": int((payload.get("fallback") or {}).get("recovered") or 0),
            "seed_url": payload.get("seed_url") or url or None,
        }
        response = {
            "ok": True,
            "request_id": request_id,
            "operation": operation,
            "usage": {"credits_charged": credits, "metered": True},
            "summary": summary,
            "result": payload,
        }
        output_bytes = len(json.dumps(response, default=str, separators=(",", ":")).encode())
        status = "ok"
        return response
    except ResolutionUnavailable as exc:
        raise HTTPException(
            status_code=503,
            detail={"code": "resolver_busy", "message": str(exc), "request_id": request_id, "credits_charged": credits},
            headers={"Retry-After": "1"},
        ) from exc
    except (ValueError, PolicyError) as exc:
        raise HTTPException(
            status_code=400,
            detail={"code": "crawl_rejected", "message": str(exc), "request_id": request_id, "credits_charged": credits},
        ) from exc
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(
            status_code=502,
            detail={"code": "crawl_failed", "message": f"{type(exc).__name__}: {exc}", "request_id": request_id, "credits_charged": credits},
        ) from exc
    finally:
        elapsed = max(0, int((time.monotonic() - started) * 1000))
        try:
            store.finish_usage(request_id, status=status, latency_ms=elapsed, output_bytes=output_bytes)
        except Exception:  # noqa: BLE001, S110 -- metering cleanup must not mask response
            pass
