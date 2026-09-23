from __future__ import annotations

from pathlib import Path

from internet_hands.site import router as site_router


def _paths() -> set[str]:
    return {str(getattr(route, "path", "") or "") for route in site_router.routes}


def test_public_legal_routes_are_registered() -> None:
    paths = _paths()
    for expected in (
        "/legal",
        "/legal/{path:path}",
        "/terms",
        "/privacy",
        "/acceptable-use",
        "/cookies",
        "/billing-policy",
        "/security",
    ):
        assert expected in paths


def test_legal_bundle_and_renderer_ship_together() -> None:
    site = Path("src/internet_hands/site.py").read_text(encoding="utf-8")
    app = Path("web/app.js").read_text(encoding="utf-8")
    policies = Path("web/legal-content.js").read_text(encoding="utf-8")
    assert 'WEB_ROOT / "legal-content.js"' in site
    assert "function renderLegalHub()" in app
    assert "function renderLegalDocument" in app
    for expected in (
        "2026-09-20",
        "Terms of Service",
        "Privacy Policy",
        "Acceptable Use Policy",
        "Cookie & Local Storage Notice",
        "Billing, Credits & Refund Policy",
        "Security & Responsible Disclosure",
        "Data Processing & Retention Notice",
        "Third-Party Services & Subprocessors",
        "Copyright & Content Takedown Policy",
    ):
        assert expected in policies


def test_public_shell_and_auth_surface_legal_links() -> None:
    app = Path("web/app.js").read_text(encoding="utf-8")
    for expected in (
        '/legal/terms',
        '/legal/privacy',
        '/legal/acceptable-use',
        '/legal',
        'ih-auth-policy-note',
    ):
        assert expected in app
