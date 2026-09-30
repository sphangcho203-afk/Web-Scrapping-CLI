"""Browser contract for the semantic web capability workbench."""
from __future__ import annotations

import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlsplit

import pytest

from internet_hands.site import WEB_ROOT, _browser_runtime

playwright = pytest.importorskip("playwright.sync_api")


@pytest.fixture(scope="module")
def capability_frontend_url():
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


def test_capability_workbench_quotes_confirms_saves_and_blocks_async(
    capability_frontend_url,
):
    quotes, runs = [], []
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
                        "id": "key_fixture",
                        "name": "Workbench",
                        "prefix": "oc",
                        "scopes": ["mcp:execute"],
                    }]
                }
            elif path == "/api/dashboard":
                data = {
                    "account": {
                        "monthly_credits": 1000,
                        "purchased_credits": 0,
                        "reserved_credits": 0,
                    }
                }
            elif path == "/api/capabilities":
                data = {
                    "capabilities": [
                        {
                            "id": "web.map.site",
                            "name": "Site URL map",
                            "description": "Discover public URLs.",
                            "pack": "web",
                            "tags": ["web", "map"],
                            "read_only": True,
                        },
                        {
                            "id": "web.extract.structured",
                            "name": "Structured website extraction",
                            "description": "Extract structured public data.",
                            "pack": "web",
                            "tags": ["web", "extract"],
                            "read_only": True,
                        },
                    ]
                }
            elif path == "/api/capabilities/web.map.site" and method == "GET":
                data = {
                    "capability": {
                        "id": "web.map.site",
                        "name": "Site URL map",
                        "description": "Discover public URLs.",
                        "pack": "web",
                        "tags": ["web", "map"],
                        "read_only": True,
                        "input_schema": {
                            "type": "object",
                            "required": ["url"],
                            "properties": {
                                "url": {
                                    "type": "string",
                                    "description": "Public site root URL",
                                },
                                "limit": {
                                    "type": "integer",
                                    "minimum": 1,
                                    "maximum": 1000,
                                },
                            },
                        },
                        "output_schema": {},
                    },
                    "availability": {
                        "interactive_ready": True,
                        "available_routes": 2,
                        "reason": None,
                    },
                }
            elif path == "/api/capabilities/web.extract.structured" and method == "GET":
                data = {
                    "capability": {
                        "id": "web.extract.structured",
                        "name": "Structured website extraction",
                        "description": "Extract structured public data.",
                        "pack": "web",
                        "tags": ["web", "extract"],
                        "read_only": True,
                        "input_schema": {
                            "type": "object",
                            "required": ["prompt"],
                            "properties": {"prompt": {"type": "string"}},
                        },
                        "output_schema": {},
                    },
                    "availability": {
                        "interactive_ready": False,
                        "available_routes": 1,
                        "reason": "This route requires an owned durable job contract.",
                    },
                }
            elif path == "/api/capabilities/web.map.site/quote":
                quotes.append(route.request.post_data_json)
                data = {
                    "quote": {
                        "credits": 15,
                        "quote_revision": "c" * 64,
                        "wallet_units_per_usd": 5000,
                        "available_credits": 1000,
                        "affordable": True,
                    }
                }
            elif path == "/api/capabilities/web.map.site/run":
                runs.append(route.request.post_data_json)
                data = {
                    "ok": True,
                    "request_id": "req_capability",
                    "usage": {
                        "credits_reserved": 15,
                        "credits_charged": 9,
                        "metered": True,
                    },
                    "result": {
                        "capability": "web.map.site",
                        "status": "completed",
                        "data": {
                            "url": "https://example.com",
                            "links": [
                                "https://example.com/docs",
                                "https://example.com/pricing",
                            ],
                        },
                        "duration_ms": 42,
                        "route_attempts": [{"status": "completed", "error": None}],
                        "error": None,
                    },
                    "dataset": {
                        "id": "ds_capability",
                        "name": "Site URL map",
                        "row_count": 2,
                    },
                }
            else:
                data = {}
            route.fulfill(
                status=200,
                content_type="application/json",
                body=json.dumps(data),
            )

        page.route("**/api/**", respond)
        page.goto(capability_frontend_url + "/dashboard/capabilities")
        page.get_by_text("Site URL map", exact=True).wait_for()
        url = page.locator('[data-cap-field="url"]')
        url.fill("https://example.com")
        page.locator("#cap-review").click()
        page.locator("#cap-confirm").wait_for()
        assert len(quotes) == 1 and not runs
        assert quotes[0]["arguments"] == {"url": "https://example.com"}

        page.locator("#cap-confirm").click()
        page.get_by_text("Open saved dataset", exact=True).wait_for()
        assert len(runs) == 1
        assert runs[0]["arguments"] == {"url": "https://example.com"}
        assert runs[0]["max_charge_credits"] == 15
        assert runs[0]["quote_revision"] == "c" * 64
        assert "hidden" not in page.locator("#cap-output").inner_text().lower()
        assert "https://example.com/docs" in page.locator("#cap-output").inner_text()

        page.locator("#cap-id").select_option("web.extract.structured")
        page.get_by_text("Not runnable here yet.", exact=True).wait_for()
        assert page.locator("#cap-review").is_disabled()
        assert "durable job" in page.locator("#cap-summary").inner_text().lower()

        for width in (320, 390, 768, 1366):
            page.set_viewport_size({"width": width, "height": 800})
            page.wait_for_timeout(60)
            assert page.evaluate("document.documentElement.scrollWidth <= innerWidth"), width

        assert not errors, errors
        browser.close()
