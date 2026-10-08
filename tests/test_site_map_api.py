from __future__ import annotations

from pathlib import Path

import pytest

from internet_hands import site_map_api
from internet_hands.datasets import result_rows


def test_map_arguments_normalize_product_controls(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(site_map_api, "validate_public_http_url", lambda value: value)
    arguments = site_map_api._map_arguments(
        {
            "url": "https://example.com/",
            "search": " docs ",
            "limit": 125,
            "include_subdomains": True,
            "sitemap_mode": "only",
        }
    )
    assert arguments == {
        "url": "https://example.com/",
        "search": "docs",
        "limit": 125,
        "includeSubdomains": True,
        "sitemapOnly": True,
    }


@pytest.mark.parametrize("value", [0, 1001, 1.5, "250", True])
def test_map_limit_requires_bounded_integer(monkeypatch: pytest.MonkeyPatch, value) -> None:
    monkeypatch.setattr(site_map_api, "validate_public_http_url", lambda target: target)
    with pytest.raises(Exception) as caught:
        site_map_api._map_arguments({"url": "https://example.com", "limit": value})
    assert getattr(caught.value, "status_code", None) == 400


def test_normalized_map_rows_are_same_site_deduplicated_and_classified() -> None:
    rows, reported, truncated = site_map_api._normalized_rows(
        {
            "links": [
                "https://example.com/",
                {"url": "https://www.example.com/docs/api", "title": "API docs"},
                "https://example.com/pricing",
                "https://example.com/pricing#plans",
                "https://sub.example.com/products/widget",
                "https://other.example.net/outside",
            ],
            "total_links": 8,
        },
        root_url="https://example.com",
        limit=20,
        include_subdomains=False,
    )
    assert [row["category"] for row in rows] == ["home", "docs", "pricing"]
    assert rows[1]["depth"] == 2
    assert rows[1]["parent_url"] == "https://www.example.com/docs/"
    assert reported == 8
    assert truncated is True


def test_subdomain_rows_are_kept_only_when_requested() -> None:
    data = {"links": ["https://sub.example.com/products/widget"]}
    denied, _, _ = site_map_api._normalized_rows(
        data, root_url="https://example.com", limit=10, include_subdomains=False
    )
    allowed, _, _ = site_map_api._normalized_rows(
        data, root_url="https://example.com", limit=10, include_subdomains=True
    )
    assert denied == []
    assert allowed[0]["category"] == "products"


def test_site_map_payload_is_dataset_compatible() -> None:
    payload = site_map_api._result_payload(
        {"links": ["https://example.com/docs", "https://example.com/pricing"]},
        arguments={
            "url": "https://example.com",
            "limit": 10,
            "includeSubdomains": False,
        },
    )
    rows = result_rows(payload)
    assert len(rows) == 2
    assert {row["record_type"] for row in rows} == {"urls"}
    assert payload["categories"] == {"docs": 1, "pricing": 1}


def test_site_map_routes_and_console_surface_are_registered() -> None:
    paths = {route.path for route in site_map_api.router.routes if hasattr(route, "path")}
    assert "/api/site-map/quote" in paths
    assert "/api/site-map/run" in paths

    root = Path(__file__).resolve().parents[1]
    saas = (root / "src" / "internet_hands" / "saas_app.py").read_text(encoding="utf-8")
    assert "from .site_map_api import router as site_map_router" in saas
    assert "app.include_router(site_map_router)" in saas

    web = (root / "web" / "app.js").read_text(encoding="utf-8")
    assert "map:dashSiteMap" in web
    assert "['map','map','Site Map']" in web
    assert "/api/site-map/quote" in web
    assert "/api/site-map/run" in web
    assert "Confirm and map site" in web


def test_site_map_is_exposed_in_product_docs() -> None:
    import json

    raw = (Path(__file__).resolve().parents[1] / "web" / "docs-content.js").read_text(encoding="utf-8").strip()
    prefix = "window.OPENCRAWL_DOCS = "
    assert raw.startswith(prefix) and raw.endswith(";")
    docs = json.loads(raw[len(prefix):-1])
    title, group, body = docs["site-map"]
    assert title == "Site Map"
    assert group == "Collect and use data"
    assert len(body) >= 1200
    assert "/api/site-map/quote" in body
    assert "/api/site-map/run" in body
    assert "quote_revision" in body
    assert "dataset.saved" in body
