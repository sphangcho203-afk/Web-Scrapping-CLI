from __future__ import annotations

import ipaddress
import socket
from urllib.parse import urlsplit


class PolicyError(ValueError):
    pass


def validate_public_http_url(url: str) -> str:
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
        addresses = {info[4][0] for info in socket.getaddrinfo(host, port)}
    except socket.gaierror as exc:
        raise PolicyError(f"DNS resolution failed for {host}") from exc

    for raw in addresses:
        ip = ipaddress.ip_address(raw)
        if (
            ip.is_private
            or ip.is_loopback
            or ip.is_link_local
            or ip.is_multicast
            or ip.is_reserved
            or ip.is_unspecified
        ):
            raise PolicyError(f"Target resolves to a non-public address: {ip}")

    return url
