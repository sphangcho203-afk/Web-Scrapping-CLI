"""Bounded, signed delivery of saved-output notifications."""
from __future__ import annotations

import asyncio
import hashlib
import hmac
import ipaddress
import time
from urllib.parse import urlsplit

import httpx

from .policy import PolicyError, ResolutionUnavailable, resolve_public_http_url, validate_public_ip
from .totp import decrypt_secret

DELIVERY_TIMEOUT = 5.0
MAX_ATTEMPTS = 5
MAX_BATCH = 5


def validate_webhook_url(url: str) -> str:
    if not isinstance(url, str) or not url or len(url) > 2000 or any(c.isspace() for c in url):
        raise PolicyError("Webhook URL must be a public HTTPS URL of at most 2000 characters.")
    try:
        parts = urlsplit(url)
        port = parts.port
    except ValueError as exc:
        raise PolicyError("Invalid webhook port.") from exc
    if (parts.scheme != "https" or not parts.hostname or parts.username is not None
            or parts.password is not None or parts.fragment or port not in (None, 443)):
        raise PolicyError("Webhook URL requires HTTPS on port 443, without credentials or fragments.")
    # Validate literal IPs immediately; DNS names are resolved again before each send.
    try:
        ipaddress.ip_address(parts.hostname)
    except ValueError:
        pass
    else:
        validate_public_ip(parts.hostname)
    if parts.hostname.casefold() in {"localhost", "localhost.localdomain"}:
        raise PolicyError("Webhook URL must be public.")
    try:
        return str(httpx.URL(url))
    except httpx.InvalidURL as exc:
        raise PolicyError("Invalid webhook URL.") from exc


def delivery_headers(secret: str, event_id: str, body: bytes, *, timestamp: int | None = None) -> dict[str, str]:
    stamp = int(time.time()) if timestamp is None else timestamp
    digest = hmac.new(secret.encode(), str(stamp).encode() + b"." + body, hashlib.sha256).hexdigest()
    return {"Content-Type": "application/json", "User-Agent": "OpenCrawl-Webhooks/1.0",
            "X-OpenCrawl-Event": "dataset.saved", "X-OpenCrawl-Delivery": event_id,
            "X-OpenCrawl-Signature": f"t={stamp},v1={digest}"}


async def send_webhook(url: str, body: bytes, headers: dict[str, str]) -> int:
    url = validate_webhook_url(url)
    snapshot = await asyncio.to_thread(resolve_public_http_url, url)
    # Connect to a validated numeric address, retaining the hostname for HTTP and
    # TLS verification. No second DNS lookup can redirect the payload to a private IP.
    address = validate_public_ip(snapshot.addresses[0])
    request_url = httpx.URL(url).copy_with(host=address)
    async with httpx.AsyncClient(timeout=DELIVERY_TIMEOUT, follow_redirects=False,
                                 trust_env=False) as client, client.stream("POST", request_url, content=body,
                                 headers={**headers, "Host": httpx.URL(url).netloc.decode("ascii")},
                                 extensions={"sni_hostname": snapshot.host}) as response:
        # Response bodies are never buffered or retained.
        return response.status_code


async def dispatch_webhooks(webhooks, *, limit: int = MAX_BATCH) -> dict:
    events = await asyncio.to_thread(webhooks.claim, limit)
    results = []
    for event in events:
        http_status = None
        error = None
        permanent = False
        try:
            body = event["body"].encode("utf-8")
            headers = delivery_headers(decrypt_secret(event["secret_enc"]), event["id"], body)
            if not await asyncio.to_thread(webhooks.begin_attempt, event):
                results.append({"id": event["id"], "error": "Delivery attempt is no longer available."})
                continue
            http_status = await asyncio.wait_for(send_webhook(event["url"], body, headers), DELIVERY_TIMEOUT)
            if not 200 <= http_status < 300:
                error = f"Receiver returned HTTP {http_status}."
                permanent = 300 <= http_status < 500 and http_status not in {408, 429}
        except ResolutionUnavailable:
            error = "Public DNS resolution is temporarily unavailable."
        except PolicyError:
            error = "Endpoint failed public-target validation."
            permanent = True
        except Exception as exc:  # noqa: BLE001 -- do not expose URLs, secrets or receiver bodies
            error = f"Delivery failed ({type(exc).__name__})."
        try:
            await asyncio.to_thread(webhooks.finish, event, http_status=http_status, error=error, permanent=permanent)
            results.append({"id": event["id"], "http_status": http_status, "error": error})
        except Exception:  # noqa: BLE001 -- lease recovery handles a failed persistence attempt
            results.append({"id": event["id"], "error": "Delivery outcome could not be recorded; lease recovery will retry."})
    return {"claimed": len(events), "processed": len(results), "deliveries": results}
