from __future__ import annotations

from pathlib import Path

import pytest
from fastapi import HTTPException

from internet_hands import smart_scrape_api
from internet_hands.capability_economics import estimate_call, settle_measured_cost
from internet_hands.datasets import result_rows


def test_auto_markdown_scrape_keeps_smart_native_first_route(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(smart_scrape_api, "validate_public_http_url", lambda value: value)
    capability, arguments, product = smart_scrape_api._normalize_scrape(
        {
            "url": "https://example.com/docs",
            "mode": "auto",
            "formats": ["markdown", "links"],
            "timeout_ms": 20_000,
        }
    )
    assert capability == "web.scrape.smart"
    assert arguments["url"] == "https://example.com/docs"
    assert arguments["formats"] == ["markdown", "links"]
    assert arguments["timeout"] == 20_000
    assert product["execution_mode"] == "auto"


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("formats", ["screenshot"]),
        ("formats", ["html"]),
        ("mobile", True),
        ("wait_ms", 500),
        ("max_age_ms", 30_000),
    ],
)
def test_auto_render_features_skip_native_probe(
    monkeypatch: pytest.MonkeyPatch, field: str, value,
) -> None:
    monkeypatch.setattr(smart_scrape_api, "validate_public_http_url", lambda target: target)
    body = {
        "url": "https://example.com/app",
        "mode": "auto",
        "formats": ["markdown"],
    }
    body[field] = value
    capability, _arguments, product = smart_scrape_api._normalize_scrape(body)
    assert capability == "web.scrape.rendered"
    assert product["execution_mode"] == "rendered"


def test_http_only_rejects_rendered_output_before_execution(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(smart_scrape_api, "validate_public_http_url", lambda target: target)
    with pytest.raises(HTTPException) as caught:
        smart_scrape_api._normalize_scrape(
            {
                "url": "https://example.com",
                "mode": "http",
                "formats": ["screenshot"],
            }
        )
    assert caught.value.status_code == 422
    assert caught.value.detail["code"] == "render_required"


def test_scrape_normalizer_hides_provider_shape_and_preserves_outputs() -> None:
    document = smart_scrape_api._normalize_document(
        {
            "markdown": "# Pricing\n[Plans](https://example.com/pricing)",
            "html": "<main><h1>Pricing</h1></main>",
            "links": [
                "https://example.com/pricing",
                {"url": "https://example.com/docs"},
                "javascript:alert(1)",
            ],
            "screenshot": {"url": "https://cdn.example.com/shot.png"},
            "metadata": {
                "title": "Pricing",
                "description": "Plans",
                "sourceURL": "https://example.com/pricing",
                "statusCode": 200,
                "contentType": "text/html",
            },
            "providerInternalField": "must-not-leak",
        },
        requested_url="https://example.com/pricing",
        route="rendered",
    )
    assert document["title"] == "Pricing"
    assert document["text"] == "Pricing Plans"
    assert document["markdown"] == "# Pricing\n[Plans](https://example.com/pricing)"
    assert document["links"] == [
        "https://example.com/pricing",
        "https://example.com/docs",
    ]
    assert document["screenshot"] == "https://cdn.example.com/shot.png"
    assert document["execution_path"] == "rendered"
    assert "providerInternalField" not in document


def test_scrape_saved_payload_is_dataset_compatible() -> None:
    document = {
        "url": "https://example.com",
        "title": "Example",
        "text": "Readable body",
        "markdown": "# Example",
        "links": ["https://example.com/docs"],
        "execution_path": "http",
    }
    rows = result_rows({"pages": [document], "execution_path": "http"})
    assert len(rows) == 1
    assert rows[0]["record_type"] == "pages"
    assert rows[0]["execution_path"] == "http"


def test_smart_scrape_reserves_fallback_headroom_but_settles_native_work() -> None:
    smart_args = {
        "capability": "web.scrape.smart",
        "arguments": {
            "url": "https://example.com",
            "formats": ["markdown", "links"],
        },
    }
    http_args = {
        "capability": "web.scrape.http",
        "arguments": {
            "url": "https://example.com",
            "formats": ["markdown", "links"],
        },
    }
    smart = estimate_call("mesh_capability_execute", smart_args, "free")
    http_only = estimate_call("mesh_capability_execute", http_args, "free")
    assert smart.allowed and http_only.allowed
    assert smart.credits > http_only.credits

    charged = settle_measured_cost(
        "mesh_capability_execute",
        smart_args,
        "free",
        reserved_credits=smart.credits,
        execution_usage={
            "completed": True,
            "provider_calls": {"nativeweb": 1},
            "counters": {"native_web_requests": 1},
        },
    )
    assert 0 < charged < smart.credits


def test_smart_scrape_routes_console_and_mount_are_registered() -> None:
    paths = {route.path for route in smart_scrape_api.router.routes if hasattr(route, "path")}
    assert "/api/scrape/quote" in paths
    assert "/api/scrape/run" in paths

    root = Path(__file__).resolve().parents[1]
    saas = (root / "src" / "internet_hands" / "saas_app.py").read_text(encoding="utf-8")
    assert "from .smart_scrape_api import router as smart_scrape_router" in saas
    assert "app.include_router(smart_scrape_router)" in saas

    web = (root / "web" / "app.js").read_text(encoding="utf-8")
    assert "scrape:dashSmartScrape" in web
    assert "['scrape','scan','Smart Scrape']" in web
    assert "/api/scrape/quote" in web
    assert "/api/scrape/run" in web
    assert "Confirm and scrape page" in web


def test_smart_scrape_is_exposed_in_product_docs() -> None:
    import json

    root = Path(__file__).resolve().parents[1]
    raw = (root / "web" / "docs-content.js").read_text(encoding="utf-8").strip()
    prefix = "window.OPENCRAWL_DOCS = "
    assert raw.startswith(prefix) and raw.endswith(";")
    docs = json.loads(raw[len(prefix):-1])
    title, group, body = docs["smart-scrape"]
    assert title == "Smart Scrape"
    assert group == "Collect and use data"
    assert len(body) >= 1500
    assert "/api/scrape/quote" in body
    assert "/api/scrape/run" in body
    assert "HTTP only" in body
    assert "quote_revision" in body
    assert "dataset.saved" in body
