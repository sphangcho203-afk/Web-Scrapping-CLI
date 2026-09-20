from pathlib import Path


def test_account_menu_uses_native_popover() -> None:
    app = Path("web/app.js").read_text(encoding="utf-8")
    assert 'popovertarget="ih-account-menu"' in app
    assert 'id="ih-account-menu" data-account-menu popover="auto"' in app
    assert "nativeAccountPopover" in app
    assert "addEventListener('toggle'" in app


def test_native_popover_uses_top_layer_visibility_rules() -> None:
    css = Path("web/cognitive-foundation.css").read_text(encoding="utf-8")
    assert "Native account popover v6" in css
    assert ".cos-account-menu[popover]:not(:popover-open)" in css
    assert ".cos-account-menu[popover]:popover-open" in css
    assert ".cos-account-menu[popover]::backdrop" in css
