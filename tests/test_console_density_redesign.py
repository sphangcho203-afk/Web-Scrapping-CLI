from pathlib import Path


def test_playground_uses_compact_progressive_disclosure() -> None:
    app = Path("web/app.js").read_text(encoding="utf-8")
    assert "Advanced crawl settings" in app
    assert "ihp-budgets-primary" in app
    assert "RUN GUARDRAILS" in app
    assert "Select the credential that should own this run" in app


def test_api_key_inventory_uses_compact_meta_summary() -> None:
    app = Path("web/app.js").read_text(encoding="utf-8")
    assert 'class="ih-key-meta"' in app
    assert "Secrets shown once" in app
    assert "One key per client or environment." in app


def test_mobile_console_prevents_key_and_playground_overflow() -> None:
    css = Path("web/cognitive-foundation.css").read_text(encoding="utf-8")
    assert "Console density redesign v7" in css
    assert ".ihp-key{" in css
    assert "grid-template-columns:1fr!important" in css
    assert ".ihx-key-row{" in css
    assert 'grid-template-areas:' in css
    assert ".ihp-key-select select" in css


def test_dashboard_heading_is_no_longer_a_fullscreen_command_hero() -> None:
    app = Path("web/app.js").read_text(encoding="utf-8")
    assert "<span>OVERVIEW</span><h1>Internet Hands</h1>" in app
    assert 'rows="2"' in app
