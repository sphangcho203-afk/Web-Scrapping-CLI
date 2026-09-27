from __future__ import annotations

from internet_hands.auth import current_auth
from internet_hands.control_store import AuthIdentity
from internet_hands.tool_mcp import _bounded_request_concurrency


def test_request_concurrency_is_capped_by_authenticated_plan() -> None:
    identity = AuthIdentity(
        user_id="usr_1",
        api_key_id="key_1",
        scopes=["mcp:execute"],
        plan_slug="builder",
        rpm_limit=60,
        source="api_key",
        concurrent_limit=2,
    )
    token = current_auth.set(identity)
    try:
        assert _bounded_request_concurrency(10, maximum=20) == 2
        assert _bounded_request_concurrency(1, maximum=20) == 1
    finally:
        current_auth.reset(token)


def test_internal_concurrency_still_has_platform_ceiling_without_identity() -> None:
    token = current_auth.set(None)
    try:
        assert _bounded_request_concurrency(999, maximum=10) == 10
        assert _bounded_request_concurrency(0, maximum=10) == 1
    finally:
        current_auth.reset(token)
