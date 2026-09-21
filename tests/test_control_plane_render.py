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
