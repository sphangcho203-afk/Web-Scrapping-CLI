from __future__ import annotations

import inspect
from pathlib import Path

from internet_hands.crawler import crawl
from internet_hands.playground_api import router as playground_router


def test_playground_api_is_registered() -> None:
    paths = {str(getattr(route, "path", "") or "") for route in playground_router.routes}
    assert "/api/playground/run" in paths


def test_crawler_exposes_bounded_controls() -> None:
    params = inspect.signature(crawl).parameters
    for name in (
        "max_pages",
        "max_depth",
        "concurrency",
        "max_seconds",
        "include_paths",
        "exclude_paths",
        "include_subdomains",
        "preserve_query",
    ):
        assert name in params


def test_playground_usage_is_priced_and_registered() -> None:
    store = Path("src/internet_hands/control_store.py").read_text(encoding="utf-8")
    saas = Path("src/internet_hands/saas_app.py").read_text(encoding="utf-8")
    assert '("playground:crawl", 2' in store
    assert "app.include_router(playground_router)" in saas


def test_playground_dashboard_surface() -> None:
    app = Path("web/app.js").read_text(encoding="utf-8")
    assert "/dashboard/playground" in app
    assert "Create API key" in app
    assert "/api/playground/run" in app
    assert "Run metered crawl" in app


def test_playground_uses_normal_account_api_keys() -> None:
    app = Path("web/app.js").read_text(encoding="utf-8")
    store = Path("src/internet_hands/control_store.py").read_text(encoding="utf-8")
    api = Path("src/internet_hands/playground_api.py").read_text(encoding="utf-8")
    assert "Playground test key" not in app
    assert 'href="/dashboard/api-keys"' in app
    assert "api_key_id" in app
    assert "api_key_identity_for_user" in store
    assert "_require_user" in api
