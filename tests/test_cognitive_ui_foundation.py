from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
WEB = ROOT / "web"
SITE = ROOT / "src" / "internet_hands" / "site.py"


def test_cognitive_foundation_is_loaded_and_served() -> None:
    index = (WEB / "index.html").read_text(encoding="utf-8")
    site = SITE.read_text(encoding="utf-8")

    assert '<link rel="stylesheet" href="/assets/cognitive-foundation.css">' in index
    assert '"cognitive-foundation.css": "text/css"' in site


def test_cognitive_foundation_exposes_canonical_page_primitives() -> None:
    css = (WEB / "cognitive-foundation.css").read_text(encoding="utf-8")

    required_contracts = (
        ".ih-page-shell",
        ".ih-page-header",
        ".ih-page-heading",
        ".ih-page-actions",
        ".ih-page-meta",
        ".ih-grid",
        ".ih-panel",
        ".ih-status",
        ".ih-metric-value",
        ".ih-metric-label",
    )

    for selector in required_contracts:
        assert selector in css, f"missing canonical Cognitive UI contract: {selector}"


def test_authenticated_shell_uses_cognitive_contract() -> None:
    runtime = (WEB / "app.js").read_text(encoding="utf-8")

    assert "cos-sidebar ih-sidebar sidebar" in runtime
    assert "cos-workspace workspace ih-workspace" in runtime
    assert "cos-topbar topbar ih-topbar" in runtime
    assert "cos-mobile-bottom ih-mobile-bottom mobile-bottom" in runtime


def test_authenticated_routes_share_cognitive_page_contract() -> None:
    app = (WEB / "app.js").read_text(encoding="utf-8")
    shell = app

    assert 'page-head ih-page-header' in app
    assert 'ih-page-heading' in app
    assert 'ih-page-actions' in app
    assert 'stat-card ih-panel ih-metric-card' in app
    assert 'ih-metric-label' in app
    assert 'ih-metric-value' in app
    assert 'ih-page-shell ih-route-' in shell
    assert 'data-dashboard-route=' in shell


def test_navigation_matches_product_information_architecture() -> None:
    shell = (WEB / "app.js").read_text(encoding="utf-8")

    for group in ("Build", "Observe", "Connect", "Account"):
        assert f"['{group}', [" in shell

    assert "['Operate', [" not in shell
    assert "['Manage', [" not in shell


def test_foundation_removes_known_fake_controls_and_scores() -> None:
    app = (WEB / "app.js").read_text(encoding="utf-8")

    assert "<option>Last 30 days</option>" not in app
    assert "SECURITY SCORE" not in app
    assert "<small>/100</small>" not in app
    assert "['Web page','HTTP / content','web']" in app
    assert "['API endpoint','JSON / status','api']" in app
    assert "['MCP endpoint','Streamable HTTP','mcp']" in app
    assert "['Gaming identity','Public profile','gaming']" in app


def test_overview_compatibility_layer_is_retired() -> None:
    index = (WEB / "index.html").read_text(encoding="utf-8")
    site = SITE.read_text(encoding="utf-8")

    assert "cognitive-overview.js" not in index
    assert "cognitive-overview.js" not in site


def test_polish_and_brand_override_layers_are_retired() -> None:
    index = (WEB / "index.html").read_text(encoding="utf-8")
    site = SITE.read_text(encoding="utf-8")
    foundation = (WEB / "cognitive-foundation.css").read_text(encoding="utf-8")
    runtime = (WEB / "app.js").read_text(encoding="utf-8")

    for retired in (
        "command-os-polish.css",
        "command-os-polish.js",
        "brand-logo.css",
        "brand-logo.js",
    ):
        assert retired not in index
        assert retired not in site

    assert "Merged public polish + exact brand identity" in foundation
    assert 'ih-brand ih-logo-only' in runtime
    assert 'cos-brand ih-logo-only' in runtime


def test_public_mobile_navigation_owns_its_accessibility_state() -> None:
    app = (WEB / "app.js").read_text(encoding="utf-8")

    assert "aria-controls" in app
    assert "aria-expanded" in app
    assert "syncNavState" in app


def test_frontend_is_shipped_as_one_runtime_and_one_stylesheet() -> None:
    index = (WEB / "index.html").read_text(encoding="utf-8")
    site = SITE.read_text(encoding="utf-8")
    runtime = (WEB / "app.js").read_text(encoding="utf-8")
    stylesheet = (WEB / "cognitive-foundation.css").read_text(encoding="utf-8")

    retired_assets = (
        "app.css",
        "product-ui.css",
        "product-ui-extended.css",
        "command-os.css",
        "product-ui.js",
        "product-ui-extended.js",
        "command-os.js",
    )
    for retired in retired_assets:
        assert f'/assets/{retired}' not in index
        assert f'"{retired}":' not in site

    assert index.count('<link rel="stylesheet"') == 1
    assert index.count('<script src="/assets/') == 1
    assert "Internet Hands unified browser runtime" in runtime
    assert "Internet Hands unified Cognitive UI stylesheet" in stylesheet
    assert "Product experience" in runtime
    assert "Command workspace shell" in runtime


def test_retired_frontend_asset_files_are_absent() -> None:
    for retired in (
        "app.css",
        "product-ui.css",
        "product-ui-extended.css",
        "command-os.css",
        "product-ui.js",
        "product-ui-extended.js",
        "command-os.js",
    ):
        assert not (WEB / retired).exists(), f"retired frontend layer still exists: {retired}"


def test_unshipped_legacy_frontend_artifacts_are_removed() -> None:
    site = SITE.read_text(encoding="utf-8")
    legacy = (
        "editorial-ui.css",
        "editorial-fixes.css",
        "editorial-ui.js",
        "legacy-controls.js",
        "security.js",
        "recovery.js",
        "auth-nav.js",
    )

    for name in legacy:
        assert f'"{name}":' not in site
        assert not (WEB / name).exists(), f"dead unshipped frontend artifact remains: {name}"


def test_common_bindings_tolerate_missing_copy_controls():
    """Public/dashboard shells may legitimately render without copy controls."""
    app_js = (ROOT / "web" / "app.js").read_text(encoding="utf-8")
    assert "$$('[data-copy]').forEach" in app_js
    assert "$('[data-copy]').forEach" not in app_js
