from __future__ import annotations

from internet_hands.mcp_server import _transport_security


def test_mcp_transport_security_allows_canonical_domain() -> None:
    settings = _transport_security()

    assert "opencrawl.top" in settings.allowed_hosts
    assert "www.opencrawl.top" in settings.allowed_hosts
    assert "https://opencrawl.top" in settings.allowed_origins
    assert "https://www.opencrawl.top" in settings.allowed_origins
