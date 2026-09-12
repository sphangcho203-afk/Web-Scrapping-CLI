from __future__ import annotations

import dataclasses
import ipaddress
import socket
from datetime import UTC, datetime
from urllib.parse import urlsplit


class PolicyError(ValueError):
    pass


@dataclasses.dataclass(frozen=True, slots=True)
class ResolutionSnapshot:
    url: str
    host: str
    port: int
    addresses: tuple[str, ...]
    resolved_at: datetime


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

    port = parts.port or (443 if parts.scheme == "https" else 80)
    try:
        raw_addresses = {info[4][0] for info in socket.getaddrinfo(host, port)}
    except socket.gaierror as exc:
        raise PolicyError(f"DNS resolution failed for {host}") from exc
    addresses = tuple(sorted(validate_public_ip(raw) for raw in raw_addresses))
    if not addresses:
        raise PolicyError(f"DNS resolution returned no usable addresses for {host}")
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
