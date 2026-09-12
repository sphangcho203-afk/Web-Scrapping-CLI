from __future__ import annotations

from functools import lru_cache
from typing import Any

from .browser_manager import BrowserSandboxManager
from .mcp_server import sandbox_mcp
from .vercel_sandbox import VercelSandboxProvider


@lru_cache(maxsize=1)
def get_browser_manager() -> BrowserSandboxManager:
    return BrowserSandboxManager(VercelSandboxProvider())


@sandbox_mcp.tool()
async def sandbox_browser_prepare(
    session_id: str,
    timeout_ms: int = 600_000,
) -> dict[str, Any]:
    """Install the versioned Playwright runtime in a sandbox; idempotent and asynchronous."""
    return await get_browser_manager().browser_prepare(session_id, timeout_ms=timeout_ms)


@sandbox_mcp.tool()
async def sandbox_browser_state(
    session_id: str,
    browser_session: str = "default",
    cwd: str | None = None,
    timeout_ms: int = 30_000,
) -> dict[str, Any]:
    """Return the current URL/title for a persistent named browser session."""
    return await get_browser_manager().browser_state(
        session_id,
        browser_session=browser_session,
        cwd=cwd,
        timeout_ms=timeout_ms,
    )


@sandbox_mcp.tool()
async def sandbox_browser_open(
    session_id: str,
    url: str,
    browser_session: str = "default",
    wait_until: str = "domcontentloaded",
    cwd: str | None = None,
    timeout_ms: int = 30_000,
) -> dict[str, Any]:
    """Navigate a persistent browser session to a public HTTP(S) URL."""
    return await get_browser_manager().browser_open(
        session_id,
        url,
        browser_session=browser_session,
        wait_until=wait_until,
        cwd=cwd,
        timeout_ms=timeout_ms,
    )


@sandbox_mcp.tool()
async def sandbox_browser_click(
    session_id: str,
    selector: str,
    browser_session: str = "default",
    nth: int = 0,
    wait_until: str | None = None,
    cwd: str | None = None,
    timeout_ms: int = 30_000,
) -> dict[str, Any]:
    """Click a Playwright locator in a persistent browser session."""
    return await get_browser_manager().browser_click(
        session_id,
        selector,
        browser_session=browser_session,
        nth=nth,
        wait_until=wait_until,
        cwd=cwd,
        timeout_ms=timeout_ms,
    )


@sandbox_mcp.tool()
async def sandbox_browser_fill(
    session_id: str,
    selector: str,
    value: str,
    browser_session: str = "default",
    nth: int = 0,
    cwd: str | None = None,
    timeout_ms: int = 30_000,
) -> dict[str, Any]:
    """Fill a form field in a persistent browser session."""
    return await get_browser_manager().browser_fill(
        session_id,
        selector,
        value,
        browser_session=browser_session,
        nth=nth,
        cwd=cwd,
        timeout_ms=timeout_ms,
    )


@sandbox_mcp.tool()
async def sandbox_browser_press(
    session_id: str,
    selector: str,
    key: str,
    browser_session: str = "default",
    nth: int = 0,
    cwd: str | None = None,
    timeout_ms: int = 30_000,
) -> dict[str, Any]:
    """Press a key on a located element in a persistent browser session."""
    return await get_browser_manager().browser_press(
        session_id,
        selector,
        key,
        browser_session=browser_session,
        nth=nth,
        cwd=cwd,
        timeout_ms=timeout_ms,
    )


@sandbox_mcp.tool()
async def sandbox_browser_extract(
    session_id: str,
    selector: str = "body",
    mode: str = "text",
    browser_session: str = "default",
    max_chars: int = 250_000,
    cwd: str | None = None,
    timeout_ms: int = 30_000,
) -> dict[str, Any]:
    """Extract text, HTML, or links from the current page using a Playwright locator."""
    return await get_browser_manager().browser_extract(
        session_id,
        selector=selector,
        mode=mode,
        browser_session=browser_session,
        max_chars=max_chars,
        cwd=cwd,
        timeout_ms=timeout_ms,
    )


@sandbox_mcp.tool()
async def sandbox_browser_capture(
    session_id: str,
    output_path: str = "artifacts/page.png",
    browser_session: str = "default",
    full_page: bool = True,
    cwd: str | None = None,
    timeout_ms: int = 30_000,
) -> dict[str, Any]:
    """Capture the current persistent browser page to a sandbox artifact path."""
    return await get_browser_manager().browser_capture(
        session_id,
        output_path=output_path,
        browser_session=browser_session,
        full_page=full_page,
        cwd=cwd,
        timeout_ms=timeout_ms,
    )


@sandbox_mcp.tool()
async def sandbox_browser_download(
    session_id: str,
    selector: str,
    browser_session: str = "default",
    nth: int = 0,
    output_dir: str = "artifacts/downloads",
    cwd: str | None = None,
    timeout_ms: int = 30_000,
) -> dict[str, Any]:
    """Click a locator that triggers a download and save it inside the sandbox."""
    return await get_browser_manager().browser_download(
        session_id,
        selector,
        browser_session=browser_session,
        nth=nth,
        output_dir=output_dir,
        cwd=cwd,
        timeout_ms=timeout_ms,
    )


@sandbox_mcp.tool()
async def sandbox_browser_trace(
    session_id: str,
    kind: str = "console",
    browser_session: str = "default",
    max_events: int = 200,
    clear: bool = False,
    cwd: str | None = None,
    timeout_ms: int = 30_000,
) -> dict[str, Any]:
    """Read persisted console/page-error or network events from a named browser session."""
    return await get_browser_manager().browser_trace(
        session_id,
        kind=kind,
        browser_session=browser_session,
        max_events=max_events,
        clear=clear,
        cwd=cwd,
        timeout_ms=timeout_ms,
    )
