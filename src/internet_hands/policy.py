from __future__ import annotations

import dataclasses
import errno
import ipaddress
import socket
import threading
import time
from datetime import UTC, datetime
from urllib.parse import urlsplit


class PolicyError(ValueError):
    pass


class ResolutionUnavailable(PolicyError):
    """Transient DNS resolver failure that should be retried by the caller."""


@dataclasses.dataclass(frozen=True, slots=True)
class ResolutionSnapshot:
    url: str
    host: str
    port: int
    addresses: tuple[str, ...]
    resolved_at: datetime


_DNS_CACHE_TTL_SECONDS = 60.0
_DNS_CACHE: dict[tuple[str, int], tuple[float, tuple[str, ...]]] = {}
_DNS_CACHE_LOCK = threading.Lock()
_TRANSIENT_RESOLVER_ERRNOS = {
    errno.EAGAIN,
    errno.EBUSY,
    errno.EMFILE,
    errno.ENFILE,
}


def validate_public_ip(raw: str) -> str:
    try:
        ip = ipaddress.ip_address(raw)
    except ValueError as exc:
        raise PolicyError(f"Invalid peer IP address: {raw}") from exc
    if (
        ip.is_private
        or ip.is_loopback
        or ip.is_link_local
        or ip.is_multicast
        or ip.is_reserved
        or ip.is_unspecified
    ):
        raise PolicyError(f"Target resolves/connects to a non-public address: {ip}")
    return str(ip)


def _cached_addresses(host: str, port: int) -> tuple[str, ...] | None:
    key = (host.casefold(), port)
    now = time.monotonic()
    with _DNS_CACHE_LOCK:
        cached = _DNS_CACHE.get(key)
        if not cached:
            return None
        expires_at, addresses = cached
        if expires_at <= now:
            _DNS_CACHE.pop(key, None)
            return None
        return addresses


def _cache_addresses(host: str, port: int, addresses: tuple[str, ...]) -> None:
    key = (host.casefold(), port)
    with _DNS_CACHE_LOCK:
        _DNS_CACHE[key] = (time.monotonic() + _DNS_CACHE_TTL_SECONDS, addresses)


def _resolve_addresses(host: str, port: int) -> tuple[str, ...]:
    cached = _cached_addresses(host, port)
    if cached is not None:
        return cached

    last_transient: OSError | None = None
    for attempt in range(3):
        try:
            raw_addresses = {
                info[4][0]
                for info in socket.getaddrinfo(
                    host,
                    port,
                    type=socket.SOCK_STREAM,
                )
            }
            addresses = tuple(sorted(validate_public_ip(raw) for raw in raw_addresses))
            if not addresses:
                raise PolicyError(f"DNS resolution returned no usable addresses for {host}")
            _cache_addresses(host, port, addresses)
            return addresses
        except socket.gaierror as exc:
            if exc.errno == getattr(socket, "EAI_AGAIN", None) and attempt < 2:
                last_transient = exc
                time.sleep(0.04 * (2**attempt))
                continue
            raise PolicyError(f"DNS resolution failed for {host}") from exc
        except OSError as exc:
            if exc.errno in _TRANSIENT_RESOLVER_ERRNOS:
                last_transient = exc
                if attempt < 2:
                    time.sleep(0.04 * (2**attempt))
                    continue
                break
            raise PolicyError(f"DNS resolution failed for {host}") from exc

    raise ResolutionUnavailable(
        f"DNS resolver is temporarily busy for {host}; retry the request"
    ) from last_transient


def resolve_public_http_url(url: str) -> ResolutionSnapshot:
    parts = urlsplit(url)
    if parts.scheme not in {"http", "https"}:
        raise PolicyError("Only http and https URLs are supported")
    if not parts.hostname:
        raise PolicyError("URL must include a hostname")
    if parts.username or parts.password:
        raise PolicyError("Credentials embedded in URLs are not accepted")

    host = parts.hostname.rstrip(".")
    if host.lower() == "localhost":
        raise PolicyError("Localhost targets are blocked")

    try:
        port = parts.port or (443 if parts.scheme == "https" else 80)
    except ValueError as exc:
        raise PolicyError("URL contains an invalid port") from exc

    addresses = _resolve_addresses(host, port)
    return ResolutionSnapshot(
        url=url,
        host=host,
        port=port,
        addresses=addresses,
        resolved_at=datetime.now(UTC),
    )


def validate_public_http_url(url: str) -> str:
    resolve_public_http_url(url)
    return url
