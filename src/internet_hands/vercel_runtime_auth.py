from __future__ import annotations

import os
from contextvars import ContextVar
from typing import Any

_request_token: ContextVar[str | None] = ContextVar("vercel_request_oidc", default=None)


def sandbox_auth_token(explicit: str | None = None) -> str | None:
    """Resolve credentials at use time; never cache a function request's OIDC token."""
    return (
        explicit
        or _request_token.get()
        or os.getenv("VERCEL_OIDC_TOKEN")
        or os.getenv("INTERNET_HANDS_VERCEL_TOKEN")
        or os.getenv("VERCEL_TOKEN")
    )


class VercelRuntimeAuthMiddleware:
    """Make Vercel's function OIDC header available to isolated Sandbox clients.

    This is provider authentication, not customer authentication. The Sandbox API
    validates the token and the configured project/team scope. Off Vercel, incoming
    headers cannot select provider credentials. Request credentials are kept out of
    process environment variables and are reset even if the request fails.
    """

    def __init__(self, app: Any) -> None:
        self.app = app

    async def __call__(self, scope: dict[str, Any], receive: Any, send: Any) -> None:
        if scope.get("type") != "http":
            await self.app(scope, receive, send)
            return
        headers = scope.get("headers", [])
        values = [v for k, v in headers if k.lower() == b"x-vercel-oidc-token"]
        value = None
        if os.getenv("VERCEL") == "1" and len(values) == 1:
            raw = values[0]
            if 0 < len(raw) <= 8192 and all(33 <= char <= 126 for char in raw):
                value = raw.decode("ascii")
        # Do not let downstream header forwarding or echoing expose this credential.
        scope = {**scope, "headers": [
            (k, v) for k, v in headers if k.lower() != b"x-vercel-oidc-token"
        ]}
        marker = _request_token.set(value)
        try:
            await self.app(scope, receive, send)
        finally:
            _request_token.reset(marker)
