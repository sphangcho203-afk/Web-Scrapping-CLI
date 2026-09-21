from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
WEB = ROOT / "web"
SITE = ROOT / "src" / "internet_hands" / "site.py"


def test_usage_intelligence_ui_uses_canonical_read_model() -> None:
    ui = (WEB / "usage-intelligence.js").read_text(encoding="utf-8")

    assert "/api/usage/intelligence?window=" in ui
    assert "['24h','7d','30d','90d']" in ui
    assert "t.success_rate==null?'—'" in ui
    assert "data.breakdowns" in ui
    assert "data.recent_failures" in ui
    assert "openRunInspector" in ui


def test_usage_feature_is_composed_into_single_shipped_runtime() -> None:
    index = (WEB / "index.html").read_text(encoding="utf-8")
    site = SITE.read_text(encoding="utf-8")

    assert index.count('<script src="/assets/') == 1
    assert '<script src="/assets/app.js' in index
    assert 'runtime = WEB_ROOT / "app.js"' in site
    assert 'usage = WEB_ROOT / "usage-intelligence.js"' in site
    assert "sources = [legal, runtime, usage, monitors]" in site
    assert '"\\n\\n".join(source.read_text(encoding="utf-8") for source in sources)' in site
    assert '"usage-intelligence.js":' not in site


def test_usage_ui_does_not_recalculate_metering_from_raw_events() -> None:
    ui = (WEB / "usage-intelligence.js").read_text(encoding="utf-8")

    assert "/api/usage?limit=" not in ui
    assert ".reduce((s,x)=>" not in ui
    assert "events.filter" not in ui
