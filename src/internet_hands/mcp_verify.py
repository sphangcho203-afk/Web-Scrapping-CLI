"""Real OAuth/Streamable HTTP verifier; credentials stay in process memory."""
from __future__ import annotations

import argparse
import asyncio
import hmac
import json
import logging
import threading
import webbrowser
from http.server import BaseHTTPRequestHandler, HTTPServer
from urllib.parse import parse_qs, urlsplit

import httpx2
from mcp import ClientSession
from mcp.client.auth import OAuthClientProvider
from mcp.client.streamable_http import streamable_http_client
from mcp.shared.auth import AuthorizationCodeResult, OAuthClientMetadata

ORIGIN = "https://opencrawl.top"
CASES = [
    ("success", "printf 'opencrawl-mcp-ok\\n'; printf 'stderr-ok\\n' >&2", 10, "completed"),
    ("nonzero", "printf 'expected-failure\\n' >&2; exit 7", 10, "failed"),
    ("timeout", "sleep 3", 1, "failed"),
]


class MemoryStorage:
    def __init__(self):
        self.tokens = None
        self.client_info = None

    async def get_tokens(self):
        return self.tokens

    async def set_tokens(self, tokens):
        self.tokens = tokens

    async def get_client_info(self):
        return self.client_info

    async def set_client_info(self, client_info):
        self.client_info = client_info


class LoopbackAuthorization:
    """Receive an SDK-validated PKCE callback on this computer, without logging codes."""
    def __init__(self):
        self.ready = threading.Event()
        self.state = ""
        self.result = None
        owner = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *_):
                pass

            def do_GET(self):
                parsed = urlsplit(self.path)
                query = parse_qs(parsed.query)
                valid = parsed.path == "/callback" and owner.state and hmac.compare_digest(
                    query.get("state", [""])[0], owner.state)
                if not valid or not query.get("code") or query.get("error"):
                    self.send_response(400)
                    self.end_headers()
                    self.wfile.write(b"Authorization was not accepted. Return to the verifier.")
                    return
                owner.result = AuthorizationCodeResult(code=query["code"][0],
                    state=query["state"][0], iss=query.get("iss", [None])[0])
                self.send_response(200)
                self.send_header("Content-Type", "text/plain; charset=utf-8")
                self.send_header("Cache-Control", "no-store")
                self.end_headers()
                self.wfile.write(b"Authorization received. Return to the verifier. You may close this tab.")
                owner.ready.set()

        self.server = HTTPServer(("127.0.0.1", 0), Handler)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.redirect_uri = f"http://127.0.0.1:{self.server.server_port}/callback"

    async def redirect(self, url):
        parsed = urlsplit(url)
        if f"{parsed.scheme}://{parsed.netloc}" != ORIGIN or parsed.path != "/oauth/authorize":
            raise RuntimeError("Unexpected authorization destination; stopped.")
        self.state = parse_qs(parsed.query).get("state", [""])[0]
        print("Approve OpenCrawl MCP verifier in the browser. Enter the API key only on opencrawl.top.", flush=True)
        if not await asyncio.to_thread(webbrowser.open, url):
            print("Open this authorization URL on the same computer:\n" + url, flush=True)

    async def callback(self):
        if not await asyncio.to_thread(self.ready.wait, 300):
            raise RuntimeError("Authorization timed out; no command was submitted.")
        return self.result

    def close(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=2)


def _data(result):
    if result.is_error or not isinstance(result.structured_content, dict):
        raise RuntimeError("MCP returned an error or an unstructured result. No automatic retry.")
    return result.structured_content


def verify_receipt(wallet, request_id, maximum):
    rows = [row for row in wallet.get("ledger", [])
        if row.get("reference_id") == request_id and row.get("kind") == "usage"]
    if not rows or len({row["bucket"] for row in rows}) != len(rows):
        raise RuntimeError("Settlement is missing or duplicated. Check Runs before retrying.")
    charge = -sum(int(row["amount"]) for row in rows)
    if not 0 < charge <= maximum:
        raise RuntimeError("Recorded charge is outside the reviewed credit cap.")
    if any(int(row["metadata"]["reservation"]["settled"]) != charge for row in rows):
        raise RuntimeError("Wallet entries disagree with settlement.")
    return charge


async def verify(*, execute=False, failures=False, max_total_credits=0):
    if execute and max_total_credits <= 0:
        raise ValueError("Execution requires an explicit positive --max-total-credits.")
    authorization = LoopbackAuthorization()
    storage = MemoryStorage()
    oauth = OAuthClientProvider(server_url=ORIGIN + "/mcp", storage=storage,
        client_metadata=OAuthClientMetadata(client_name="OpenCrawl MCP verifier",
            redirect_uris=[authorization.redirect_uri], scope="mcp:read mcp:execute account:read",
            grant_types=["authorization_code"], response_types=["code"], token_endpoint_auth_method="none"),
        redirect_handler=authorization.redirect, callback_handler=authorization.callback)
    receipts = []

    async def response_hook(response):
        request_id = response.headers.get("x-request-id")
        if request_id and response.headers.get("x-credits-reserved"):
            receipts.append({"request_id": request_id,
                "reserved": int(response.headers["x-credits-reserved"])})

    try:
        async with httpx2.AsyncClient(auth=oauth, timeout=60,
            event_hooks={"response": [response_hook]}) as client:
            async with streamable_http_client(ORIGIN + "/mcp", http_client=client) as streams:
                async with ClientSession(*streams) as session:
                    initialized = await session.initialize()
                    tools = await session.list_tools()
                    names = {tool.name for tool in tools.tools}
                    required = {"mesh_execute", "account_wallet"}
                    if not required.issubset(names):
                        raise RuntimeError("Required tools are missing from the live catalog.")
                    execute_tool = next(tool for tool in tools.tools if tool.name == "mesh_execute")
                    if not {"max_charge_credits", "quote_revision"}.issubset(execute_tool.input_schema.get("properties", {})):
                        raise RuntimeError("Live MCP schema does not expose spending controls.")
                    print(json.dumps({"oauth": "authorized", "protocol": initialized.protocol_version,
                        "tools": len(names), "spending_controls": True}), flush=True)
                    if not execute:
                        return
                    ceiling_used = 0
                    for name, command, timeout, expected in CASES if failures else CASES[:1]:
                        quoted = await client.post(ORIGIN + "/api/sandbox/quote", json={
                            "command": command, "timeout_seconds": timeout})
                        quoted.raise_for_status()
                        quote = quoted.json()["quote"]
                        maximum = int(quote["maximum_charge_credits"])
                        if maximum <= 0 or not quote["affordable"] or not quote["allowed"] or ceiling_used + maximum > max_total_credits:
                            raise RuntimeError("Quote exceeds the total spending limit or execution is unavailable.")
                        ceiling_used += maximum
                        before = len(receipts)
                        # This call is never retried. Uncertain results must be reconciled in Runs.
                        result = _data(await session.call_tool("mesh_execute", {
                            "ref": "nativesandbox:exec", "arguments": {"command": command,
                                "timeout_seconds": timeout, "background": False},
                            "max_charge_credits": maximum, "quote_revision": quote["quote_revision"]}))
                        new_receipts = receipts[before:]
                        if len(new_receipts) != 1:
                            raise RuntimeError("Unexpected execution receipt count. Check Runs before retrying.")
                        receipt = new_receipts[0]
                        print(json.dumps({"case": name, **receipt, "status": result.get("status")}), flush=True)
                        if result.get("status") != expected:
                            raise RuntimeError("Unexpected command outcome. Check the recorded run.")
                        cleanup = (result.get("metadata") or {}).get("cleanup", {}).get("status")
                        if expected == "completed" and cleanup != "deleted":
                            raise RuntimeError("Sandbox deletion was not confirmed.")
                        wallet = None
                        for attempt in range(5):
                            wallet = _data(await session.call_tool("account_wallet", {"limit": 100}))
                            if any(row.get("reference_id") == receipt["request_id"] for row in wallet.get("ledger", [])):
                                break
                            if attempt < 4:
                                await asyncio.sleep(1)
                        charged = verify_receipt(wallet, receipt["request_id"], maximum)
                        print(json.dumps({"case": name, "settled_credits": charged,
                            "cleanup": cleanup or "not reported; inspect provider/run"}), flush=True)
    finally:
        authorization.close()
        storage.tokens = storage.client_info = None


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--execute", action="store_true", help="Run the fixed harmless smoke command.")
    parser.add_argument("--failures", action="store_true", help="Also run controlled nonzero and timeout cases.")
    parser.add_argument("--max-total-credits", type=int, default=0)
    args = parser.parse_args()
    logging.getLogger("mcp").setLevel(logging.CRITICAL)
    logging.getLogger("httpx2").setLevel(logging.CRITICAL)
    try:
        asyncio.run(verify(execute=args.execute, failures=args.failures,
            max_total_credits=args.max_total_credits))
    except (Exception, KeyboardInterrupt):  # noqa: BLE001 - do not print token-bearing exception URLs
        raise SystemExit("Verification stopped. No automatic retries. Check any printed request IDs in Runs.") from None


if __name__ == "__main__":
    main()
