from __future__ import annotations

import hashlib
from datetime import UTC, datetime

from .models import BrowserResult
from .policy import PolicyError, validate_public_http_url


async def render_page(url: str, *, timeout_ms: int = 30_000) -> BrowserResult:
    """Render a public page with Playwright when the optional browser extra is installed."""
    validate_public_http_url(url)
    try:
        from playwright.async_api import async_playwright
    except ImportError as exc:
        raise RuntimeError(
            "Browser support is optional. Install with: pip install 'internet-hands[browser]'"
        ) from exc

    async with async_playwright() as playwright:
        browser = await playwright.chromium.launch(headless=True)
        context = await browser.new_context()
        page = await context.new_page()

        async def guard(route) -> None:
            try:
                validate_public_http_url(route.request.url)
            except (PolicyError, ValueError):
                await route.abort()
                return
            await route.continue_()

        await page.route("**/*", guard)
        response = await page.goto(url, wait_until="domcontentloaded", timeout=timeout_ms)
        final_url = page.url
        validate_public_http_url(final_url)
        html = await page.content()
        title = await page.title()
        status_code = response.status if response else None
        await context.close()
        await browser.close()

    payload = html.encode("utf-8")
    return BrowserResult(
        request_url=url,
        final_url=final_url,
        status_code=status_code,
        title=title or None,
        html=html,
        sha256=hashlib.sha256(payload).hexdigest(),
        captured_at=datetime.now(UTC),
    )
