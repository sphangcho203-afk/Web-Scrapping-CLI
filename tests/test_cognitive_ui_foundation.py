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


def test_overview_migration_is_loaded_served_and_scoped() -> None:
    index = (WEB / "index.html").read_text(encoding="utf-8")
    site = SITE.read_text(encoding="utf-8")
    overview = (WEB / "cognitive-overview.js").read_text(encoding="utf-8")

    assert '<script src="/assets/cognitive-overview.js" defer></script>' in index
    assert '"cognitive-overview.js": "application/javascript"' in site
    assert "location.pathname === '/dashboard'" in overview
    assert "location.pathname === '/dashboard/'" in overview
    assert "content.dataset.ihOverview === '1'" in overview
    assert "content.classList.add('ih-page-shell', 'ih-overview')" in overview
    assert "head.classList.add('ih-page-header')" in overview
    assert "stats.classList.add('ih-grid', 'ih-grid--4'" in overview
    assert "dashboard.classList.add('ih-grid', 'ih-grid--2'" in overview
    assert "card.classList.add('ih-panel'" in overview
