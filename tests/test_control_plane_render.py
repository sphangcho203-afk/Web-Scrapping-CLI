"""Run the shipped runtime in Chromium against nullable API response fixtures."""
import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlsplit

import pytest

from internet_hands.site import WEB_ROOT, _browser_runtime

playwright = pytest.importorskip("playwright.sync_api")


@pytest.mark.parametrize("statuses,label", [([None], "CRAWL FAILED"), ([403], "CRAWL FAILED"), ([200, 503], "CRAWL PARTIAL"), ([200], "CRAWL COMPLETE")])
def test_crawl_outcome_labels_match_successful_pages(frontend_url, statuses, label):
    with playwright.sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_page(viewport={"width": 390, "height": 800})
        def respond(route):
            path = urlsplit(route.request.url).path
            if path == "/api/auth/me":
                data = {"user": {"email": "owner@test.invalid", "email_verified": True}, "account": {}}
            elif path == "/api/api-keys":
                data = {"keys": [{"id": "key_fixture", "name": "Collection", "prefix": "oc"}]}
            elif path == "/api/playground/run":
                data = {"ok": 200 in statuses, "operation": "crawl", "usage": {}, "summary": {},
                        "result": {"pages": [{"url": "https://example.com/", "status_code": code,
                            "error": "PolicyError: outside scope" if code is None else None} for code in statuses]}}
            else:
                data = {}
            route.fulfill(status=200, content_type="application/json", body=json.dumps(data))
        page.route("**/api/**", respond)
        page.goto(frontend_url + "/dashboard/playground")
        page.locator("#research-query").fill("https://example.com/")
        page.locator("#ihp-submit").click()
        page.locator("#ihp-results .search-result-header .search-section-kicker").wait_for()
        assert page.locator("#ihp-results .search-result-header .search-section-kicker").inner_text() == label
        assert "successful" in page.locator("#ihp-results .search-result-header p").inner_text()
        browser.close()


def test_content_monitor_billing_form_and_capture_history(frontend_url):
    submitted = []
    monitor = {"id": "mon_content", "name": "Price watch", "type": "content", "target": "https://example.com/pricing",
               "config": {"api_key_id": "key_fixture"}, "enabled": True, "interval_minutes": 60, "last_status": "changed"}
    with playwright.sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_page(viewport={"width": 390, "height": 800})
        errors = []
        page.on("pageerror", lambda error: errors.append(str(error)))
        def respond(route):
            path = urlsplit(route.request.url).path
            if path == "/api/auth/me":
                data = {"user": {"email": "owner@test.invalid", "email_verified": True}, "account": {}}
            elif path == "/api/api-keys":
                data = {"keys": [{"id": "key_fixture", "name": "Monitoring", "prefix": "oc"}]}
            elif path == "/api/monitors/validate":
                submitted.append(route.request.post_data_json)
                data = {"valid": True, "monitor": route.request.post_data_json}
            elif path == "/api/monitors" and route.request.method == "POST":
                data = monitor
            elif path == "/api/monitors":
                data = {"monitors": [monitor]}
            elif path == "/api/monitors/mon_content":
                data = monitor
            elif path.endswith("/history"):
                data = {"runs": [{"status": "changed", "credits_charged": 3, "dataset_id": "ds_new",
                                  "diff": {"previous_dataset_id": "ds_old"}, "summary": '<img src=x onerror="window.injected=true">'}]}
            else:
                data = {}
            route.fulfill(status=200, content_type="application/json", body=json.dumps(data))
        page.route("**/api/**", respond)
        page.goto(frontend_url + "/dashboard/monitors")
        page.locator('[data-monitor-template="content"]').click()
        page.locator('input[name="name"]').fill("Price watch")
        page.locator('input[name="target"]').fill(monitor["target"])
        page.locator('select[name="api_key_id"]').select_option("key_fixture")
        assert page.locator("#monitor-content-billing").is_visible()
        page.get_by_role("button", name="Validate and create").click()
        page.get_by_text("Monitor created", exact=True).wait_for()
        assert submitted[0]["type"] == "content" and submitted[0]["config"] == {"api_key_id": "key_fixture"}
        page.locator(".monitor-row").click()
        page.get_by_role("link", name="Open capture").wait_for()
        assert page.get_by_role("link", name="Open capture").get_attribute("href") == "/dashboard/datasets?dataset=ds_new"
        assert page.get_by_role("link", name="Previous capture").get_attribute("href") == "/dashboard/datasets?dataset=ds_old"
        assert page.locator(".monitor-history-table img").count() == 0
        assert page.evaluate("window.injected === undefined")
        for width in (320, 390, 1366):
            page.set_viewport_size({"width": width, "height": 800})
            assert page.evaluate("document.documentElement.scrollWidth <= innerWidth"), width
        assert not errors
        browser.close()


def test_background_crawl_submission_reopen_and_cancel(frontend_url):
    run = {"id": "run_fixture", "url": "https://example.com/<unsafe>", "status": "queued",
           "attempts": 0, "progress": {"pages": 0, "discovered_urls": 0},
           "credits_reserved": 100, "credits_charged": 0}
    submissions = []
    with playwright.sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_page(viewport={"width": 390, "height": 800})
        errors = []
        page.on("pageerror", lambda error: errors.append(str(error)))

        def respond(route):
            path = urlsplit(route.request.url).path
            if path == "/api/auth/me":
                data = {"user": {"email": "owner@test.invalid", "email_verified": True}, "account": {}}
            elif path == "/api/api-keys":
                data = {"keys": [{"id": "key_fixture", "name": "Collection", "prefix": "oc"}]}
            elif path == "/api/dashboard":
                data = {"account": {"monthly_credits": 10000}}
            elif path == "/api/crawl-runs" and route.request.method == "POST":
                submissions.append((route.request.post_data_json, route.request.headers.get("idempotency-key")))
                data = {"run": run}
            elif path.endswith("/cancel"):
                run["status"] = "cancelled"
                data = {"run": run}
            elif path == "/api/crawl-runs/run_fixture":
                data = {"run": run}
            else:
                data = {}
            route.fulfill(status=200, content_type="application/json", body=json.dumps(data))

        page.route("**/api/**", respond)
        page.goto(frontend_url + "/dashboard/playground")
        page.locator("#research-query").fill("https://example.com/")
        page.get_by_text("Background URL crawl", exact=True).click()
        assert page.locator("#ihp-background").is_checked()
        page.locator("#ihp-submit").click()
        page.get_by_role("heading", name="Collection progress", exact=True).wait_for()
        assert submissions[0][0]["url"] == "https://example.com/" and submissions[0][1]
        assert page.locator("unsafe").count() == 0
        for width in (320, 390, 1366):
            page.set_viewport_size({"width": width, "height": 800})
            assert page.evaluate("document.documentElement.scrollWidth <= innerWidth"), width
        page.reload()
        page.locator("#crawl-run-cancel").click()
        page.get_by_role("status").filter(has_text="cancelled").wait_for()
        assert not errors
        browser.close()


def test_saved_dataset_browser_controls_and_exports(frontend_url):
    dataset = {"id": "ds_fixture", "name": "Collected sources", "operation": "search",
               "row_count": 1, "columns": ["url", "title"], "request_id": "req_fixture"}
    deleted = False
    with playwright.sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_page(viewport={"width": 390, "height": 800})
        errors = []
        page.on("pageerror", lambda error: errors.append(str(error)))

        def respond(route):
            nonlocal deleted
            url, method = route.request.url, route.request.method
            if "/api/auth/me" in url:
                data = {"user": {"email": "owner@test.invalid", "email_verified": True}, "account": {}}
            elif "/export?format=csv" in url:
                route.fulfill(status=200, content_type="text/csv", body="title,url\nSource,https://example.com\n")
                return
            elif method == "PATCH":
                dataset["name"] = route.request.post_data_json["name"]
                data = {"dataset": dataset}
            elif method == "DELETE":
                deleted = True
                data = {"deleted": True}
            elif "/api/datasets/ds_fixture" in url:
                data = {"dataset": dataset, "rows": [{"url": "https://example.com", "title": "Source"}], "total": 1}
            elif "/api/datasets" in url:
                data = {"datasets": [] if deleted else [dataset], "total": 0 if deleted else 1}
            else:
                data = {}
            route.fulfill(status=200, content_type="application/json", body=json.dumps(data))

        page.route("**/api/**", respond)
        page.goto(frontend_url + "/dashboard/datasets")
        page.get_by_role("link", name="Collected sources", exact=True).click()
        page.locator("#dataset-rename").wait_for()
        for width in (320, 390, 1366):
            page.set_viewport_size({"width": width, "height": 800})
            assert page.evaluate("document.documentElement.scrollWidth <= innerWidth"), width
        page.locator('#dataset-rename input').fill("Renamed output")
        page.locator('#dataset-rename button').click()
        page.get_by_role("heading", name="Renamed output", exact=True).wait_for()
        with page.expect_download() as download:
            page.get_by_role("button", name="Download CSV", exact=True).click()
        assert download.value.suggested_filename == "ds_fixture.csv"
        page.on("dialog", lambda dialog: dialog.accept())
        page.get_by_role("button", name="Delete dataset", exact=True).click()
        page.get_by_text("No saved outputs yet", exact=True).wait_for()
        assert deleted and not errors
        browser.close()


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
                content_type = ({
                    ".css": "text/css",
                    ".js": "application/javascript",
                    ".png": "image/png",
                    ".webp": "image/webp",
                    ".svg": "image/svg+xml",
                }.get(asset.suffix, "application/octet-stream"))
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


def test_opencrawl_mark_and_wordmark_at_phone_and_desktop_widths(frontend_url):
    with playwright.sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_page(viewport={"width": 320, "height": 740})
        page.route("**/api/**", lambda route: route.fulfill(
            status=401, content_type="application/json", body='{"detail":"sign in required"}'
        ))
        for path in ("/", "/login"):
            page.goto(frontend_url + path)
            mark = page.locator(".oc-brand-mark").first
            mark.wait_for()
            assert page.get_by_role("link", name="OpenCrawl home").count() >= 1
            assert mark.evaluate("image => image.complete && image.naturalWidth > 0")
            assert mark.get_attribute("src") == "/assets/opencrawl-crab.png"
            for width in (320, 390, 768, 1366):
                page.set_viewport_size({"width": width, "height": 740})
                assert page.evaluate("document.documentElement.scrollWidth <= innerWidth"), (path, width)
                if path == "/" and width == 390:
                    header = page.locator(".ih-site-header").bounding_box()
                    kicker = page.locator(".oc-hero-kicker").bounding_box()
                    assert header and kicker and kicker["y"] - (header["y"] + header["height"]) < 100
        browser.close()


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
            "/dashboard/rewards": ".ih-route-rewards",
            "/dashboard/billing": ".ih-route-billing",
            "/dashboard/settings": ".ih-route-settings",
            "/dashboard/integrations": ".ih-route-connections",
            "/docs/clients": ".docs-article",
            "/docs/two-factor": ".docs-article",
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
                data = {"request_id": "req_rank", "ref": tool["ref"],
                        "result": {"ranks": [1], "source_url": "https://example.test/ranks",
                                   "captured_at": "2026-09-26T00:00:00Z"},
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
        assert "openapi" not in page.locator(".game-capabilities").inner_text()
        page.locator('[data-game-discover="mlbb.reference.rank"]').click()
        page.locator("#game-discovered-form").wait_for()
        assert page.locator("#game-operation").input_value() == "0"
        assert "/rank" not in page.locator("#game-operation").inner_text()
        fields = page.locator("[data-game-arg]")
        fields.nth(0).select_option("false")
        fields.nth(1).fill('{"tier":"gold"}')
        fields.nth(2).fill('["NA"]')
        fields.nth(3).fill("12")
        fields.nth(4).select_option(label="historical")
        page.locator("#game-discovered-form button[type=submit]").click()
        page.get_by_text("req_rank").wait_for()
        assert not page.locator(".game-tool-output .game-operation-trace p").is_visible()
        page.get_by_text("Source evidence").click()
        assert page.locator(".game-tool-output .game-operation-trace a").get_attribute("href") == "https://example.test/ranks"
        assert "openapi" not in page.locator(".game-tool-output .game-operation-trace").inner_text()
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
            elif path == "/api/repos/inspect":
                calls.append(route.request.post_data_json)
                data = {"request_id": "req_inspect", "result": {"repository": "sample/game-api",
                        "api_specs": [{"path": "openapi.json", "url": "https://github.com/sample/game-api/blob/main/openapi.json",
                                       "parsed": True, "endpoints": [{"method": "GET", "path": "/heroes"}],
                                       "operations": [{"method": "GET", "path": "/heroes", "name": "List heroes",
                                                       "inputs": ["region"], "requires_auth": False}],
                                       "oauth_scopes": []}], "candidate_files": []},
                        "usage": {"credits_charged": 3, "github_api_calls": 3}}
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
        page.locator("#repo-query").fill("sample/game-api")
        page.locator("#repo-submit").click()
        page.get_by_text("req_inspect").wait_for()
        assert page.locator(".repo-operations article").count() == 1
        assert "List heroes" in page.locator(".repo-operations").inner_text()
        assert "Discovery only" in page.locator(".repo-operations").inner_text()
        assert calls[1] == {"repository": "sample/game-api", "api_key_id": "key_fixture"}
        assert page.evaluate("document.documentElement.scrollWidth <= innerWidth")
        assert not errors, errors
        browser.close()


def test_usage_leads_with_workflows_and_retains_technical_trace(frontend_url):
    run = {"request_id": "req_fixture", "tool_ref": "openapi:rank", "capability": "mlbb.reference.rank",
           "provider": "openapi", "status": "ok", "credits_charged": 2, "latency_ms": 100,
           "created_at": "2026-09-25T12:00:00Z", "input_bytes": 50, "output_bytes": 80}
    with playwright.sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_page(viewport={"width": 320, "height": 740})
        errors = []
        page.on("pageerror", lambda error: errors.append(str(error)))

        def respond(route):
            path = urlsplit(route.request.url).path
            if path == "/api/auth/me":
                data = {"user": {"email": "fixture@example.test", "email_verified": True}, "account": {}}
            elif path == "/api/usage/intelligence":
                data = {"totals": {"requests": 1, "credits": 2}, "account": {}, "series": [],
                        "breakdowns": {"tool": [{"name": "openapi:rank", "requests": 1,
                                                 "credits": 2, "avg_latency_ms": 100}],
                                       "status": [], "provider": [{"name": "openapi", "requests": 1}]},
                        "recent_runs": [run], "recent_failures": []}
            elif path == "/api/usage/runs/req_fixture":
                data = {"run": run}
            else:
                data = {}
            route.fulfill(status=200, content_type="application/json", body=json.dumps(data))

        page.route("**/api/**", respond)
        page.goto(frontend_url + "/dashboard/usage")
        page.locator(".ih-run-table-row").wait_for()
        assert "Game intelligence" in page.locator(".ih-run-table-row").inner_text()
        assert "openapi" not in page.locator(".ih-run-table-wrap").inner_text()
        page.locator(".ih-run-table-row").click()
        page.locator(".ih-run-modal").wait_for()
        assert "Game intelligence" in page.locator(".ih-inspector-grid").inner_text()
        page.get_by_text("Technical routing and provenance").click()
        assert "openapi:rank" in page.locator(".ih-run-diagnostics").inner_text()
        assert page.evaluate("document.documentElement.scrollWidth <= innerWidth")
        assert not errors, errors
        browser.close()


def test_expanded_catalog_paginates_and_searches_at_narrow_widths(frontend_url):
    games = [{"game_id": f"game-{index}", "name": f"Public Game {index:03}",
              "capability_count": 3, "provider_ready_count": 3, "capabilities": []} for index in range(132)]
    with playwright.sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_page(viewport={"width": 320, "height": 800})
        errors = []
        page.on("pageerror", lambda error: errors.append(str(error)))
        def respond(route):
            path = urlsplit(route.request.url).path
            if path == "/api/auth/me":
                data = {"user": {"email": "fixture@example.test", "email_verified": True}, "account": {}}
            elif path == "/api/games":
                data = {"games": games}
            elif path.startswith("/api/games/"):
                data = {"game": next(game for game in games if game["game_id"] == path.rsplit("/", 1)[-1])}
            else:
                data = {"keys": []}
            route.fulfill(status=200, content_type="application/json", body=json.dumps(data))
        page.route("**/api/**", respond)
        page.goto(frontend_url + "/dashboard/games")
        page.locator('[data-game="game-0"][aria-pressed="true"]').wait_for()
        assert page.locator(".game-tile").count() == 24
        page.locator("[data-game-next]").click()
        assert page.locator('[data-game="game-24"]').count() == 1
        page.locator("#game-search").fill("Public Game 131")
        assert page.locator(".game-tile").count() == 1
        page.locator('[data-game="game-131"]').click()
        page.locator("#game-detail h2").get_by_text("Public Game 131").wait_for()
        for width in [320, 360, 390, 430, 768, 1024, 1280, 1366, 1440, 1920]:
            page.set_viewport_size({"width": width, "height": 900})
            assert page.evaluate("document.documentElement.scrollWidth <= innerWidth"), width
        assert not errors
        browser.close()


def test_public_data_workspace_validates_executes_and_reports_partial_results(frontend_url):
    calls = []
    with playwright.sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_page(viewport={"width": 320, "height": 800})
        errors = []
        page.on("pageerror", lambda error: errors.append(str(error)))
        def respond(route):
            path = urlsplit(route.request.url).path
            if path == "/api/auth/me":
                data = {"user": {"email": "fixture@example.test", "email_verified": True}, "account": {}}
            elif path == "/api/api-keys":
                data = {"keys": [{"id": "key_fixture", "name": "Research key", "scopes": []}]}
            elif path.startswith("/api/public-data/"):
                calls.append(route.request.post_data_json)
                if path.endswith("/search"):
                    data = {"request_id": "req_search", "usage": {"credits_charged": 8},
                            "result": {"results": [{"url": "https://doi.org/10.1234/test",
                            "title": "Public agent research", "snippet": "Publication evidence",
                            "sources": ["openalex", "crossref"]}], "errors": [], "partial": False}}
                else:
                    data = {"request_id": "req_public", "usage": {"credits_charged": 8},
                            "result": {"partial": True, "evidence": [{"source_url": "https://source.example/report",
                            "title": "Public report", "captured_at": "2026-09-26T00:00:00Z", "snippets": ["A won by three points."]}],
                            "errors": [{"code": "robots_disallowed"}]}}
            else:
                data = {}
            route.fulfill(status=200, content_type="application/json", body=json.dumps(data))
        page.route("**/api/**", respond)
        page.goto(frontend_url + "/dashboard/data")
        form = page.locator("#public-data-form")
        form.wait_for()
        form.locator('[name="operation"]').select_option("research")
        form.locator('[name="urls"]').fill("file:///etc/passwd")
        form.locator('button[type="submit"]').click()
        assert not calls
        form.locator('[name="urls"]').fill("https://source.example/report")
        form.locator('[name="query"]').fill("scores")
        form.locator('button[type="submit"]').click()
        page.get_by_text("Partial evidence collected", exact=True).wait_for()
        assert len(calls) == 1 and calls[0]["arguments"]["max_pages"] == 5
        assert calls[0]["api_key_id"] == "key_fixture"
        assert "$0.0016 charged" in page.locator("#public-data-output").inner_text()
        assert page.get_by_role("link", name="Open source", exact=True).get_attribute("href") == "https://source.example/report"
        form.locator('[name="operation"]').select_option("extract")
        assert not page.locator("#public-data-research-fields").is_visible()
        assert "$0.0010" in page.locator("#public-data-budget").inner_text()
        form.locator('[name="operation"]').select_option("search")
        assert not page.locator("#public-data-urls-field").is_visible()
        form.locator('[name="search_query"]').fill("agent research")
        form.locator('button[type="submit"]').click()
        page.get_by_role("link", name="Open source", exact=True).wait_for()
        assert calls[-1]["arguments"] == {"query": "agent research", "sources": ["wikipedia", "openalex", "crossref"], "limit": 5}
        assert "Publication evidence" in page.locator("#public-data-output").inner_text()
        for width in [320, 360, 390, 430, 768, 1024, 1366, 1440, 1920]:
            page.set_viewport_size({"width": width, "height": 900})
            assert page.evaluate("document.documentElement.scrollWidth <= innerWidth"), width
        assert not errors
        browser.close()



def test_rewards_redemption_delivers_wallet_prize(frontend_url):
    state = {
        "points": 120,
        "purchased": 500,
        "redemptions": [],
    }
    with playwright.sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_page(viewport={"width": 390, "height": 844})
        errors = []
        page.on("pageerror", lambda error: errors.append(str(error)))
        page.on("dialog", lambda dialog: dialog.accept())

        def rewards_payload():
            return {
                "account": {
                    "points": state["points"],
                    "lifetime_earned": 120,
                    "lifetime_redeemed": 120 - state["points"],
                },
                "wallet": {
                    "monthly_credits": 250,
                    "purchased_credits": state["purchased"],
                    "reserved_credits": 0,
                },
                "catalog": [{
                    "slug": "wallet-025",
                    "name": "$0.25 wallet credit",
                    "description": "Add rollover OpenCrawl balance to your wallet.",
                    "points_cost": 100,
                    "fulfillment_type": "wallet_credit",
                    "fulfillment_value": 1250,
                }],
                "redemptions": list(state["redemptions"]),
                "ledger": [],
                "earned_now": 0,
                "wallet_units_per_usd": 5000,
                "earning_rule": {"usd_spend_per_point": 0.05},
            }

        def respond(route):
            path = urlsplit(route.request.url).path
            if path == "/api/auth/me":
                data = {
                    "user": {"email": "fixture@example.test", "email_verified": True},
                    "account": {},
                }
            elif path == "/api/rewards" and route.request.method == "GET":
                data = rewards_payload()
            elif path == "/api/rewards/wallet-025/redeem" and route.request.method == "POST":
                idempotency_key = route.request.headers.get("idempotency-key")
                assert idempotency_key and idempotency_key.startswith("rwd-")
                assert state["points"] >= 100
                state["points"] -= 100
                state["purchased"] += 1250
                redemption = {
                    "id": "rwd_fixture",
                    "reward_slug": "wallet-025",
                    "reward_name": "$0.25 wallet credit",
                    "points_spent": 100,
                    "status": "fulfilled",
                    "fulfillment_type": "wallet_credit",
                    "fulfillment_value": 1250,
                    "created_at": "2026-09-28T10:00:00Z",
                    "fulfilled_at": "2026-09-28T10:00:00Z",
                }
                state["redemptions"].insert(0, redemption)
                data = {
                    "ok": True,
                    "redemption": redemption,
                    "account": {"points": state["points"]},
                    "wallet": {"purchased_credits": state["purchased"]},
                    "wallet_units_per_usd": 5000,
                }
            else:
                data = {}
            route.fulfill(status=200, content_type="application/json", body=json.dumps(data))

        page.route("**/api/**", respond)
        page.goto(frontend_url + "/dashboard/rewards")
        page.locator(".ih-route-rewards").wait_for()
        assert page.get_by_text("120", exact=True).count() >= 1
        page.get_by_role("button", name="Redeem prize").click()
        page.get_by_text("Prize redeemed and delivered to your wallet").wait_for()
        page.get_by_text("20", exact=True).first.wait_for()
        assert page.get_by_text("$0.25 wallet credit", exact=True).count() >= 1
        assert state["purchased"] == 1750
        assert state["points"] == 20
        assert not errors, errors
        browser.close()



def test_community_reward_code_redemption(frontend_url):
    state = {
        "points": 120,
        "purchased": 500,
        "code_redemptions": [],
    }
    with playwright.sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_page(viewport={"width": 390, "height": 844})
        errors = []
        page.on("pageerror", lambda error: errors.append(str(error)))

        def rewards_payload():
            return {
                "account": {
                    "points": state["points"],
                    "lifetime_earned": state["points"],
                    "lifetime_redeemed": 0,
                },
                "wallet": {
                    "monthly_credits": 250,
                    "purchased_credits": state["purchased"],
                    "reserved_credits": 0,
                },
                "catalog": [],
                "redemptions": [],
                "code_redemptions": list(state["code_redemptions"]),
                "ledger": [],
                "earned_now": 0,
                "wallet_units_per_usd": 5000,
                "earning_rule": {"usd_spend_per_point": 0.05},
            }

        def respond(route):
            path = urlsplit(route.request.url).path
            if path == "/api/auth/me":
                data = {
                    "user": {"email": "fixture@example.test", "email_verified": True},
                    "account": {},
                }
            elif path == "/api/rewards" and route.request.method == "GET":
                data = rewards_payload()
            elif path == "/api/rewards/codes/redeem" and route.request.method == "POST":
                body = route.request.post_data_json
                assert body["code"] == "DISCORD100"
                state["points"] += 100
                state["code_redemptions"].insert(0, {
                    "id": "rcd_fixture",
                    "code_hint": "DISC…",
                    "label": "Discord launch drop",
                    "reward_type": "points",
                    "reward_value": 100,
                    "created_at": "2026-09-28T18:30:00Z",
                })
                data = {
                    "ok": True,
                    "campaign": {
                        "label": "Discord launch drop",
                        "code_hint": "DISC…",
                        "reward_type": "points",
                        "reward_value": 100,
                    },
                    "account": {"points": state["points"]},
                    "wallet": {"purchased_credits": state["purchased"]},
                    "wallet_units_per_usd": 5000,
                }
            else:
                data = {}
            route.fulfill(status=200, content_type="application/json", body=json.dumps(data))

        page.route("**/api/**", respond)
        page.goto(frontend_url + "/dashboard/rewards")
        page.locator("#reward-code-form").wait_for()
        page.locator('#reward-code-form input[name="code"]').fill("discord100")
        page.get_by_role("button", name="Redeem code").click()
        page.get_by_text("220", exact=True).first.wait_for()
        assert page.get_by_text("Discord launch drop", exact=True).count() >= 1
        assert page.get_by_text("+100 pts", exact=True).count() >= 1
        assert not errors, errors
        browser.close()


def test_playground_crawl_text_is_escaped_and_truncation_visible(frontend_url):
    with playwright.sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_page(viewport={"width": 390, "height": 800})
        errors = []
        page.on("pageerror", lambda error: errors.append(str(error)))

        def respond(route):
            path = urlsplit(route.request.url).path
            if path == "/api/auth/me":
                data = {"user": {"email": "owner@test.invalid", "email_verified": True}, "account": {}}
            elif path == "/api/api-keys":
                data = {"keys": [{"id": "key_fixture", "name": "Test key", "prefix": "ih_test"}]}
            elif path == "/api/playground/run":
                data = {"ok": True, "operation": "crawl", "request_id": "req_fixture",
                        "usage": {}, "summary": {"pages": 1, "successful": 1, "content_truncated": True},
                        "dataset": {"id": "ds_fixture"},
                        "result": {"pages": [{"url": "https://example.com", "title": "API guide",
                            "status_code": 200, "text": '<img src=x onerror="window.injected=true">' + 'X' * 400,
                            "content_truncated": True}], "search_results": [], "evidence": []}}
            else:
                data = {}
            route.fulfill(status=200, content_type="application/json", body=json.dumps(data))

        page.route("**/api/**", respond)
        page.goto(frontend_url + "/dashboard/playground")
        page.locator("#research-query").fill("https://example.com")
        page.get_by_role("button", name="Run search", exact=True).click()
        page.get_by_text("Content was shortened to fit the collection limits.", exact=True).wait_for()
        page.get_by_text("Read page text", exact=True).click()
        assert '<img src=x onerror="window.injected=true">' in page.locator(".crawl-content pre").inner_text()
        assert page.locator(".crawl-content img").count() == 0
        assert page.evaluate("window.injected === undefined")
        for width in (320, 390, 1366):
            page.set_viewport_size({"width": width, "height": 800})
            assert page.evaluate("document.documentElement.scrollWidth <= innerWidth"), width
        assert not errors
        browser.close()


def test_dataset_webhook_setup_secret_pause_and_retry_controls(frontend_url):
    endpoint = None
    deliveries = [{"id": "wh_fixture", "dataset_id": "ds_fixture", "status": "failed", "attempts": 5,
                   "last_error": '<img src=x onerror="window.injected=true">'}]
    with playwright.sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_page(viewport={"width": 390, "height": 800})
        errors = []
        page.on("pageerror", lambda error: errors.append(str(error)))

        def respond(route):
            nonlocal endpoint, deliveries
            path, method = urlsplit(route.request.url).path, route.request.method
            if path == "/api/auth/me":
                data = {"user": {"email": "owner@test.invalid", "email_verified": True}, "account": {}}
            elif path == "/api/dataset-webhook" and method == "PUT":
                body = route.request.post_data_json
                created = endpoint is None
                endpoint = {"url": body["url"], "enabled": body["enabled"]}
                data = {"endpoint": endpoint}
                if created or body["rotate_secret"]:
                    data["signing_secret"] = "whsec_" + "x" * 43
            elif path == "/api/dataset-webhook" and method == "DELETE":
                endpoint, deliveries = None, []
                data = {"deleted": True}
            elif path == "/api/dataset-webhook":
                data = {"available": True, "endpoint": endpoint}
            elif path.endswith("/retry"):
                deliveries[0]["status"] = "pending"
                data = {"delivery": deliveries[0]}
            elif path == "/api/dataset-webhook/deliveries":
                data = {"deliveries": deliveries, "total": len(deliveries)}
            else:
                data = {"datasets": [], "total": 0}
            route.fulfill(status=200, content_type="application/json", body=json.dumps(data))

        page.route("**/api/**", respond)
        page.goto(frontend_url + "/dashboard/datasets")
        page.get_by_role("link", name="Webhook delivery", exact=True).click()
        page.get_by_label("Receiver URL", exact=True).fill("https://hooks.example.com/receive")
        page.get_by_role("button", name="Save webhook", exact=True).click()
        page.get_by_text("Save your signing secret", exact=True).wait_for()
        assert page.locator("#dataset-webhook-secret code").inner_text() == "whsec_" + "x" * 43
        assert page.locator(".table-wrap img").count() == 0
        for width in (320, 390, 1366):
            page.set_viewport_size({"width": width, "height": 800})
            assert page.evaluate("document.documentElement.scrollWidth <= innerWidth"), width
        page.get_by_label("Enable delivery", exact=True).uncheck()
        page.get_by_role("button", name="Save webhook", exact=True).click()
        page.wait_for_function("document.querySelector('#dataset-webhook-secret').hidden")
        assert page.get_by_role("button", name="Retry delivery", exact=True).is_disabled()
        page.get_by_label("Enable delivery", exact=True).check()
        page.get_by_role("button", name="Save webhook", exact=True).click()
        page.wait_for_function("!document.querySelector('[data-webhook-retry]').disabled")
        page.get_by_role("button", name="Retry delivery", exact=True).click()
        page.get_by_role("cell", name="pending", exact=True).wait_for()
        page.on("dialog", lambda dialog: dialog.accept())
        page.get_by_role("button", name="Remove webhook", exact=True).click()
        page.get_by_text("No deliveries yet", exact=True).wait_for()
        page.goto(frontend_url + "/docs/dataset-webhooks")
        page.get_by_role("heading", name="Dataset webhooks", exact=True).wait_for()
        assert not errors
        browser.close()
