from __future__ import annotations

import asyncio
import base64
import hashlib
import json
import subprocess
import tempfile
import time
from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from .fetcher import fetch_url, inspect_api
from .models import FetchResult
from .policy import validate_public_http_url


class Adapter(ABC):
    """Extension point for public or explicitly authorized platform collectors."""

    name: str

    @abstractmethod
    def supports(self, url: str) -> bool:
        raise NotImplementedError

    @abstractmethod
    async def collect(self, url: str) -> Any:
        raise NotImplementedError


class HttpAdapter(Adapter):
    name = "http"

    def supports(self, url: str) -> bool:
        return url.startswith(("http://", "https://"))

    async def collect(self, url: str) -> FetchResult:
        return await fetch_url(url, include_body=True)


class JsonApiAdapter(Adapter):
    name = "json-api"

    def supports(self, url: str) -> bool:
        return url.startswith(("http://", "https://"))

    async def collect(self, url: str) -> Any:
        return await inspect_api(url)


@dataclass
class AdapterRegistry:
    adapters: list[Adapter]

    @classmethod
    def default(cls) -> AdapterRegistry:
        return cls(adapters=[JsonApiAdapter(), HttpAdapter()])

    def get(self, name: str) -> Adapter:
        for adapter in self.adapters:
            if adapter.name == name:
                return adapter
        raise KeyError(f"Unknown adapter: {name}")


class AdapterError(RuntimeError):
    pass


class ExternalNetworkNotAllowed(AdapterError):
    pass


def _require_external_network(allow_external_network: bool) -> None:
    if not allow_external_network:
        raise ExternalNetworkNotAllowed(
            "External crawler networking is disabled by default. Enable it only inside a "
            "public-egress-restricted worker environment."
        )


def _result(
    *,
    backend: str,
    request_url: str,
    final_url: str,
    status_code: int,
    headers: dict[str, str] | None,
    body: bytes,
    elapsed_ms: float,
) -> FetchResult:
    validate_public_http_url(final_url)
    normalized_headers = {str(key).lower(): str(value) for key, value in (headers or {}).items()}
    normalized_headers["x-internet-hands-backend"] = backend
    content_type = normalized_headers.get("content-type") or "text/html; charset=utf-8"
    body_text = body.decode("utf-8", errors="replace")
    return FetchResult(
        request_url=request_url,
        final_url=final_url,
        status_code=status_code,
        headers=normalized_headers,
        content_type=content_type,
        content_length=len(body),
        sha256=hashlib.sha256(body).hexdigest(),
        elapsed_ms=round(elapsed_ms, 2),
        captured_at=datetime.now(UTC),
        body_text=body_text,
        body_base64=base64.b64encode(body).decode("ascii"),
    )


async def crawlee_capture(
    url: str,
    *,
    allow_external_network: bool = False,
    max_bytes: int = 8_000_000,
) -> FetchResult:
    """Fetch one URL through Crawlee's current HttpCrawler API."""
    _require_external_network(allow_external_network)
    validate_public_http_url(url)
    try:
        from crawlee.crawlers import HttpCrawler
    except ImportError as exc:
        raise AdapterError(
            "Crawlee is optional. Install with: pip install 'internet-hands[crawlee]'"
        ) from exc

    captured: dict[str, Any] = {}
    crawler = HttpCrawler(max_requests_per_crawl=1)

    @crawler.router.default_handler
    async def handler(context) -> None:
        body = await context.http_response.read()
        if len(body) > max_bytes:
            raise AdapterError(f"Crawlee response exceeded max_bytes={max_bytes}")
        loaded_url = context.request.loaded_url or context.request.url
        captured.update(
            {
                "body": body,
                "url": str(loaded_url),
                "status": int(context.http_response.status_code),
                "headers": {
                    str(key): str(value)
                    for key, value in dict(context.http_response.headers).items()
                },
            }
        )

    started = time.perf_counter()
    await crawler.run([url])
    if not captured:
        raise AdapterError("Crawlee completed without producing a capture")
    return _result(
        backend="crawlee-http",
        request_url=url,
        final_url=str(captured["url"]),
        status_code=int(captured["status"]),
        headers=captured["headers"],
        body=captured["body"],
        elapsed_ms=(time.perf_counter() - started) * 1000,
    )


async def crawl4ai_capture(
    url: str,
    *,
    allow_external_network: bool = False,
    max_bytes: int = 8_000_000,
) -> FetchResult:
    """Render one public URL through Crawl4AI and normalize the result."""
    _require_external_network(allow_external_network)
    validate_public_http_url(url)
    try:
        from crawl4ai import AsyncWebCrawler
    except ImportError as exc:
        raise AdapterError(
            "Crawl4AI is optional. Install with: pip install 'internet-hands[crawl4ai]'"
        ) from exc

    started = time.perf_counter()
    async with AsyncWebCrawler() as crawler:
        result = await crawler.arun(url=url)
    if not getattr(result, "success", False):
        message = getattr(result, "error_message", None) or "Crawl4AI crawl failed"
        raise AdapterError(str(message))
    final_url = str(getattr(result, "url", url))
    validate_public_http_url(final_url)
    html = str(getattr(result, "html", "") or "")
    body = html.encode("utf-8")
    if len(body) > max_bytes:
        raise AdapterError(f"Crawl4AI response exceeded max_bytes={max_bytes}")
    headers = getattr(result, "response_headers", None) or {}
    status_code = int(getattr(result, "status_code", 200) or 200)
    return _result(
        backend="crawl4ai",
        request_url=url,
        final_url=final_url,
        status_code=status_code,
        headers={str(key): str(value) for key, value in dict(headers).items()},
        body=body,
        elapsed_ms=(time.perf_counter() - started) * 1000,
    )


async def scrapy_capture(
    url: str,
    *,
    allow_external_network: bool = False,
    max_bytes: int = 8_000_000,
    timeout: float = 30.0,
) -> FetchResult:
    """Run a one-request Scrapy worker with redirects disabled and normalize its output."""
    _require_external_network(allow_external_network)
    validate_public_http_url(url)
    return await asyncio.to_thread(_scrapy_capture_sync, url, max_bytes, timeout)


def _scrapy_capture_sync(url: str, max_bytes: int, timeout: float) -> FetchResult:
    spider = r'''
import base64
import scrapy

class InternetHandsSingleSpider(scrapy.Spider):
    name = "internet_hands_single"
    custom_settings = {
        "LOG_ENABLED": False,
        "ROBOTSTXT_OBEY": True,
        "REDIRECT_ENABLED": False,
        "DOWNLOAD_FAIL_ON_DATALOSS": True,
    }

    def __init__(self, target=None, max_bytes="8000000", *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.target = target
        self.max_bytes = int(max_bytes)

    def start_requests(self):
        yield scrapy.Request(self.target, callback=self.parse, dont_filter=True)

    def parse(self, response):
        body = bytes(response.body)
        if len(body) > self.max_bytes:
            raise RuntimeError(f"response exceeded max_bytes={self.max_bytes}")
        headers = {}
        for key, values in response.headers.items():
            rendered = b", ".join(values).decode("latin-1", errors="replace")
            headers[key.decode("latin-1", errors="replace")] = rendered
        yield {
            "url": response.url,
            "status": response.status,
            "headers": headers,
            "body_base64": base64.b64encode(body).decode("ascii"),
        }
'''
    with tempfile.TemporaryDirectory(prefix="internet-hands-scrapy-") as temp_dir:
        root = Path(temp_dir)
        spider_path = root / "spider.py"
        output_path = root / "result.jsonl"
        spider_path.write_text(spider, encoding="utf-8")
        started = time.perf_counter()
        try:
            process = subprocess.run(
                [
                    "scrapy",
                    "runspider",
                    str(spider_path),
                    "-a",
                    f"target={url}",
                    "-a",
                    f"max_bytes={max_bytes}",
                    "-O",
                    str(output_path),
                    "-s",
                    f"DOWNLOAD_TIMEOUT={max(1, int(timeout))}",
                ],
                check=False,
                capture_output=True,
                text=True,
                timeout=timeout + 10,
            )
        except FileNotFoundError as exc:
            raise AdapterError(
                "Scrapy is optional. Install with: pip install 'internet-hands[scrapy]'"
            ) from exc
        except subprocess.TimeoutExpired as exc:
            raise AdapterError("Scrapy adapter timed out") from exc
        if process.returncode != 0:
            message = process.stderr.strip() or process.stdout.strip() or "Scrapy adapter failed"
            raise AdapterError(message[-4000:])
        if not output_path.exists():
            raise AdapterError("Scrapy completed without producing output")
        lines = [
            line
            for line in output_path.read_text(encoding="utf-8").splitlines()
            if line.strip()
        ]
        if not lines:
            raise AdapterError("Scrapy produced an empty capture")
        record = json.loads(lines[0])
        body = base64.b64decode(record["body_base64"])
        return _result(
            backend="scrapy",
            request_url=url,
            final_url=str(record["url"]),
            status_code=int(record["status"]),
            headers={str(key): str(value) for key, value in record.get("headers", {}).items()},
            body=body,
            elapsed_ms=(time.perf_counter() - started) * 1000,
        )


async def capture_with_backend(
    backend: str,
    url: str,
    *,
    allow_external_network: bool = False,
    max_bytes: int = 8_000_000,
) -> FetchResult:
    normalized = backend.strip().lower()
    if normalized in {"crawlee", "crawlee-http"}:
        return await crawlee_capture(
            url,
            allow_external_network=allow_external_network,
            max_bytes=max_bytes,
        )
    if normalized == "crawl4ai":
        return await crawl4ai_capture(
            url,
            allow_external_network=allow_external_network,
            max_bytes=max_bytes,
        )
    if normalized == "scrapy":
        return await scrapy_capture(
            url,
            allow_external_network=allow_external_network,
            max_bytes=max_bytes,
        )
    raise AdapterError(f"Unknown external backend: {backend}")
