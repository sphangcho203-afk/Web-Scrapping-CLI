from __future__ import annotations

from datetime import UTC, datetime

import pytest

from internet_hands import intelligence_fabric as module
from internet_hands.models import BrowserResult, FetchResult


def _fetch(body: str, *, status: int = 200) -> FetchResult:
    payload = body.encode()
    return FetchResult(
        request_url="https://example.com/",
        final_url="https://example.com/",
        status_code=status,
        headers={},
        content_type="text/html; charset=utf-8",
        content_length=len(payload),
        sha256="a" * 64,
        elapsed_ms=10,
        captured_at=datetime.now(UTC),
        body_text=body,
    )


@pytest.mark.asyncio
async def test_resilient_fetch_keeps_native_http_when_content_is_good(monkeypatch) -> None:
    async def fetch(*args, **kwargs):
        return _fetch("<html><title>Example</title><body><h1>Hello</h1><p>" + "Useful text " * 80 + "</p></body></html>")

    async def browser(*args, **kwargs):
        pytest.fail("browser fallback should not run for sufficient static content")

    monkeypatch.setattr(module, "fetch_url", fetch)
    monkeypatch.setattr(module, "render_page", browser)

    result = await module.resilient_public_fetch(
        "https://example.com/",
        render="auto",
        minimum_text=100,
    )

    assert result["status"] == "completed"
    assert result["selected_backend"] == "native-http"
    assert result["document"]["title"] == "Example"
    assert result["blocked"] is False


@pytest.mark.asyncio
async def test_resilient_fetch_renders_dynamic_page_when_native_text_is_thin(monkeypatch) -> None:
    async def fetch(*args, **kwargs):
        return _fetch("<html><body><div id='root'></div><script>webpack={}</script></body></html>")

    async def browser(*args, **kwargs):
        html = "<html><title>Rendered</title><body><h1>Loaded</h1><p>" + "Rendered evidence " * 60 + "</p></body></html>"
        return BrowserResult(
            request_url="https://example.com/",
            final_url="https://example.com/",
            status_code=200,
            title="Rendered",
            html=html,
            sha256="b" * 64,
            captured_at=datetime.now(UTC),
        )

    monkeypatch.setattr(module, "fetch_url", fetch)
    monkeypatch.setattr(module, "render_page", browser)

    result = await module.resilient_public_fetch(
        "https://example.com/",
        render="auto",
        minimum_text=100,
    )

    assert result["selected_backend"] == "native-playwright"
    assert result["document"]["title"] == "Rendered"
    assert [item["backend"] for item in result["attempts"]] == [
        "native-http",
        "native-playwright",
    ]


@pytest.mark.asyncio
async def test_challenge_page_is_reported_without_attempting_bypass(monkeypatch) -> None:
    async def fetch(*args, **kwargs):
        return _fetch(
            "<html><title>Verify</title><body>CAPTCHA - verify you are human</body></html>",
            status=403,
        )

    async def browser(*args, **kwargs):
        pytest.fail("challenge pages must not trigger browser evasion")

    monkeypatch.setattr(module, "fetch_url", fetch)
    monkeypatch.setattr(module, "render_page", browser)

    result = await module.resilient_public_fetch("https://example.com/", render="auto")

    assert result["status"] == "blocked"
    assert result["blocked"] is True
    assert result["selected_backend"] == "native-http"
    assert result["policy"]["challenge_bypass"] is False
    assert len(result["attempts"]) == 1


@pytest.mark.asyncio
async def test_external_backend_requires_explicit_server_opt_in(monkeypatch) -> None:
    monkeypatch.delenv("OPENCRAWL_EXTERNAL_BACKENDS_ENABLED", raising=False)
    provider = module.IntelligenceFabricProvider()

    with pytest.raises(module.AdapterError, match="disabled"):
        await module.resilient_public_fetch(
            "https://example.com/",
            backend="crawl4ai",
        )

    status = await provider.status()
    assert status["challenge_bypass"] is False
    assert status["optional_backends_enabled"] is False
