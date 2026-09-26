from pathlib import Path


def test_authenticated_shell_uses_canonical_labels_and_routes() -> None:
    app = Path("web/app.js").read_text(encoding="utf-8")
    usage = Path("web/usage-intelligence.js").read_text(encoding="utf-8")
    assert "['overview','terminal','Overview']" in app
    assert "['connections','plug','Connections']" in app
    assert "['billing','billing','Billing & Plans']" in app
    assert "['settings','settings','Settings & Security']" in app
    assert "dashboardShell('connections'" in app
    assert 'data-link href="/dashboard/playground"' in app
    assert "go('/dashboard/playground')" in usage


def test_mobile_shell_has_single_overlay_controller() -> None:
    app = Path("web/app.js").read_text(encoding="utf-8")
    assert "const closeOverlays = " in app
    assert "ih-overlay-open" in app
    assert "window.__ihShellEscape" in app
    assert "sheet.inert=" in app
    assert "sidebar.inert=" in app


def test_final_shell_css_owns_mobile_spacing() -> None:
    css = Path("web/cognitive-foundation.css").read_text(encoding="utf-8")
    assert "Shell IA + responsive authority v2" in css
    assert ".cos-content.ih-content{width:100%!important;max-width:none!important;margin:0!important;padding:0!important" in css
    assert "width:min(20rem,84vw)!important" in css
    assert "grid-template-columns:repeat(5,minmax(0,1fr))!important" in css
