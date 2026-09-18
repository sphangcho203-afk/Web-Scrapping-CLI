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
    # command-os.js is the runtime owner of the authenticated shell. app.js still
    # contains the compatibility renderer while routes are migrated incrementally.
    shell = (WEB / "command-os.js").read_text(encoding="utf-8")

    assert "cos-sidebar ih-sidebar sidebar" in shell
    assert "cos-workspace workspace ih-workspace" in shell
    assert "cos-topbar topbar ih-topbar" in shell
    assert "cos-mobile-bottom ih-mobile-bottom mobile-bottom" in shell


def test_authenticated_routes_share_cognitive_page_contract() -> None:
    app = (WEB / "app.js").read_text(encoding="utf-8")
    shell = (WEB / "command-os.js").read_text(encoding="utf-8")

    assert 'page-head ih-page-header' in app
    assert 'ih-page-heading' in app
    assert 'ih-page-actions' in app
    assert 'stat-card ih-panel ih-metric-card' in app
    assert 'ih-metric-label' in app
    assert 'ih-metric-value' in app
    assert 'ih-page-shell ih-route-' in shell
    assert 'data-dashboard-route=' in shell


def test_navigation_matches_product_information_architecture() -> None:
    shell = (WEB / "command-os.js").read_text(encoding="utf-8")

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
