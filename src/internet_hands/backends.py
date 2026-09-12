from __future__ import annotations

import json
import shutil
import subprocess
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any


DEFAULT_BACKEND_ROOT = Path(".internet-hands/backends")


class BackendError(RuntimeError):
    pass


@dataclass(frozen=True, slots=True)
class BackendSpec:
    name: str
    repository: str
    license: str
    role: str
    integration: str
    clone_by_default: bool = True
    command: tuple[str, ...] = ()
    import_name: str | None = None
    notes: str = ""


BACKENDS: tuple[BackendSpec, ...] = (
    BackendSpec(
        name="playwright-mcp",
        repository="https://github.com/microsoft/playwright-mcp.git",
        license="Apache-2.0",
        role="agent browser automation and accessibility-snapshot control",
        integration="mcp",
        command=("npx", "@playwright/mcp@latest"),
        notes="Use as an MCP sidecar; Internet Hands remains the provenance/control plane.",
    ),
    BackendSpec(
        name="crawlee-python",
        repository="https://github.com/apify/crawlee-python.git",
        license="Apache-2.0",
        role="concurrent HTTP/browser crawling, request queues, retries, sessions",
        integration="python-worker",
        import_name="crawlee",
    ),
    BackendSpec(
        name="scrapy",
        repository="https://github.com/scrapy/scrapy.git",
        license="BSD-3-Clause",
        role="high-throughput HTTP crawling and scheduling",
        integration="python-worker",
        command=("scrapy",),
        import_name="scrapy",
    ),
    BackendSpec(
        name="crawl4ai",
        repository="https://github.com/unclecode/crawl4ai.git",
        license="Apache-2.0 + project attribution requirement",
        role="LLM-oriented web extraction and browser crawling",
        integration="python-worker",
        import_name="crawl4ai",
        notes="Keep upstream attribution visible when enabled.",
    ),
    BackendSpec(
        name="trafilatura",
        repository="https://github.com/adbar/trafilatura.git",
        license="Apache-2.0",
        role="high-quality article/main-text and metadata extraction",
        integration="python-library",
        import_name="trafilatura",
    ),
    BackendSpec(
        name="firecrawl",
        repository="https://github.com/firecrawl/firecrawl.git",
        license="AGPL-3.0 (core)",
        role="optional self-hosted web-data service",
        integration="external-service",
        clone_by_default=False,
        notes=(
            "Service-only integration by default. Do not vendor its AGPL core into the MIT "
            "Internet Hands source tree without intentionally accepting the license obligations."
        ),
    ),
)


def backend_specs() -> list[BackendSpec]:
    return list(BACKENDS)


def get_backend(name: str) -> BackendSpec:
    for spec in BACKENDS:
        if spec.name == name:
            return spec
    raise BackendError(f"Unknown backend: {name}")


def clone_backend(
    name: str,
    *,
    root: Path = DEFAULT_BACKEND_ROOT,
    update: bool = True,
) -> dict[str, Any]:
    """Clone or fast-forward one curated backend and record its exact commit."""
    spec = get_backend(name)
    git = shutil.which("git")
    if not git:
        raise BackendError("git is required to clone curated backends")

    root.mkdir(parents=True, exist_ok=True)
    target = root / spec.name
    if target.exists():
        if not (target / ".git").exists():
            raise BackendError(f"Backend path exists but is not a git repository: {target}")
        if update:
            _run([git, "-C", str(target), "fetch", "--depth", "1", "origin"])
            default_ref = _run(
                [git, "-C", str(target), "symbolic-ref", "refs/remotes/origin/HEAD"],
                allow_failure=True,
            ).strip()
            if default_ref:
                remote_branch = default_ref.rsplit("/", 1)[-1]
                _run([git, "-C", str(target), "checkout", remote_branch])
                _run([git, "-C", str(target), "reset", "--hard", f"origin/{remote_branch}"])
    else:
        _run(
            [
                git,
                "clone",
                "--depth",
                "1",
                "--filter=blob:none",
                spec.repository,
                str(target),
            ]
        )

    commit = _run([git, "-C", str(target), "rev-parse", "HEAD"]).strip()
    remote = _run([git, "-C", str(target), "remote", "get-url", "origin"]).strip()
    if remote != spec.repository:
        raise BackendError(
            f"Unexpected origin for {name}: {remote!r}; expected curated origin {spec.repository!r}"
        )

    record = {
        "name": spec.name,
        "repository": spec.repository,
        "license": spec.license,
        "role": spec.role,
        "integration": spec.integration,
        "commit": commit,
        "path": str(target),
    }
    (target / ".internet-hands-backend.json").write_text(
        json.dumps(record, indent=2) + "\n",
        encoding="utf-8",
    )
    return record


def sync_default_backends(
    *,
    root: Path = DEFAULT_BACKEND_ROOT,
    update: bool = True,
) -> list[dict[str, Any]]:
    return [
        clone_backend(spec.name, root=root, update=update)
        for spec in BACKENDS
        if spec.clone_by_default
    ]


def backend_status(
    name: str,
    *,
    root: Path = DEFAULT_BACKEND_ROOT,
) -> dict[str, Any]:
    spec = get_backend(name)
    target = root / spec.name
    commit: str | None = None
    if (target / ".git").exists() and shutil.which("git"):
        commit = _run(
            ["git", "-C", str(target), "rev-parse", "HEAD"],
            allow_failure=True,
        ).strip() or None

    command_ready = None
    if spec.command:
        command_ready = shutil.which(spec.command[0]) is not None

    import_ready = None
    if spec.import_name:
        import importlib.util

        import_ready = importlib.util.find_spec(spec.import_name) is not None

    return {
        **asdict(spec),
        "cloned": (target / ".git").exists(),
        "path": str(target),
        "commit": commit,
        "command_ready": command_ready,
        "import_ready": import_ready,
    }


def playwright_mcp_config() -> dict[str, Any]:
    """Return a portable MCP configuration for Microsoft's Playwright MCP server."""
    return {
        "mcpServers": {
            "playwright": {
                "command": "npx",
                "args": ["@playwright/mcp@latest"],
            }
        }
    }


def _run(command: list[str], *, allow_failure: bool = False) -> str:
    proc = subprocess.run(
        command,
        check=False,
        capture_output=True,
        text=True,
    )
    if proc.returncode != 0 and not allow_failure:
        stderr = proc.stderr.strip() or proc.stdout.strip()
        raise BackendError(f"Command failed ({proc.returncode}): {stderr}")
    return proc.stdout
