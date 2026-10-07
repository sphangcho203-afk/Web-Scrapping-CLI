"""Safe setup diagnostics shared by semantic routing and product discovery."""
from __future__ import annotations

from typing import Any

REASONS = {
    "not_configured": "This operation needs server-side credentials or an execution environment. Contact the workspace administrator to configure it.",
    "connection_required": "Connect an authorized account for this operation, then check availability again.",
    "tool_not_found": "This operation is not exposed by the configured connection. The workspace administrator must repair its route.",
    "temporarily_unavailable": "Availability could not be checked right now. Try again before running this operation.",
    "timeout": "The availability check timed out. Try again before running this operation.",
    "read_only_mismatch": "The configured operation does not support read-only execution. The workspace administrator must repair its route.",
    "conditions_not_matched": "No configured route matches these arguments. Check the operation's required inputs.",
}


def availability_failure(code: str) -> dict[str, Any]:
    return {"available": False, "reason_code": code, "reason": REASONS[code]}


def availability_exception(exc: Exception) -> dict[str, Any]:
    """Never echo upstream URLs, tokens, account IDs or response bodies."""
    status = getattr(getattr(exc, "response", None), "status_code", None)
    if isinstance(exc, TimeoutError) or "timeout" in type(exc).__name__.lower():
        code = "timeout"
    elif isinstance(exc, PermissionError) or status in {401, 403}:
        code = "connection_required"
    elif isinstance(exc, (LookupError, ValueError)) or status == 404:
        code = "tool_not_found"
    else:
        code = "temporarily_unavailable"
    return availability_failure(code)
