from pathlib import Path


def test_account_trigger_has_touch_safe_native_popover() -> None:
    app = Path("web/app.js").read_text(encoding="utf-8")
    assert 'data-account-toggle popovertarget="ih-account-menu"' in app
    assert 'data-account-menu popover="auto"' in app
    assert "addEventListener('pointerup'" in app
    assert "aria-expanded" in app
    assert 'type="button" data-account-toggle' in app


def test_account_trigger_sits_above_mobile_backdrop() -> None:
    css = Path("web/cognitive-foundation.css").read_text(encoding="utf-8")
    assert "Account trigger reliability v5" in css
    assert "z-index:121!important" in css
    assert "pointer-events:auto!important" in css
