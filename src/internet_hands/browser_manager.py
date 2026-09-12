from __future__ import annotations

import json
import posixpath
import secrets
from typing import Any

from .browser_runtime import (
    BROWSER_PACKAGE_JSON,
    BROWSER_PACKAGE_PATH,
    BROWSER_READY_PATH,
    BROWSER_ROOT,
    BROWSER_RUNTIME_JS,
    BROWSER_RUNTIME_PATH,
    BROWSER_RUNTIME_VERSION,
)
from .policy import validate_public_http_url
from .sandbox_manager import SandboxManager
from .sandbox_policy import validate_name, validate_timeout_ms

_ALLOWED_WAIT_UNTIL = {"load", "domcontentloaded", "networkidle"}
_ALLOWED_EXTRACT_MODES = {"text", "html", "links"}
_ALLOWED_TRACE_KINDS = {"console", "network"}


class BrowserSandboxManager(SandboxManager):
    """Structured browser actions backed by a persistent Playwright profile in the sandbox."""

    async def browser_prepare(
        self,
        session_id: str,
        *,
        timeout_ms: int = 600_000,
    ) -> dict[str, Any]:
        if not 10_000 <= timeout_ms <= self.limits.max_background_timeout_ms:
            raise ValueError(
                "browser prepare timeout must be between 10000 and "
                f"{self.limits.max_background_timeout_ms} ms"
            )
        root = await self._sandbox_root(session_id)
        ready = await self._browser_ready(session_id, root)
        if ready:
            return {
                "ready": True,
                "version": BROWSER_RUNTIME_VERSION,
                "root": posixpath.join(root, BROWSER_ROOT),
                "process": None,
            }

        await self.provider.write_file(
            session_id,
            BROWSER_PACKAGE_PATH,
            BROWSER_PACKAGE_JSON.encode(),
            cwd=root,
        )
        await self.provider.write_file(
            session_id,
            BROWSER_RUNTIME_PATH,
            BROWSER_RUNTIME_JS.encode(),
            cwd=root,
        )
        script = (
            f"mkdir -p {BROWSER_ROOT}/requests {BROWSER_ROOT}/sessions && "
            f"npm install --prefix {BROWSER_ROOT} --no-audit --no-fund --silent && "
            f"{BROWSER_ROOT}/node_modules/.bin/playwright install chromium && "
            f"printf %s {BROWSER_RUNTIME_VERSION} > {BROWSER_READY_PATH}"
        )
        process = await self.start(
            session_id,
            "/bin/sh",
            ["-lc", script],
            cwd=root,
            timeout_ms=timeout_ms,
        )
        return {
            "ready": False,
            "version": BROWSER_RUNTIME_VERSION,
            "root": posixpath.join(root, BROWSER_ROOT),
            "process": process,
            "next": "poll process status, then call browser_state or another browser action",
        }

    async def browser_state(
        self,
        session_id: str,
        *,
        browser_session: str = "default",
        cwd: str | None = None,
        timeout_ms: int = 30_000,
    ) -> dict[str, Any]:
        return await self._browser_invoke(
            session_id,
            {"action": "state", "browser_session": validate_name(browser_session)},
            cwd=cwd,
            timeout_ms=timeout_ms,
        )

    async def browser_open(
        self,
        session_id: str,
        url: str,
        *,
        browser_session: str = "default",
        wait_until: str = "domcontentloaded",
        cwd: str | None = None,
        timeout_ms: int = 30_000,
    ) -> dict[str, Any]:
        validate_public_http_url(url)
        wait_until = self._validate_wait_until(wait_until)
        return await self._browser_invoke(
            session_id,
            {
                "action": "open",
                "browser_session": validate_name(browser_session),
                "url": url,
                "wait_until": wait_until,
            },
            cwd=cwd,
            timeout_ms=timeout_ms,
        )

    async def browser_click(
        self,
        session_id: str,
        selector: str,
        *,
        browser_session: str = "default",
        nth: int = 0,
        wait_until: str | None = None,
        cwd: str | None = None,
        timeout_ms: int = 30_000,
    ) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "action": "click",
            "browser_session": validate_name(browser_session),
            "selector": self._validate_selector(selector),
            "nth": self._validate_nth(nth),
        }
        if wait_until is not None:
            payload["wait_until"] = self._validate_wait_until(wait_until)
        return await self._browser_invoke(
            session_id, payload, cwd=cwd, timeout_ms=timeout_ms
        )

    async def browser_fill(
        self,
        session_id: str,
        selector: str,
        value: str,
        *,
        browser_session: str = "default",
        nth: int = 0,
        cwd: str | None = None,
        timeout_ms: int = 30_000,
    ) -> dict[str, Any]:
        if len(value) > 100_000:
            raise ValueError("browser fill value exceeds 100000 characters")
        return await self._browser_invoke(
            session_id,
            {
                "action": "fill",
                "browser_session": validate_name(browser_session),
                "selector": self._validate_selector(selector),
                "value": value,
                "nth": self._validate_nth(nth),
            },
            cwd=cwd,
            timeout_ms=timeout_ms,
        )

    async def browser_press(
        self,
        session_id: str,
        selector: str,
        key: str,
        *,
        browser_session: str = "default",
        nth: int = 0,
        cwd: str | None = None,
        timeout_ms: int = 30_000,
    ) -> dict[str, Any]:
        if not key or len(key) > 100:
            raise ValueError("browser key must contain 1-100 characters")
        return await self._browser_invoke(
            session_id,
            {
                "action": "press",
                "browser_session": validate_name(browser_session),
                "selector": self._validate_selector(selector),
                "key": key,
                "nth": self._validate_nth(nth),
            },
            cwd=cwd,
            timeout_ms=timeout_ms,
        )

    async def browser_extract(
        self,
        session_id: str,
        *,
        selector: str = "body",
        mode: str = "text",
        browser_session: str = "default",
        max_chars: int = 250_000,
        cwd: str | None = None,
        timeout_ms: int = 30_000,
    ) -> dict[str, Any]:
        if mode not in _ALLOWED_EXTRACT_MODES:
            raise ValueError("browser extract mode must be text, html, or links")
        if not 1 <= max_chars <= 500_000:
            raise ValueError("max_chars must be between 1 and 500000")
        return await self._browser_invoke(
            session_id,
            {
                "action": "extract",
                "browser_session": validate_name(browser_session),
                "selector": self._validate_selector(selector),
                "mode": mode,
                "max_chars": max_chars,
            },
            cwd=cwd,
            timeout_ms=timeout_ms,
        )

    async def browser_capture(
        self,
        session_id: str,
        *,
        output_path: str = "artifacts/page.png",
        browser_session: str = "default",
        full_page: bool = True,
        cwd: str | None = None,
        timeout_ms: int = 30_000,
    ) -> dict[str, Any]:
        self._validate_relative_path(output_path, "output_path")
        return await self._browser_invoke(
            session_id,
            {
                "action": "screenshot",
                "browser_session": validate_name(browser_session),
                "output_path": output_path,
                "full_page": bool(full_page),
            },
            cwd=cwd,
            timeout_ms=timeout_ms,
        )

    async def browser_download(
        self,
        session_id: str,
        selector: str,
        *,
        browser_session: str = "default",
        nth: int = 0,
        output_dir: str = "artifacts/downloads",
        cwd: str | None = None,
        timeout_ms: int = 30_000,
    ) -> dict[str, Any]:
        self._validate_relative_path(output_dir, "output_dir")
        return await self._browser_invoke(
            session_id,
            {
                "action": "download",
                "browser_session": validate_name(browser_session),
                "selector": self._validate_selector(selector),
                "nth": self._validate_nth(nth),
                "output_dir": output_dir,
            },
            cwd=cwd,
            timeout_ms=timeout_ms,
        )

    async def browser_trace(
        self,
        session_id: str,
        *,
        kind: str = "console",
        browser_session: str = "default",
        max_events: int = 200,
        clear: bool = False,
        cwd: str | None = None,
        timeout_ms: int = 30_000,
    ) -> dict[str, Any]:
        if kind not in _ALLOWED_TRACE_KINDS:
            raise ValueError("browser trace kind must be console or network")
        if not 1 <= max_events <= 1000:
            raise ValueError("max_events must be between 1 and 1000")
        return await self._browser_invoke(
            session_id,
            {
                "action": "trace",
                "browser_session": validate_name(browser_session),
                "kind": kind,
                "max_events": max_events,
                "clear": bool(clear),
            },
            cwd=cwd,
            timeout_ms=timeout_ms,
        )

    async def _browser_invoke(
        self,
        session_id: str,
        payload: dict[str, Any],
        *,
        cwd: str | None,
        timeout_ms: int,
    ) -> dict[str, Any]:
        timeout_ms = validate_timeout_ms(timeout_ms, self.limits)
        root = await self._sandbox_root(session_id)
        if not await self._browser_ready(session_id, root):
            raise ValueError(
                "browser runtime is not prepared; call sandbox_browser_prepare and wait for "
                "its process to finish successfully"
            )
        token = secrets.token_hex(12)
        request_rel = f"{BROWSER_ROOT}/requests/{token}.json"
        request_abs = posixpath.join(root, request_rel)
        runtime_abs = posixpath.join(root, BROWSER_RUNTIME_PATH)
        payload = {**payload, "timeout_ms": timeout_ms}
        await self.provider.write_file(
            session_id,
            request_rel,
            json.dumps(payload, ensure_ascii=False).encode(),
            cwd=root,
        )
        try:
            result = await self.exec(
                session_id,
                "node",
                [runtime_abs, request_abs],
                cwd=cwd,
                timeout_ms=timeout_ms,
            )
        finally:
            await self.provider.exec(
                session_id,
                "rm",
                ["-f", "--", request_abs],
                timeout_ms=5_000,
            )
        if result.get("exit_code") not in (0, None):
            detail = str(result.get("stderr") or result.get("stdout") or "")[-4000:]
            raise ValueError(f"browser action failed: {detail}")
        lines = [line for line in str(result.get("stdout") or "").splitlines() if line.strip()]
        if not lines:
            raise ValueError("browser runtime returned no structured result")
        try:
            data = json.loads(lines[-1])
        except json.JSONDecodeError as exc:
            raise ValueError("browser runtime returned invalid JSON") from exc
        if not isinstance(data, dict):
            raise TypeError("browser runtime returned an invalid result object")
        return data

    async def _sandbox_root(self, session_id: str) -> str:
        result = await self.provider.exec(
            session_id,
            "pwd",
            [],
            timeout_ms=5_000,
        )
        if result.exit_code not in (0, None):
            raise ValueError("could not determine sandbox working directory")
        root = result.stdout.strip().splitlines()[-1] if result.stdout.strip() else ""
        if not root.startswith("/"):
            raise ValueError("sandbox returned an invalid working directory")
        return root.rstrip("/") or "/"

    async def _browser_ready(self, session_id: str, root: str) -> bool:
        result = await self.provider.exec(
            session_id,
            "test",
            ["-f", posixpath.join(root, BROWSER_READY_PATH)],
            timeout_ms=5_000,
        )
        return result.exit_code == 0

    @staticmethod
    def _validate_selector(selector: str) -> str:
        value = selector.strip()
        if not value or len(value) > 2_000:
            raise ValueError("browser selector must contain 1-2000 characters")
        return value

    @staticmethod
    def _validate_nth(nth: int) -> int:
        if not 0 <= nth <= 10_000:
            raise ValueError("nth must be between 0 and 10000")
        return nth

    @staticmethod
    def _validate_wait_until(value: str) -> str:
        if value not in _ALLOWED_WAIT_UNTIL:
            raise ValueError("wait_until must be load, domcontentloaded, or networkidle")
        return value

    @staticmethod
    def _validate_relative_path(value: str, field: str) -> str:
        if not value or value.startswith("/") or ".." in value.split("/"):
            raise ValueError(f"{field} must be a relative sandbox path without ..")
        if len(value) > 1_000:
            raise ValueError(f"{field} is too long")
        return value
