from __future__ import annotations

import base64
import hashlib
import json
import time
from datetime import UTC, datetime
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import unquote, urljoin, urlsplit

import httpx

from .models import ApiEnvelope, DownloadInfo, FetchResult, HealthResult, LinkResult
from .policy import resolve_public_http_url, validate_public_http_url, validate_public_ip

DEFAULT_UA = "InternetHands/0.2 (+https://github.com/sphangcho203-afk/Web-Scrapping-CLI)"
REDIRECT_CODES = {301, 302, 303, 307, 308}


class BodyTooLarge(RuntimeError):
    pass


class TooManyRedirects(RuntimeError):
    pass


class _LinkParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.hrefs: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag.lower() != "a":
            return
        for key, value in attrs:
            if key.lower() == "href" and value:
                self.hrefs.append(value)


async def fetch_url(
    url: str,
    *,
    timeout: float = 20.0,
    max_bytes: int = 8_000_000,
    include_body: bool = True,
    user_agent: str = DEFAULT_UA,
    max_redirects: int = 10,
) -> FetchResult:
    started = time.perf_counter()
    current = url

    async with httpx.AsyncClient(
        follow_redirects=False,
        timeout=timeout,
        headers={"User-Agent": user_agent, "Accept": "*/*"},
    ) as client:
        for _ in range(max_redirects + 1):
            snapshot = resolve_public_http_url(current)
            async with client.stream("GET", current) as response:
                peer_ip = _peer_ip(response)
                if peer_ip is not None:
                    peer_ip = validate_public_ip(peer_ip)
                if response.status_code in REDIRECT_CODES and response.headers.get("location"):
                    current = urljoin(str(response.url), response.headers["location"])
                    continue

                chunks: list[bytes] = []
                total = 0
                async for chunk in response.aiter_bytes():
                    total += len(chunk)
                    if total > max_bytes:
                        raise BodyTooLarge(f"Response exceeded max_bytes={max_bytes}")
                    chunks.append(chunk)
                body = b"".join(chunks)
                final_url = str(response.url)
                status_code = response.status_code
                headers = {k.lower(): v for k, v in response.headers.items()}
                headers["x-internet-hands-resolved-addresses"] = ",".join(snapshot.addresses)
                if peer_ip is not None:
                    headers["x-internet-hands-peer-ip"] = peer_ip
                encoding = response.encoding
                break
        else:
            raise TooManyRedirects(f"Exceeded max_redirects={max_redirects}")

    elapsed_ms = (time.perf_counter() - started) * 1000
    content_type = headers.get("content-type")
    text: str | None = None
    encoded: str | None = None
    if include_body:
        encoded = base64.b64encode(body).decode("ascii")
        if _looks_textual(content_type):
            text = body.decode(encoding or "utf-8", errors="replace")

    return FetchResult(
        request_url=url,
        final_url=final_url,
        status_code=status_code,
        headers=headers,
        content_type=content_type,
        content_length=len(body),
        sha256=hashlib.sha256(body).hexdigest(),
        elapsed_ms=round(elapsed_ms, 2),
        captured_at=datetime.now(UTC),
        body_text=text,
        body_base64=encoded,
    )


def extract_links(result: FetchResult) -> LinkResult:
    if not result.body_text:
        return LinkResult(source_url=result.final_url, links=[])
    parser = _LinkParser()
    parser.feed(result.body_text)
    links: set[str] = set()
    for href in parser.hrefs:
        absolute = urljoin(result.final_url, href)
        parts = urlsplit(absolute)
        if parts.scheme in {"http", "https"}:
            clean = parts._replace(fragment="").geturl()
            links.add(clean)
    return LinkResult(source_url=result.final_url, links=sorted(links))


async def inspect_api(
    url: str, *, timeout: float = 20.0, max_bytes: int = 8_000_000
) -> ApiEnvelope:
    result = await fetch_url(url, timeout=timeout, max_bytes=max_bytes, include_body=True)
    parsed = None
    if result.body_text:
        try:
            parsed = json.loads(result.body_text)
        except json.JSONDecodeError:
            parsed = None
    return ApiEnvelope(fetch=result, parsed=parsed)


async def health_check(url: str, *, timeout: float = 10.0) -> HealthResult:
    try:
        result = await fetch_url(url, timeout=timeout, max_bytes=1_000_000, include_body=False)
        return HealthResult(
            url=url,
            ok=200 <= result.status_code < 400,
            status_code=result.status_code,
            elapsed_ms=result.elapsed_ms,
            content_type=result.content_type,
        )
    except Exception as exc:  # noqa: BLE001 -- health boundary returns failures as data
        return HealthResult(url=url, ok=False, error=f"{type(exc).__name__}: {exc}")


async def inspect_download(
    url: str, *, timeout: float = 20.0, max_redirects: int = 10
) -> DownloadInfo:
    current = url
    peer_ip: str | None = None
    resolved_addresses: tuple[str, ...] = ()
    async with httpx.AsyncClient(
        follow_redirects=False,
        timeout=timeout,
        headers={"User-Agent": DEFAULT_UA, "Accept": "*/*"},
    ) as client:
        for _ in range(max_redirects + 1):
            snapshot = resolve_public_http_url(current)
            resolved_addresses = snapshot.addresses
            response = await client.head(current)
            peer_ip = _peer_ip(response)
            if peer_ip is not None:
                peer_ip = validate_public_ip(peer_ip)
            if response.status_code in REDIRECT_CODES and response.headers.get("location"):
                current = urljoin(str(response.url), response.headers["location"])
                validate_public_http_url(current)
                continue
            if response.status_code in {405, 501}:
                response = await client.get(current, headers={"Range": "bytes=0-0"})
                peer_ip = _peer_ip(response)
                if peer_ip is not None:
                    peer_ip = validate_public_ip(peer_ip)
            break
        else:
            raise TooManyRedirects(f"Exceeded max_redirects={max_redirects}")

    disposition = response.headers.get("content-disposition")
    filename = (
        _filename_from_headers(disposition)
        or Path(unquote(urlsplit(str(response.url)).path)).name
        or None
    )
    length = response.headers.get("content-length")
    headers = {k.lower(): v for k, v in response.headers.items()}
    headers["x-internet-hands-resolved-addresses"] = ",".join(resolved_addresses)
    if peer_ip is not None:
        headers["x-internet-hands-peer-ip"] = peer_ip
    return DownloadInfo(
        request_url=url,
        final_url=str(response.url),
        status_code=response.status_code,
        content_type=response.headers.get("content-type"),
        content_length=int(length) if length and length.isdigit() else None,
        filename=filename,
        disposition=disposition,
        headers=headers,
    )


def save_capture(result: FetchResult, root: Path = Path("data/runs")) -> Path:
    run_id = result.captured_at.strftime("%Y%m%dT%H%M%S.%fZ") + "-" + result.sha256[:12]
    target = root / run_id
    target.mkdir(parents=True, exist_ok=False)
    manifest = result.model_copy(update={"body_text": None, "body_base64": None})
    (target / "manifest.json").write_text(manifest.model_dump_json(indent=2), encoding="utf-8")
    if result.body_base64 is not None:
        (target / "body.bin").write_bytes(base64.b64decode(result.body_base64))
    if result.body_text is not None:
        (target / "body.txt").write_text(result.body_text, encoding="utf-8")
    return target


def _peer_ip(response: httpx.Response) -> str | None:
    stream = response.extensions.get("network_stream")
    if stream is None or not hasattr(stream, "get_extra_info"):
        return None
    try:
        server = stream.get_extra_info("server_addr")
    except (AttributeError, OSError, TypeError):
        return None
    if isinstance(server, tuple) and server:
        return str(server[0])
    if isinstance(server, str):
        return server
    return None


def _looks_textual(content_type: str | None) -> bool:
    if not content_type:
        return False
    lowered = content_type.lower()
    return any(x in lowered for x in ("text/", "json", "xml", "javascript", "svg"))


def _filename_from_headers(disposition: str | None) -> str | None:
    if not disposition:
        return None
    for part in disposition.split(";"):
        part = part.strip()
        if part.lower().startswith("filename="):
            return part.split("=", 1)[1].strip().strip('"') or None
    return None
