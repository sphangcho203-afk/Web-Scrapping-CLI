"""Run the shipped runtime in Chromium against nullable API response fixtures."""
import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlsplit

import pytest

from internet_hands.site import WEB_ROOT, _browser_runtime

playwright = pytest.importorskip("playwright.sync_api")


@pytest.fixture(scope="module")
def frontend_url():
    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            path = urlsplit(self.path).path
            if path == "/assets/app.js":
                body = _browser_runtime().body
                content_type = "application/javascript"
            elif path.startswith("/assets/"):
                asset = WEB_ROOT / path.rsplit("/", 1)[-1]
                body = asset.read_bytes()
                content_type = "text/css" if asset.suffix == ".css" else "image/svg+xml"
            else:
                body = (WEB_ROOT / "index.html").read_bytes()
                content_type = "text/html"
            self.send_response(200)
            self.send_header("Content-Type", content_type)
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, *_args):
            pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    yield f"http://127.0.0.1:{server.server_port}"
    server.shutdown()
    server.server_close()
    thread.join()


@pytest.mark.parametrize("mode", ["null", "missing", "empty", "populated"])
def test_initial_control_plane_render(frontend_url, mode):
    fields = ["plans", "credit_packs", "series", "events", "recent_runs",
              "recent_failures", "keys", "monitors", "ledger", "payments", "sessions"]
    value = None if mode == "null" else []
    payload = {} if mode == "missing" else dict.fromkeys(fields, value)
    payload["breakdowns"] = None if mode == "null" else {
        "status": value, "tool": value, "provider": value,
    }
    if mode == "populated":
        payload["recent_runs"] = [{"request_id": "fixture-run", "tool_ref": "Fixture tool",
                                   "status": "ok", "credits_charged": 3}]
        payload["keys"] = [{"id": "fixture-key", "name": "Fixture key", "scopes": None}]

    with playwright.sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_page()
        errors = []
        page.on("pageerror", lambda error: errors.append(str(error)))
        page.on("console", lambda message: errors.append(message.text)
                if message.type == "error" else None)

        def respond(route):
            assert route.request.method == "GET", "Rendering must not mutate account state"
            data = ({"user": {"email": "fixture@example.test", "email_verified": True},
                     "account": {}} if "/api/auth/me" in route.request.url else payload)
            route.fulfill(status=200, content_type="application/json", body=json.dumps(data))

        page.route("**/api/**", respond)
        routes = {
            "/": "h1", "/pricing": "h1", "/login": "#auth-form",
            "/dashboard": ".ih-route-overview",
            "/dashboard/usage": ".ih-route-usage",
            "/dashboard/api-keys": ".ih-route-api-keys",
            "/dashboard/monitors": ".ih-route-monitors",
            "/dashboard/wallet": ".ih-route-wallet",
            "/dashboard/billing": ".ih-route-billing",
            "/dashboard/settings": ".ih-route-settings",
            "/dashboard/integrations": ".ih-route-connections",
        }
        for route, selector in routes.items():
            page.goto(frontend_url + route)
            try:
                page.locator(selector).first.wait_for(timeout=5000)
            except playwright.TimeoutError:
                pytest.fail(f"{route}: {errors}; {page.locator('body').inner_text()}")
            assert page.locator(".fatal").count() == 0, route
            assert not errors, (route, errors)
            assert page.locator('script[src^="/assets/"]').count() == 1
            assert page.locator('link[rel="stylesheet"]').count() == 1
            if mode == "populated" and route == "/dashboard":
                assert page.get_by_text("Fixture tool", exact=True).count() == 1
            if mode == "populated" and route == "/dashboard/api-keys":
                assert page.get_by_text("Fixture key", exact=True).count() == 1
        browser.close()


def test_monitor_history_and_responsive_layout(frontend_url):
    monitor = {
        "id": "mon_fixture", "name": "Docs health", "type": "web",
        "target": "https://example.com/long/path/to/health-check", "enabled": True,
        "interval_minutes": 60, "last_status": "healthy",
        "last_checked_at": "2026-09-25T12:00:00Z",
        "next_check_at": "2026-09-25T13:00:00Z",
    }
    run = {"created_at": "2026-09-25T12:00:00Z", "status": "healthy",
           "http_status": 200, "latency_ms": 83, "summary": "HTTP 200"}
    older = {**run, "created_at": "2026-09-24T12:00:00Z", "summary": "Older check"}

    with playwright.sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_page(viewport={"width": 1366, "height": 800})
        errors = []
        page.on("pageerror", lambda error: errors.append(str(error)))

        def respond(route):
            path = urlsplit(route.request.url).path
            if path == "/api/auth/me":
                data = {"user": {"email": "fixture@example.test", "email_verified": True},
                        "account": {}}
            elif path == "/api/monitors":
                data = {"monitors": [monitor]}
            elif path == "/api/monitors/mon_fixture":
                data = monitor
            elif path == "/api/monitors/mon_fixture/history":
                data = ({"runs": [older], "has_more": False, "next_before": None}
                        if "before=" in route.request.url else
                        {"runs": [run], "has_more": True,
                         "next_before": "2026-09-25T12:00:00Z"})
            else:
                data = {}
            route.fulfill(status=200, content_type="application/json", body=json.dumps(data))

        page.route("**/api/**", respond)
        page.goto(frontend_url + "/dashboard/monitors")
        page.locator(".monitor-row").wait_for()
        assert page.locator(".monitor-row .badge.success").count() == 1
        assert page.locator(".stats-grid .stat-card").nth(1).locator("b").inner_text() == "1"
        assert page.locator('[data-monitor-template="gaming"]').count() == 0
        for width in (320, 360, 390, 430, 768, 900, 1024, 1366, 1440, 1920):
            page.set_viewport_size({"width": width, "height": 800})
            assert page.evaluate("document.documentElement.scrollWidth <= innerWidth"), width

        page.set_viewport_size({"width": 320, "height": 700})
        page.locator(".monitor-row").click()
        page.locator(".monitor-history-table tbody tr").wait_for()
        page.get_by_role("button", name="Load older checks").click()
        page.locator(".monitor-history-table tbody tr").nth(1).wait_for()
        assert page.locator(".monitor-history-table tbody tr").count() == 2
        assert page.get_by_role("button", name="Load older checks").count() == 0
        bounds = page.locator(".modal").bounding_box()
        assert bounds and bounds["x"] >= 0 and bounds["x"] + bounds["width"] <= 320
        page.locator(".modal").press("Escape")
        page.get_by_role("button", name="New monitor").click()
        assert page.locator('input[name="target"]').get_attribute("type") == "url"
        page.locator('select[name="type"]').select_option("mcp")
        assert "MCP endpoint" in page.locator("#monitor-target-hint").inner_text()
        assert not errors, errors
        browser.close()


def test_curl_connection_preview_then_save(frontend_url):
    saved = []
    with playwright.sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_page(viewport={"width": 390, "height": 844})
        errors = []
        page.on("pageerror", lambda error: errors.append(str(error)))

        def respond(route):
            path = urlsplit(route.request.url).path
            if path == "/api/auth/me":
                data = {"user": {"email": "fixture@example.test", "email_verified": True},
                        "account": {}}
            elif path == "/api/connections" and route.request.method == "GET":
                data = {"connections": saved}
            elif path == "/api/connections/import-curl":
                body = route.request.post_data_json
                assert body["command"].startswith("curl ")
                if body.get("save"):
                    saved.append({"id": "con_fixture", "name": "Provider",
                                  "endpoint_url": "https://example.com/mcp",
                                  "transport": "streamable_http", "auth_type": "bearer",
                                  "header_names": ["Authorization"]})
                    data = {"connection": saved[-1], "saved": True}
                else:
                    data = {"connection": {"name": "Provider", "url": "https://example.com/mcp",
                                           "auth_type": "bearer", "header_names": ["Authorization"]}}
            else:
                data = {}
            route.fulfill(status=200, content_type="application/json", body=json.dumps(data))

        page.route("**/api/**", respond)
        page.goto(frontend_url + "/dashboard/connections")
        page.locator("#mcp-curl").click()
        page.locator('#curl-form input[name="name"]').fill("Provider")
        page.locator('#curl-form textarea[name="command"]').fill(
            "curl https://example.com/mcp -H 'Authorization: Bearer fixture-access-token'"
        )
        page.get_by_role("button", name="Preview import").click()
        page.locator("#curl-save").wait_for()
        assert "fixture-access-token" not in page.locator("#curl-result").inner_text()
        page.locator("#curl-save").click()
        page.locator(".mcp-row").wait_for()
        assert len(saved) == 1
        assert "Provider" in page.locator(".mcp-row").inner_text()
        assert page.evaluate("document.documentElement.scrollWidth <= innerWidth")
        assert not errors, errors
        browser.close()


def test_game_discovery_schema_execution_and_mobile_state(frontend_url):
    calls = []
    remote = {"id": "mlbb.reference.rank", "name": "Rank reference", "description": "Public rank data",
              "providers": ["openapi"], "provider_ready": True, "availability": "ready"}
    local = {"id": "game.matches.analyze", "name": "Match analysis", "description": "Analyze matches",
             "providers": ["gamecore"], "provider_ready": True, "availability": "ready"}
    game = {"game_id": "mlbb", "name": "Mobile Legends", "capability_count": 2,
            "provider_ready_count": 2, "capabilities": [remote, local]}
    tool = {"ref": "openapi:rank", "name": "Public rank", "provider": "openapi",
            "description": "Published rankings", "metadata": {"method": "GET", "path": "/rank"},
            "input_schema": {"required": ["enabled", "filters"], "properties": {
                "enabled": {"type": "boolean"}, "filters": {"type": "object"},
                "regions": {"type": "array"}, "limit": {"type": "integer", "minimum": 1, "maximum": 100},
                "mode": {"type": "string", "enum": ["current", "historical"]},
            }}}

    with playwright.sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_page(viewport={"width": 320, "height": 740})
        errors = []
        page.on("pageerror", lambda error: errors.append(str(error)))

        def respond(route):
            path = urlsplit(route.request.url).path
            if path == "/api/auth/me":
                data = {"user": {"email": "fixture@example.test", "email_verified": True}, "account": {}}
            elif path == "/api/api-keys":
                data = {"keys": [{"id": "key_fixture", "name": "Test key", "prefix": "ih_test", "scopes": []}]}
            elif path == "/api/games":
                data = {"games": [game]}
            elif path == "/api/games/mlbb":
                data = {"game": game}
            elif path.endswith("/tools/mlbb.reference.rank") and route.request.method == "GET":
                data = {"tools": [tool]}
            elif path.endswith("/tools/mlbb.reference.rank"):
                calls.append(route.request.post_data_json)
                data = {"request_id": "req_rank", "ref": tool["ref"], "result": {"ranks": [1]},
                        "usage": {"credits_charged": 1}}
            elif path.endswith("/tools/game.matches.analyze"):
                calls.append(route.request.post_data_json)
                data = {"request_id": "req_match", "result": {"overall": {"games": 1, "win_rate": 100,
                        "kda": 3}, "recent_10": {"win_rate": 100}, "current_streak": {"games": 1,
                        "outcome": "win"}}, "usage": {"credits_charged": 1}}
            else:
                data = {}
            route.fulfill(status=200, content_type="application/json", body=json.dumps(data))

        page.route("**/api/**", respond)
        page.goto(frontend_url + "/dashboard/games")
        page.locator('[data-game="mlbb"][aria-pressed="true"]').wait_for()
        page.locator('[data-game-discover="mlbb.reference.rank"]').click()
        page.locator("#game-discovered-form").wait_for()
        fields = page.locator("[data-game-arg]")
        fields.nth(0).select_option("false")
        fields.nth(1).fill('{"tier":"gold"}')
        fields.nth(2).fill('["NA"]')
        fields.nth(3).fill("12")
        fields.nth(4).select_option(label="historical")
        page.locator("#game-discovered-form button[type=submit]").click()
        page.get_by_text("req_rank").wait_for()
        assert calls[0]["arguments"] == {"enabled": False, "filters": {"tier": "gold"},
                                          "regions": ["NA"], "limit": 12, "mode": "historical"}
        assert calls[0]["api_key_id"] == "key_fixture"
        fields.nth(1).fill("[]")
        page.locator("#game-discovered-form button[type=submit]").click()
        assert "JSON object" in page.locator("#game-discovered-output").inner_text()
        assert len(calls) == 1

        page.locator('[data-game-tool="game.matches.analyze"]').click()
        page.locator('#game-tool-form textarea[name="match_results"]').fill('{}')
        page.locator("#game-tool-form button[type=submit]").click()
        assert "JSON array" in page.locator("#game-tool-output").inner_text()
        assert len(calls) == 1
        page.locator('#game-tool-form textarea[name="match_results"]').fill('[{"win":true}]')
        page.locator("#game-tool-form button[type=submit]").click()
        page.get_by_text("req_match").wait_for()
        assert calls[1]["arguments"]["matches"] == [{"win": True}]
        assert page.evaluate("document.documentElement.scrollWidth <= innerWidth")
        assert not errors, errors
        browser.close()


def test_repository_investigation_blocks_duplicate_metered_requests(frontend_url):
    calls = []
    with playwright.sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_page(viewport={"width": 360, "height": 740})
        errors = []
        page.on("pageerror", lambda error: errors.append(str(error)))

        def respond(route):
            path = urlsplit(route.request.url).path
            if path == "/api/auth/me":
                data = {"user": {"email": "fixture@example.test", "email_verified": True}, "account": {}}
            elif path == "/api/api-keys":
                data = {"keys": [{"id": "key_fixture", "name": "Test key", "prefix": "ih_test", "scopes": []}]}
            elif path == "/api/repos/search":
                calls.append(route.request.post_data_json)
                data = {"request_id": "req_search", "result": {"repositories": []},
                        "usage": {"credits_charged": 2, "github_api_calls": 1}}
            else:
                data = {}
            route.fulfill(status=200, content_type="application/json", body=json.dumps(data))

        page.route("**/api/**", respond)
        page.goto(frontend_url + "/dashboard/repositories")
        page.locator("#repo-query").fill("public game api")
        page.evaluate("""() => {
            const form = document.querySelector('#repo-form');
            form.requestSubmit(); form.dispatchEvent(new Event('submit', {bubbles:true, cancelable:true}));
            document.querySelector('[data-repo-example]').click();
        }""")
        page.get_by_text("req_search").wait_for()
        assert calls == [{"query": "public game api", "api_key_id": "key_fixture"}]
        assert page.evaluate("document.documentElement.scrollWidth <= innerWidth")
        assert not errors, errors
        browser.close()
