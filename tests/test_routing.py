from internet_hands import routing
from internet_hands.routing import BackendIntent, route_backend


def test_static_route_always_has_native_http():
    plan = route_backend(BackendIntent.STATIC)
    assert plan["selected"] == "native-http"
    assert plan["candidates"][0]["state"] == "native"


def test_dynamic_route_prefers_native_playwright_when_installed(monkeypatch):
    monkeypatch.setattr(
        routing,
        "module_available",
        lambda name: name == "playwright",
    )
    plan = route_backend(BackendIntent.DYNAMIC)
    assert plan["selected"] == "native-playwright"
    assert plan["candidates"][0]["runtime_ready"] is True


def test_article_route_can_select_trafilatura(monkeypatch):
    monkeypatch.setattr(
        routing,
        "module_available",
        lambda name: name == "trafilatura",
    )
    plan = route_backend(BackendIntent.ARTICLE)
    assert plan["selected"] == "trafilatura"
