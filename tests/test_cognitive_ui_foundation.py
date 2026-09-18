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
    app = (WEB / "app.js").read_text(encoding="utf-8")

    assert "cos-sidebar ih-sidebar" in app
    assert "cos-workspace ih-workspace" in app
    assert "cos-topbar ih-topbar" in app
