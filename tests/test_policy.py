import errno

import pytest

from internet_hands import policy
from internet_hands.policy import (
    PolicyError,
    ResolutionUnavailable,
    resolve_public_http_url,
    validate_public_http_url,
)


def test_blocks_non_http_scheme():
    with pytest.raises(PolicyError):
        validate_public_http_url("file:///etc/passwd")


def test_blocks_embedded_credentials():
    with pytest.raises(PolicyError):
        validate_public_http_url("https://user:pass@example.com/")


def test_blocks_localhost():
    with pytest.raises(PolicyError):
        validate_public_http_url("http://localhost:8080/")


def test_transient_resolver_busy_retries(monkeypatch):
    policy._DNS_CACHE.clear()
    calls = {"count": 0}

    def fake_getaddrinfo(host, port, **kwargs):
        calls["count"] += 1
        if calls["count"] < 3:
            raise OSError(errno.EBUSY, "Device or resource busy")
        return [(2, 1, 6, "", ("93.184.216.34", port))]

    monkeypatch.setattr(policy.socket, "getaddrinfo", fake_getaddrinfo)
    monkeypatch.setattr(policy.time, "sleep", lambda _seconds: None)

    snapshot = resolve_public_http_url("https://example.com/")
    assert snapshot.addresses == ("93.184.216.34",)
    assert calls["count"] == 3


def test_successful_resolution_is_cached(monkeypatch):
    policy._DNS_CACHE.clear()
    calls = {"count": 0}

    def fake_getaddrinfo(host, port, **kwargs):
        calls["count"] += 1
        return [(2, 1, 6, "", ("93.184.216.34", port))]

    monkeypatch.setattr(policy.socket, "getaddrinfo", fake_getaddrinfo)

    resolve_public_http_url("https://example.com/a")
    resolve_public_http_url("https://example.com/b")
    assert calls["count"] == 1


def test_persistent_resolver_busy_becomes_controlled_error(monkeypatch):
    policy._DNS_CACHE.clear()

    def always_busy(host, port, **kwargs):
        raise OSError(errno.EBUSY, "Device or resource busy")

    monkeypatch.setattr(policy.socket, "getaddrinfo", always_busy)
    monkeypatch.setattr(policy.time, "sleep", lambda _seconds: None)

    with pytest.raises(ResolutionUnavailable):
        resolve_public_http_url("https://example.com/")
