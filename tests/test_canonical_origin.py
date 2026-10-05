from __future__ import annotations

import pytest
from starlette.requests import Request

from internet_hands.control_api import CANONICAL_PUBLIC_ORIGIN, _origin


def _request(host: str, *, proto: str = "https") -> Request:
    scope = {
        "type": "http",
        "http_version": "1.1",
        "method": "GET",
        "scheme": proto,
        "path": "/",
        "raw_path": b"/",
        "query_string": b"",
        "headers": [
            (b"host", host.encode("ascii")),
            (b"x-forwarded-proto", proto.encode("ascii")),
        ],
        "client": ("127.0.0.1", 12345),
        "server": (host, 443 if proto == "https" else 80),
    }
    return Request(scope)


def test_production_aliases_canonicalize_to_opencrawl(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("OPENCRAWL_PUBLIC_ORIGIN", raising=False)
    monkeypatch.delenv("INTERNET_HANDS_PUBLIC_ORIGIN", raising=False)

    assert _origin(_request("opencrawl.top")) == CANONICAL_PUBLIC_ORIGIN
    assert _origin(_request("www.opencrawl.top")) == CANONICAL_PUBLIC_ORIGIN
    assert _origin(_request("web-scrapping-cli.vercel.app")) == CANONICAL_PUBLIC_ORIGIN


def test_preview_origin_stays_on_preview_deployment(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("OPENCRAWL_PUBLIC_ORIGIN", raising=False)
    monkeypatch.delenv("INTERNET_HANDS_PUBLIC_ORIGIN", raising=False)

    preview = "web-scrapping-cli-git-feature-stand-still.vercel.app"
    assert _origin(_request(preview)) == f"https://{preview}"


def test_operator_can_override_public_origin(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("OPENCRAWL_PUBLIC_ORIGIN", "https://staging.opencrawl.example")
    monkeypatch.delenv("INTERNET_HANDS_PUBLIC_ORIGIN", raising=False)

    assert _origin(_request("web-scrapping-cli.vercel.app")) == (
        "https://staging.opencrawl.example"
    )
