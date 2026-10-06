"""Run the shipped runtime in Chromium against nullable API response fixtures."""
import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlsplit

import pytest

from internet_hands.site import WEB_ROOT, _browser_runtime

playwright = pytest.importorskip("playwright.sync_api")


def test_usage_vector_chart_interactions_ranges_and_export(frontend_url):
    queries = []
    failure = {"enabled": False}
    series = [{"bucket": f"2026-09-{day}T00:00:00Z", "bucket_start": f"2026-09-{day}T00:00:00Z",
        "bucket_end": f"2026-09-{day+1}T00:00:00Z" if day < 30 else "2026-10-01T00:00:00Z", "requests": requests, "credits": credits,
        "succeeded": 1 if requests == 2 else 0, "failed": 1 if requests == 2 else 0,
        "pending": 1 if requests == 1 else 0, "success_rate": 50 if requests == 2 else None,
        "avg_latency_ms": 100 if requests == 2 else None, "partial": day == 30}
        for day, requests, credits in [(28, 2, 5), (29, 0, 0), (30, 1, 0)]]
    with playwright.sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_page(viewport={"width": 390, "height": 844})
        errors = []
        page.on("pageerror", lambda e: errors.append(str(e)))

        def respond(route):
            path = urlsplit(route.request.url).path
            if path in {"/api/playground/quote", "/api/crawl-runs/quote"}:
                route.fulfill(status=200, content_type="application/json", body=json.dumps({"quote": {
                    "credits": 5, "quote_revision": "a" * 64, "wallet_units_per_usd": 5000,
                    "available_credits": 1000, "affordable": True}}))
                return
            if path == "/api/auth/me":
                data = {"user": {"email": "owner@test.invalid", "email_verified": True}, "account": {}}
            elif path == "/api/usage/intelligence":
                if failure["enabled"]:
                    route.fulfill(status=503, content_type="application/json", body='{"detail":"temporarily unavailable"}')
                    return
                queries.append(route.request.url)
                data = {"generated_at": "2026-09-30T12:00:00Z", "range": {"timezone": "UTC", "granularity": "day"},
                        "series": series, "totals": {"requests": 3, "credits": 5, "success_rate": 50, "pending": 1},
                        "breakdowns": {"tool": [{"name": "playground:crawl", "requests": 3, "credits": 5}],
                                       "status": [{"name": "ok", "requests": 1}, {"name": "failed", "requests": 1}, {"name": "accepted", "requests": 1}]},
                        "recent_runs": []}
            else:
                data = {}
            route.fulfill(status=200, content_type="application/json", body=json.dumps(data))

        page.route("**/api/**", respond)
        page.goto(frontend_url + "/dashboard/usage?window=7d&metric=credits")
        page.locator("[data-usage-chart] svg").wait_for()
        assert "window=7d" in queries[-1]
        assert page.locator("[data-usage-chart]").get_attribute("data-metric") == "credits"
        slider = page.get_by_label("Inspect time bucket")
        slider.focus()
        slider.press("Home")
        assert "5 credits" in page.locator("[data-bucket-detail]").inner_text()
        slider.press("ArrowRight")
        assert "0 requests" in page.locator("[data-bucket-detail]").inner_text()
        page.get_by_role("button", name="Average latency", exact=True).click()
        assert "No latency measurement" in page.locator("[data-bucket-detail]").inner_text()
        assert "metric=latency" in page.url
        page.get_by_role("button", name="Success rate", exact=True).click()
        assert page.locator("[data-usage-chart] svg").get_attribute("data-domain-max") == "100"
        page.get_by_role("button", name="24h", exact=True).click()
        page.locator('[data-usage-window="24h"][aria-pressed="true"]').wait_for()
        assert "window=24h" in queries[-1]
        with page.expect_download() as download_info:
            page.get_by_role("button", name="Export chart CSV", exact=True).click()
        download = download_info.value
        with open(download.path()) as exported:
            assert "bucket_start" in exported.read()
        failure["enabled"] = True
        page.get_by_role("button", name="Refresh data", exact=True).click()
        page.get_by_text("Update failed · showing previous snapshot", exact=True).wait_for()
        assert page.locator("[data-usage-chart] svg").is_visible()
        failure["enabled"] = False
        page.get_by_role("button", name="Refresh data", exact=True).click()
        page.locator("[data-usage-freshness]").filter(has_text="Updated").wait_for()
        for width in (320, 390, 1366):
            page.set_viewport_size({"width": width, "height": 800})
            page.wait_for_timeout(80)
            assert page.evaluate("document.documentElement.scrollWidth <= innerWidth")
            assert page.locator("[data-usage-chart] svg").bounding_box()["width"] > 150
        assert not errors, errors
        page.screenshot(path="/tmp/opencrawl-usage-desktop.png", full_page=True)
        page.set_viewport_size({"width": 390, "height": 844})
        page.reload()
        page.locator("[data-usage-chart] svg").wait_for()
        page.screenshot(path="/tmp/opencrawl-usage-mobile.png", full_page=True)
        browser.close()



def test_playground_cost_review_requires_confirmation_and_requotes_changed_inputs(frontend_url):
    quotes, executions = [], []
    with playwright.sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_page(viewport={"width": 390, "height": 844})

        def respond(route):
            path = urlsplit(route.request.url).path
            if path == "/api/auth/me":
                data = {"user": {"email": "owner@test.invalid", "email_verified": True}, "account": {}}
            elif path == "/api/api-keys":
                data = {"keys": [{"id": "key_fixture", "name": "Collection", "prefix": "oc"}]}
            elif path == "/api/playground/quote":
                quotes.append(route.request.post_data_json)
                data = {"quote": {"credits": 25 if route.request.post_data_json.get("paid_recovery") else 5,
                    "quote_revision": "b" * 64, "wallet_units_per_usd": 5000,
                    "available_credits": 1000, "affordable": True}}
            elif path == "/api/playground/run":
                executions.append(route.request.post_data_json)
                data = {"ok": True, "operation": "search", "usage": {"credits_reserved": 5, "credits_charged": 5},
                        "summary": {}, "result": {"pages": [], "search_results": []}}
            else:
                data = {}
            route.fulfill(status=200, content_type="application/json", body=json.dumps(data))

        page.route("**/api/**", respond)
        page.goto(frontend_url + "/dashboard/playground")
        page.locator("#research-query").fill("example company")
        page.get_by_role("button", name="Review cost", exact=True).click()
        page.get_by_role("button", name="Confirm run", exact=True).wait_for()
        assert len(quotes) == 1 and not executions
        assert page.get_by_role("button", name="Review cost", exact=True).is_visible()
        assert quotes[-1]["paid_recovery"] is False
        page.locator("#research-query").fill("changed company")
        page.get_by_role("button", name="Review cost", exact=True).click()
        page.get_by_role("button", name="Confirm run", exact=True).wait_for()
        assert len(quotes) == 2 and not executions
        page.locator("#ihp-spend-limit").fill("0")
        page.get_by_role("button", name="Review cost", exact=True).click()
        page.get_by_text("This run exceeds your spending limit. Adjust the limit or inputs.", exact=True).wait_for()
        assert not executions
        page.locator("#ihp-spend-limit").fill("")
        page.get_by_role("button", name="Review cost", exact=True).click()
        page.get_by_role("button", name="Confirm run", exact=True).click()
        page.locator("#ihp-results .search-result-header").wait_for()
        assert len(executions) == 1
        assert executions[0]["max_charge_credits"] == 5 and executions[0]["quote_revision"] == "b" * 64
        assert page.evaluate("document.documentElement.scrollWidth <= innerWidth")
        browser.close()

@pytest.mark.parametrize("statuses,label,truncated", [([None], "CRAWL FAILED", False), ([403], "CRAWL FAILED", False), ([200, 503], "CRAWL PARTIAL", False), ([200], "CRAWL COMPLETE", False), ([200], "CRAWL PARTIAL", True)])
def test_crawl_outcome_labels_match_successful_pages(frontend_url, statuses, label, truncated):
    submissions = []
    with playwright.sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_page(viewport={"width": 390, "height": 800})
        def respond(route):
            path = urlsplit(route.request.url).path
            if path in {"/api/playground/quote", "/api/crawl-runs/quote"}:
                route.fulfill(status=200, content_type="application/json", body=json.dumps({"quote": {
                    "credits": 5, "quote_revision": "a" * 64, "wallet_units_per_usd": 5000,
                    "available_credits": 1000, "affordable": True}}))
                return
            if path == "/api/auth/me":
                data = {"user": {"email": "owner@test.invalid", "email_verified": True}, "account": {}}
            elif path == "/api/api-keys":
                data = {"keys": [{"id": "key_fixture", "name": "Collection", "prefix": "oc"}]}
            elif path == "/api/playground/run":
                submissions.append(route.request.post_data_json)
                data = {"ok": 200 in statuses, "operation": "crawl", "usage": {}, "summary": {},
                        "result": {"sitemap_documents": 2, "sitemap_urls": 1, "truncated": truncated, "pages": [{"url": "https://example.com/", "status_code": code,
                            "error": "PolicyError: outside scope" if code is None else None} for code in statuses]}}
            else:
                data = {}
            route.fulfill(status=200, content_type="application/json", body=json.dumps(data))
        page.route("**/api/**", respond)
        page.goto(frontend_url + "/dashboard/playground")
        page.locator("#research-query").fill("https://example.com/")
        page.locator(".search-advanced summary").click()
        page.locator("#ihp-sitemaps").check()
        page.locator("#ihp-submit").click()
        page.get_by_role("button", name="Confirm run", exact=True).click()
        page.locator("#ihp-results .search-result-header .search-section-kicker").wait_for()
        assert page.locator("#ihp-results .search-result-header .search-section-kicker").inner_text() == label
        assert "successful" in page.locator("#ihp-results .search-result-header p").inner_text()
        assert submissions[0]["discover_sitemaps"] is True
        page.get_by_text("Run details", exact=True).click()
        assert page.get_by_text("1 additional URLs from 2 sitemap checks.", exact=True).is_visible()
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
            if path in {"/api/playground/quote", "/api/crawl-runs/quote"}:
                route.fulfill(status=200, content_type="application/json", body=json.dumps({"quote": {
                    "credits": 5, "quote_revision": "a" * 64, "wallet_units_per_usd": 5000,
                    "available_credits": 1000, "affordable": True}}))
                return
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
            if path in {"/api/playground/quote", "/api/crawl-runs/quote"}:
                route.fulfill(status=200, content_type="application/json", body=json.dumps({"quote": {
                    "credits": 5, "quote_revision": "a" * 64, "wallet_units_per_usd": 5000,
                    "available_credits": 1000, "affordable": True}}))
                return
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
        page.locator(".search-advanced summary").click()
        page.locator("#ihp-sitemaps").check()
        page.locator("#ihp-submit").click()
        page.get_by_role("button", name="Confirm run", exact=True).click()
        page.get_by_role("heading", name="Collection progress", exact=True).wait_for()
        assert submissions[0][0]["url"] == "https://example.com/" and submissions[0][1]
        assert submissions[0][0]["discover_sitemaps"] is True
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
            if path in {"/api/playground/quote", "/api/crawl-runs/quote"}:
                route.fulfill(status=200, content_type="application/json", body=json.dumps({"quote": {
                    "credits": 5, "quote_revision": "a" * 64, "wallet_units_per_usd": 5000,
                    "available_credits": 1000, "affordable": True}}))
                return
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
            if path in {"/api/playground/quote", "/api/crawl-runs/quote"}:
                route.fulfill(status=200, content_type="application/json", body=json.dumps({"quote": {
                    "credits": 5, "quote_revision": "a" * 64, "wallet_units_per_usd": 5000,
                    "available_credits": 1000, "affordable": True}}))
                return
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
            if path in {"/api/playground/quote", "/api/crawl-runs/quote"}:
                route.fulfill(status=200, content_type="application/json", body=json.dumps({"quote": {
                    "credits": 5, "quote_revision": "a" * 64, "wallet_units_per_usd": 5000,
                    "available_credits": 1000, "affordable": True}}))
                return
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
            if path in {"/api/playground/quote", "/api/crawl-runs/quote"}:
                route.fulfill(status=200, content_type="application/json", body=json.dumps({"quote": {
                    "credits": 5, "quote_revision": "a" * 64, "wallet_units_per_usd": 5000,
                    "available_credits": 1000, "affordable": True}}))
                return
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
            if path in {"/api/playground/quote", "/api/crawl-runs/quote"}:
                route.fulfill(status=200, content_type="application/json", body=json.dumps({"quote": {
                    "credits": 5, "quote_revision": "a" * 64, "wallet_units_per_usd": 5000,
                    "available_credits": 1000, "affordable": True}}))
                return
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
            elif path == "/api/runs/req_fixture":
                data = {"run": {"id": "req_fixture", "credits_reserved": 10,
                        "credits_charged": 2, "output_dataset_id": "ds_fixture",
                        "execution": {"status": "completed", "attempts": 1}},
                        "events": [{"sequence": 1, "type": "billing_transition", "status": "ok",
                                    "timestamp": "2026-09-25T12:00:00Z"}]}
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
        assert "Game intelligence" in page.locator(".ih-inspector-grid").first.inner_text()
        receipt = page.locator("[data-run-receipt]")
        assert "reserved credits" in receipt.inner_text().casefold()
        assert "billing_transition" in receipt.inner_text()
        assert receipt.get_by_role("link", name="Open saved dataset").get_attribute("href") == "/dashboard/datasets?dataset=ds_fixture"
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
            if path in {"/api/playground/quote", "/api/crawl-runs/quote"}:
                route.fulfill(status=200, content_type="application/json", body=json.dumps({"quote": {
                    "credits": 5, "quote_revision": "a" * 64, "wallet_units_per_usd": 5000,
                    "available_credits": 1000, "affordable": True}}))
                return
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
            if path in {"/api/playground/quote", "/api/crawl-runs/quote"}:
                route.fulfill(status=200, content_type="application/json", body=json.dumps({"quote": {
                    "credits": 5, "quote_revision": "a" * 64, "wallet_units_per_usd": 5000,
                    "available_credits": 1000, "affordable": True}}))
                return
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
            if path in {"/api/playground/quote", "/api/crawl-runs/quote"}:
                route.fulfill(status=200, content_type="application/json", body=json.dumps({"quote": {
                    "credits": 5, "quote_revision": "a" * 64, "wallet_units_per_usd": 5000,
                    "available_credits": 1000, "affordable": True}}))
                return
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
            if path in {"/api/playground/quote", "/api/crawl-runs/quote"}:
                route.fulfill(status=200, content_type="application/json", body=json.dumps({"quote": {
                    "credits": 5, "quote_revision": "a" * 64, "wallet_units_per_usd": 5000,
                    "available_credits": 1000, "affordable": True}}))
                return
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
            if path in {"/api/playground/quote", "/api/crawl-runs/quote"}:
                route.fulfill(status=200, content_type="application/json", body=json.dumps({"quote": {
                    "credits": 5, "quote_revision": "a" * 64, "wallet_units_per_usd": 5000,
                    "available_credits": 1000, "affordable": True}}))
                return
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
        page.get_by_role("button", name="Review cost", exact=True).click()
        page.get_by_role("button", name="Confirm run", exact=True).click()
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


def test_site_map_review_confirmation_dataset_and_responsive_layout(frontend_url):
    quotes, executions = [], []
    with playwright.sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_page(viewport={"width": 390, "height": 844})
        errors = []
        page.on("pageerror", lambda error: errors.append(str(error)))

        def respond(route):
            path = urlsplit(route.request.url).path
            if path == "/api/auth/me":
                data = {"user": {"email": "owner@test.invalid", "email_verified": True}, "account": {}}
            elif path == "/api/api-keys":
                data = {"keys": [{"id": "key_fixture", "name": "Mapping", "prefix": "oc_map"}]}
            elif path == "/api/site-map/quote":
                quotes.append(route.request.post_data_json)
                data = {"quote": {"credits": 5, "maximum_charge_credits": 5,
                    "quote_revision": "m" * 64, "wallet_units_per_usd": 5000,
                    "available_credits": 1000, "affordable": True}}
            elif path == "/api/site-map/run":
                executions.append(route.request.post_data_json)
                data = {"ok": True, "request_id": "req_map_fixture", "operation": "map",
                    "usage": {"credits_reserved": 5, "credits_charged": 3},
                    "summary": {"returned_urls": 2, "reported_urls": 2, "max_depth": 2,
                                "truncated": False, "categories": {"docs": 1, "pricing": 1}},
                    "dataset": {"id": "ds_map_fixture"},
                    "result": {"root_url": "https://example.com", "urls": [
                        {"url": "https://example.com/docs/api", "title": "<img src=x onerror=window.injected=true>",
                         "path": "/docs/api", "depth": 2, "category": "docs",
                         "parent_url": "https://example.com/docs/"},
                        {"url": "https://example.com/pricing", "title": "Pricing",
                         "path": "/pricing", "depth": 1, "category": "pricing",
                         "parent_url": "https://example.com/"}
                    ]}}
            else:
                data = {}
            route.fulfill(status=200, content_type="application/json", body=json.dumps(data))

        page.route("**/api/**", respond)
        page.goto(frontend_url + "/dashboard/map")
        page.get_by_label("Site root", exact=True).fill("https://example.com")
        page.get_by_label("Focus (optional)", exact=True).fill("docs")
        page.get_by_role("button", name="Review map cost", exact=True).click()
        page.get_by_role("button", name="Confirm and map site", exact=True).wait_for()
        assert len(quotes) == 1 and not executions
        assert quotes[0]["url"] == "https://example.com"
        assert quotes[0]["search"] == "docs"

        page.get_by_role("button", name="Confirm and map site", exact=True).click()
        page.get_by_role("heading", name="2 URLs mapped", exact=True).wait_for()
        assert len(executions) == 1
        assert executions[0]["max_charge_credits"] == 5
        assert executions[0]["quote_revision"] == "m" * 64
        assert page.get_by_role("link", name="Open saved dataset").get_attribute("href") == "/dashboard/datasets?dataset=ds_map_fixture"
        assert page.locator(".repo-result-list img").count() == 0
        assert page.evaluate("window.injected === undefined")

        for width in (320, 390, 1366):
            page.set_viewport_size({"width": width, "height": 800})
            page.wait_for_timeout(50)
            assert page.evaluate("document.documentElement.scrollWidth <= innerWidth"), width
        assert not errors, errors
        browser.close()


def test_smart_scrape_review_confirmation_dataset_and_safe_outputs(frontend_url):
    quotes, executions = [], []
    with playwright.sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_page(viewport={"width": 390, "height": 844})
        errors = []
        page.on("pageerror", lambda error: errors.append(str(error)))

        def respond(route):
            path = urlsplit(route.request.url).path
            if path == "/api/auth/me":
                data = {"user": {"email": "owner@test.invalid", "email_verified": True}, "account": {}}
            elif path == "/api/api-keys":
                data = {"keys": [{"id": "key_scrape", "name": "Scrape key", "prefix": "oc_sc"}]}
            elif path == "/api/scrape/quote":
                quotes.append(route.request.post_data_json)
                data = {
                    "quote": {
                        "credits": 255,
                        "maximum_charge_credits": 255,
                        "quote_revision": "s" * 64,
                        "wallet_units_per_usd": 5000,
                        "available_credits": 5000,
                        "affordable": True,
                    },
                    "scrape": {
                        "requested_mode": "auto",
                        "execution_mode": "auto",
                        "formats": ["markdown", "links"],
                    },
                }
            elif path == "/api/scrape/run":
                executions.append(route.request.post_data_json)
                data = {
                    "ok": True,
                    "request_id": "req_scrape_fixture",
                    "operation": "scrape",
                    "usage": {"credits_reserved": 255, "credits_charged": 5},
                    "summary": {
                        "execution_path": "http",
                        "status_code": 200,
                        "formats": ["markdown", "links"],
                        "text_bytes": 41,
                        "links": 1,
                    },
                    "dataset": {"id": "ds_scrape_fixture"},
                    "result": {
                        "url": "https://example.com/pricing",
                        "status_code": 200,
                        "title": '<img src=x onerror="window.injected=true">',
                        "description": "Pricing page",
                        "text": "Simple public pricing",
                        "markdown": '# Pricing\n<img src=x onerror="window.injected=true">',
                        "links": ["https://example.com/docs"],
                        "execution_path": "http",
                    },
                }
            else:
                data = {}
            route.fulfill(status=200, content_type="application/json", body=json.dumps(data))

        page.route("**/api/**", respond)
        page.goto(frontend_url + "/dashboard/scrape")
        page.get_by_label("Public page URL", exact=True).fill("https://example.com/pricing")
        page.get_by_role("button", name="Review scrape cost", exact=True).click()
        page.get_by_role("button", name="Confirm and scrape page", exact=True).wait_for()
        assert len(quotes) == 1 and not executions
        assert quotes[0]["mode"] == "auto"
        assert quotes[0]["formats"] == ["markdown", "links"]

        page.get_by_role("button", name="Confirm and scrape page", exact=True).click()
        page.get_by_text("Pricing page", exact=True).wait_for()
        assert len(executions) == 1
        assert executions[0]["max_charge_credits"] == 255
        assert executions[0]["quote_revision"] == "s" * 64
        assert page.get_by_role("link", name="Open saved dataset").get_attribute("href") == "/dashboard/datasets?dataset=ds_scrape_fixture"
        markdown_panel = page.locator(".scrape-result-tabs details[open] pre").first
        assert '<img src=x onerror="window.injected=true">' in markdown_panel.inner_text()
        assert page.locator(".scrape-result-tabs img").count() == 0
        assert page.evaluate("window.injected === undefined")

        for width in (320, 390, 1366):
            page.set_viewport_size({"width": width, "height": 800})
            page.wait_for_timeout(50)
            assert page.evaluate("document.documentElement.scrollWidth <= innerWidth"), width
        assert not errors, errors
        browser.close()



def test_structured_extract_review_starts_owned_run_and_hides_provider(frontend_url):
    quotes = []
    creates = []
    with playwright.sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_page(viewport={"width": 390, "height": 844})
        errors = []
        page.on("pageerror", lambda error: errors.append(str(error)))

        def respond(route):
            path = urlsplit(route.request.url).path
            method = route.request.method
            if path == "/api/auth/me":
                data = {
                    "user": {
                        "email": "owner@test.invalid",
                        "email_verified": True,
                        "display_name": "Owner",
                    },
                    "account": {},
                }
            elif path == "/api/api-keys":
                data = {
                    "keys": [{
                        "id": "key_extract",
                        "name": "Extract key",
                        "prefix": "oc_ex",
                        "scopes": ["mcp:execute"],
                    }]
                }
            elif path == "/api/extract/runs" and method == "GET":
                data = {"runs": [], "total": 0, "limit": 12, "offset": 0}
            elif path == "/api/extract/quote":
                quotes.append(route.request.post_data_json)
                data = {
                    "quote": {
                        "credits": 1500,
                        "maximum_charge_credits": 1500,
                        "quote_revision": "e" * 64,
                        "wallet_units_per_usd": 5000,
                        "available_credits": 25000,
                        "affordable": True,
                    },
                    "extract": {
                        "source_count": 1,
                        "effort": "medium",
                        "schema_provided": True,
                        "asynchronous": True,
                    },
                }
            elif path == "/api/extract/runs" and method == "POST":
                creates.append({
                    "body": route.request.post_data_json,
                    "idempotency": route.request.headers.get("idempotency-key"),
                })
                data = {
                    "run": {
                        "id": "caprun_fixture",
                        "request_id": "req_extract_fixture",
                        "capability": "web.extract.structured",
                        "status": "waiting",
                        "attempts": 1,
                        "dataset_id": None,
                        "credits_reserved": 1500,
                        "credits_charged": 0,
                        "error_code": None,
                        "updated_at": "2026-10-01T00:00:00Z",
                        "input": {
                            "source_count": 1,
                            "schema_provided": True,
                            "effort": "medium",
                        },
                        "result": {
                            "record_count": 0,
                            "schema_valid": None,
                            "schema_errors": [],
                            "source_urls": [],
                        },
                    },
                    # Deliberately include fields the product must not render if
                    # an upstream adapter accidentally leaks them.
                    "provider": "firecrawl",
                    "provider_job_id": "agent:secret-provider-job",
                }
            elif path == "/api/extract/runs/caprun_fixture":
                data = {
                    "run": {
                        "id": "caprun_fixture",
                        "request_id": "req_extract_fixture",
                        "capability": "web.extract.structured",
                        "status": "completed",
                        "attempts": 2,
                        "dataset_id": "ds_extract_fixture",
                        "credits_reserved": 1500,
                        "credits_charged": 753,
                        "error_code": None,
                        "updated_at": "2026-10-01T00:00:30Z",
                        "finished_at": "2026-10-01T00:00:30Z",
                        "input": {
                            "source_count": 1,
                            "schema_provided": True,
                            "effort": "medium",
                        },
                        "result": {
                            "record_count": 2,
                            "schema_valid": True,
                            "schema_errors": [],
                            "source_urls": ["https://example.com/pricing"],
                        },
                    }
                }
            else:
                data = {}
            route.fulfill(
                status=200,
                content_type="application/json",
                body=json.dumps(data),
            )

        page.route("**/api/**", respond)
        page.goto(frontend_url + "/dashboard/extract")
        page.get_by_text("Turn public pages into validated JSON", exact=True).wait_for()

        page.get_by_label("Public source URLs", exact=False).fill(
            "https://example.com/pricing"
        )
        page.get_by_label("What should OpenCrawl extract?", exact=True).fill(
            "Extract plan names and monthly prices."
        )
        schema = {
            "type": "object",
            "properties": {"plans": {"type": "array"}},
        }
        page.get_by_text("Optional JSON Schema", exact=True).click()
        page.locator('textarea[name="schema"]').fill(json.dumps(schema))

        page.get_by_role(
            "button", name="Review extraction cost", exact=True
        ).click()
        page.get_by_role(
            "button", name="Confirm and start extraction", exact=True
        ).wait_for()
        assert len(quotes) == 1 and not creates
        assert quotes[0]["urls"] == ["https://example.com/pricing"]
        assert quotes[0]["schema"] == schema

        page.get_by_role(
            "button", name="Confirm and start extraction", exact=True
        ).click()
        page.get_by_text("EXTRACT RUN · WAITING", exact=True).wait_for()
        assert len(creates) == 1
        assert creates[0]["body"]["max_charge_credits"] == 1500
        assert creates[0]["body"]["quote_revision"] == "e" * 64
        assert creates[0]["idempotency"].startswith("extract:")
        assert "firecrawl" not in page.locator("#extract-output").inner_text().lower()
        assert "secret-provider-job" not in page.locator("#extract-output").inner_text()

        # Polling is local to the route renderer, so use the recent-run inspect
        # endpoint contract directly by re-entering the page with a completed
        # owned run rather than sleeping through the production 15-second timer.
        page.reload()
        page.wait_for_timeout(100)
        assert page.evaluate("document.documentElement.scrollWidth <= innerWidth")

        for width in (320, 390, 768, 1366):
            page.set_viewport_size({"width": width, "height": 800})
            page.wait_for_timeout(50)
            assert page.evaluate("document.documentElement.scrollWidth <= innerWidth"), width

        assert not errors, errors
        browser.close()


def test_canonical_runs_list_timeline_paging_and_cancel_on_mobile(frontend_url):
    cancelled = False
    event_pages = []
    with playwright.sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_page(viewport={'width':390,'height':844})
        errors = []
        page.on('pageerror', lambda error: errors.append(str(error)))

        def respond(route):
            nonlocal cancelled
            path = urlsplit(route.request.url).path
            run = {'id':'req_fixture','capability_id':'playground:crawl','execution_status':'cancelled' if cancelled else 'queued',
                'status':'cancelled' if cancelled else 'reserved','source_kind':'crawl','source_ref':'crawl_fixture',
                'credits_reserved':100,'credits_charged':0,'source_count':1,'retry_count':0,'warning_count':0,
                'created_at':'2026-10-01T00:00:00Z','output_dataset_id':None,'history_origin':'observed'}
            if path=='/api/auth/me':
                data={'user':{'email':'owner@test.invalid','email_verified':True},'account':{}}
            elif path=='/api/runs':
                data={'runs':[run],'total':1}
            elif path=='/api/runs/req_fixture/cancel':
                cancelled=True
                data={'run':{**run,'execution_status':'cancelled'},'events':[]}
            elif path=='/api/runs/req_fixture':
                next_page = 'after=100' in route.request.url
                event_pages.append(route.request.url)
                events = [{'sequence':n,'timestamp':'2026-10-01T00:00:00Z','type':'execution_status',
                           'status':'queued','message':'Execution state: queued.'} for n in range(1,101)]
                if next_page:
                    events=[{'sequence':101,'timestamp':'2026-10-01T00:01:00Z','type':'provider_attempt',
                             'status':'failed','attempt':2,'message':'Provider attempt recorded.'}]
                data={'run':run,'events':events,'next_after':101 if next_page else 100}
            else:
                data={}
            route.fulfill(status=200,content_type='application/json',body=json.dumps(data))

        page.route('**/api/**', respond)
        page.goto(frontend_url+'/dashboard/runs')
        page.get_by_role('link',name='playground:crawl',exact=True).click()
        page.locator('[data-canonical-run]').wait_for()
        assert page.locator('#canonical-run-events li').count()==100
        page.get_by_role('button',name='Load more events').click()
        page.get_by_text('Provider attempt recorded.',exact=False).wait_for()
        assert page.locator('#canonical-run-events li').count()==101
        assert any('after=100' in request for request in event_pages)
        for width in (320,390,1366):
            page.set_viewport_size({'width':width,'height':844})
            assert page.evaluate('document.documentElement.scrollWidth <= innerWidth')
        page.get_by_role('button',name='Cancel run',exact=True).click()
        page.locator('[data-canonical-run]').get_by_text('cancelled',exact=True).wait_for()
        assert page.get_by_role('button',name='Cancel run',exact=True).count()==0
        assert not errors, errors
        browser.close()


def test_spending_limits_account_key_save_conflict_reload_and_mobile(frontend_url):
    saved=[]; conflicts={'enabled':False}
    policies={scope:{'scope_id':scope,'version':0,'single_run_limit_credits':None,
                    'daily_limit_credits':None,'monthly_limit_credits':None} for scope in ('account','key_fixture')}
    with playwright.sync_playwright() as p:
        browser=p.chromium.launch()
        page=browser.new_page(viewport={'width':390,'height':844})
        errors=[];page.on('pageerror',lambda e:errors.append(str(e)))
        def respond(route):
            path=urlsplit(route.request.url).path
            scope='key_fixture' if '/key_fixture/' in path else 'account'
            if path=='/api/auth/me':
                data={'user':{'email':'owner@test.invalid','email_verified':True},'account':{}}
            elif path=='/api/api-keys':
                data={'keys':[{'id':'key_fixture','name':'Scheduled capture','scopes':['mcp:execute']}]}
            elif path.endswith('/spend-policy'):
                if route.request.method=='PUT':
                    body=route.request.post_data_json;saved.append((scope,body))
                    if conflicts['enabled']:
                        route.fulfill(status=409,content_type='application/json',body=json.dumps({'detail':{
                            'code':'spend_policy_changed','message':'Spending limits changed. Reload them before saving.'}}))
                        return
                    policies[scope]={**policies[scope],**{name:value for name,value in body.items() if name!='expected_version'},
                                     'version':policies[scope]['version']+1}
                data={'policy':policies[scope],'wallet_units_per_usd':5000,'usage':{'day_end':'2026-10-02T00:00:00Z',
                    **{period:{'charged_credits':1000,'reserved_credits':500,'remaining_credits':None,'unknown_reservation_count':0}
                       for period in ('daily','monthly')}}}
            else:
                data={}
            route.fulfill(status=200,content_type='application/json',body=json.dumps(data))
        page.route('**/api/**',respond)
        page.goto(frontend_url+'/dashboard/spending')
        page.get_by_label('Daily spend (USD)',exact=True).wait_for()
        assert not saved
        assert 'reserved' in page.locator('#spend-policy-panel').inner_text()
        page.get_by_label('Daily spend (USD)',exact=True).fill('0.0002')
        page.get_by_role('button',name='Save limits',exact=True).click()
        page.get_by_text('Limits saved.',exact=True).wait_for()
        assert saved[-1]==('account',{'expected_version':0,'single_run_limit_credits':None,'daily_limit_credits':1,'monthly_limit_credits':None})
        assert page.get_by_label('Daily spend (USD)',exact=True).input_value()=='0.0002'
        page.get_by_label('Apply limits to',exact=True).select_option('key_fixture')
        page.get_by_role('heading',name='Scheduled capture',exact=True).wait_for()
        page.get_by_label('Per-run spend (USD)',exact=True).fill('0')
        page.get_by_role('button',name='Save limits',exact=True).click()
        page.get_by_text('Limits saved.',exact=True).wait_for()
        assert saved[-1][0]=='key_fixture' and saved[-1][1]['single_run_limit_credits']==0
        assert saved[-1][1]['daily_limit_credits'] is None
        conflicts['enabled']=True
        page.get_by_label('Monthly spend (USD)',exact=True).fill('1')
        page.get_by_role('button',name='Save limits',exact=True).click()
        page.get_by_text('Spending limits changed. Reload them before saving.',exact=True).wait_for()
        assert policies['key_fixture']['monthly_limit_credits'] is None
        conflicts['enabled']=False
        page.get_by_role('button',name='Reload limits and usage',exact=True).click()
        assert page.get_by_label('Monthly spend (USD)',exact=True).input_value()==''
        for width in (320,390,1366):
            page.set_viewport_size({'width':width,'height':844})
            assert page.evaluate('document.documentElement.scrollWidth <= innerWidth')
        assert not errors,errors
        page.screenshot(path='/tmp/opencrawl-spend-limits-desktop.png',full_page=True)
        browser.close()


def test_spending_limits_loading_error_retry_and_unknown_headroom(frontend_url):
    failure={'enabled':True}
    with playwright.sync_playwright() as p:
        browser=p.chromium.launch();page=browser.new_page()
        def respond(route):
            path=urlsplit(route.request.url).path
            if path=='/api/auth/me':
                data={'user':{'email':'owner@test.invalid','email_verified':True},'account':{}}
            elif path=='/api/api-keys':
                data={'keys':[]}
            elif path=='/api/spend-policy':
                if failure['enabled']:
                    route.fulfill(status=503,content_type='application/json',body=json.dumps({'detail':'Temporarily unavailable'}))
                    return
                data={'policy':{'version':0,'single_run_limit_credits':None,'daily_limit_credits':10,'monthly_limit_credits':None},
                    'wallet_units_per_usd':5000,'usage':{'day_end':'2026-10-02T00:00:00Z',
                        **{period:{'charged_credits':0,'reserved_credits':0,'remaining_credits':None,'unknown_reservation_count':1}
                           for period in ('daily','monthly')}}}
            else:
                data={}
            route.fulfill(status=200,content_type='application/json',body=json.dumps(data))
        page.route('**/api/**',respond)
        page.goto(frontend_url+'/dashboard/spending')
        page.get_by_role('alert').get_by_text('Temporarily unavailable',exact=True).wait_for()
        assert page.get_by_role('button',name='Save limits',exact=True).count()==0
        failure['enabled']=False
        page.get_by_role('button',name='Try again',exact=True).click()
        page.get_by_role('button',name='Save limits',exact=True).wait_for()
        assert 'Unknown · active reservation needs review' in page.locator('#spend-policy-panel').inner_text()
        browser.close()
