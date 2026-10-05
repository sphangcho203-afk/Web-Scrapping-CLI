from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
APP = (ROOT / "web" / "app.js").read_text(encoding="utf-8")
CSS = (ROOT / "web" / "cognitive-foundation.css").read_text(encoding="utf-8")


def test_capability_workbench_has_global_page_headline_helper() -> None:
    assert "const pageHeadline =" in APP
    start = APP.index("async function dashCapabilities()")
    end = APP.index("/* === Extended authenticated surfaces", start)
    capability_source = APP[start:end]
    assert "pageHeadline('WEB CAPABILITIES'" in capability_source
    assert "headline('WEB CAPABILITIES'" not in capability_source


def test_connected_apps_use_provider_logos_end_to_end() -> None:
    assert "const safeProviderLogo =" in APP
    assert "const connectedAppMark =" in APP
    assert "data-provider-logo" in APP
    assert "connectedAppMark(appItem)" in APP
    assert "connectedAppMark(configured)" in APP
    assert ".connected-app-mark img" in CSS
    assert ".connected-app-logo-fallback" in CSS


def test_connected_app_catalog_is_not_letter_avatar_only() -> None:
    old_catalog_avatar = (
        '<span class="connected-app-mark">'
        "+esc((item.name||toolkit||'?').slice(0,1).toUpperCase())+"
    )
    assert old_catalog_avatar not in APP
    assert "connected-catalog-intro" in APP
    assert "connected-catalog-state" in APP


def test_client_setup_uses_canonical_mcp_endpoint_and_brand_marks() -> None:
    assert "const endpoint='https://opencrawl.top/mcp';" in APP
    assert "platformMark('openai','OpenAI')" in APP
    assert "platformMark('anthropic','Anthropic')" in APP
    assert "platformMark('mcp','MCP')" in APP
    assert ".agent-tab-mark" in CSS


def test_browser_runtime_does_not_treat_query_selector_as_a_collection() -> None:
    unsafe_patterns = [
        "$('[data-provider-logo]',root).forEach",
        "$('[data-copy]').forEach",
        "$('.docs-group a').forEach",
        "$('.docs-group').forEach",
        "$('[data-cap-field]',fields).forEach",
    ]
    for pattern in unsafe_patterns:
        assert pattern not in APP
