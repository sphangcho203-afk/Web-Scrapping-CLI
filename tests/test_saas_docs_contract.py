from __future__ import annotations

from pathlib import Path


def test_saas_docs_pin_permanent_endpoints() -> None:
    text = Path("docs/SAAS_CONTROL_PLANE.md").read_text(encoding="utf-8")
    for expected in (
        "/mcp",
        "/api/auth/github/callback",
        "/api/webhooks/razorpay",
        "/.well-known/oauth-protected-resource",
        "/oauth/authorize",
        "/oauth/token",
    ):
        assert expected in text
