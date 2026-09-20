from pathlib import Path


def test_route_navigation_clears_overlay_lock() -> None:
    app = Path("web/app.js").read_text(encoding="utf-8")
    assert "function clearTransientUi()" in app
    assert "async function renderRoute(){clearTransientUi();" in app
    assert "window.addEventListener('pageshow',clearTransientUi)" in app


def test_mobile_backdrop_consumes_pointer_before_underlay() -> None:
    app = Path("web/app.js").read_text(encoding="utf-8")
    assert "consumeOverlayPointer" in app
    assert "addEventListener('pointerdown', consumeOverlayPointer)" in app
    assert "e.stopPropagation();" in app


def test_overlay_pointer_events_are_explicit() -> None:
    css = Path("web/cognitive-foundation.css").read_text(encoding="utf-8")
    assert "Interaction hardening v3" in css
    assert ".cos-sheet-backdrop{pointer-events:none!important}" in css
    assert ".cos-sheet-backdrop.open{pointer-events:auto!important}" in css


def test_settings_mobile_header_can_wrap_status() -> None:
    css = Path("web/cognitive-foundation.css").read_text(encoding="utf-8")
    assert ".ih-route-settings" in css
    assert "flex-wrap:wrap!important" in css
