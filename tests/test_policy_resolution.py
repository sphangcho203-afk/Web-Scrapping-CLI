import socket

import pytest

from internet_hands import policy
from internet_hands.policy import PolicyError, resolve_public_http_url, validate_public_ip


def test_resolution_snapshot_accepts_public_addresses(monkeypatch):
    monkeypatch.setattr(
        socket,
        "getaddrinfo",
        lambda host, port: [
            (socket.AF_INET, socket.SOCK_STREAM, 6, "", ("8.8.8.8", port)),
            (socket.AF_INET, socket.SOCK_STREAM, 6, "", ("1.1.1.1", port)),
        ],
    )
    snapshot = resolve_public_http_url("https://example.com/path")
    assert snapshot.host == "example.com"
    assert snapshot.port == 443
    assert snapshot.addresses == ("1.1.1.1", "8.8.8.8")


def test_resolution_snapshot_rejects_private_address(monkeypatch):
    monkeypatch.setattr(
        socket,
        "getaddrinfo",
        lambda host, port: [
            (socket.AF_INET, socket.SOCK_STREAM, 6, "", ("10.0.0.5", port)),
        ],
    )
    with pytest.raises(PolicyError, match="non-public"):
        resolve_public_http_url("https://example.com/")


def test_peer_ip_validation_rejects_loopback():
    with pytest.raises(PolicyError, match="non-public"):
        validate_public_ip("127.0.0.1")
    assert validate_public_ip("8.8.4.4") == "8.8.4.4"


def test_localhost_is_rejected_without_dns(monkeypatch):
    monkeypatch.setattr(policy.socket, "getaddrinfo", lambda *args: pytest.fail("DNS called"))
    with pytest.raises(PolicyError, match="Localhost"):
        resolve_public_http_url("http://localhost/")
