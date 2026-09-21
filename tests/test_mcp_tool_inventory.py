from __future__ import annotations

import ast
from pathlib import Path

import pytest

from internet_hands import saas_app
from internet_hands.mcp_server import sandbox_mcp

ROOT = Path(__file__).resolve().parents[1]

EXPECTED = {
    "src/internet_hands/mcp_server.py": {
        "sandbox_create", "sandbox_get", "sandbox_exec", "sandbox_start", "sandbox_shell",
        "sandbox_command", "sandbox_commands", "sandbox_command_logs", "sandbox_kill",
        "sandbox_install", "sandbox_git_clone", "sandbox_read_file", "sandbox_artifact",
        "sandbox_write_file", "sandbox_mkdir", "sandbox_start_service",
        "sandbox_browser_screenshot", "sandbox_snapshot", "sandbox_fork", "sandbox_stop",
        "sandbox_delete",
    },
    "src/internet_hands/browser_mcp.py": {
        "sandbox_browser_prepare", "sandbox_browser_state", "sandbox_browser_open",
        "sandbox_browser_click", "sandbox_browser_fill", "sandbox_browser_press",
        "sandbox_browser_extract", "sandbox_browser_capture", "sandbox_browser_download",
        "sandbox_browser_trace", "sandbox_browser_close",
    },
    "src/internet_hands/tool_mcp.py": {
        "mesh_providers", "mesh_route", "mesh_search", "mesh_describe",
        "mesh_describe_many", "mesh_execute", "mesh_batch_execute", "mesh_job_status",
        "mesh_results", "mesh_capabilities", "mesh_capability_resolve",
        "mesh_capability_execute", "gaming_capabilities", "gaming_intel",
        "gaming_profile_plan", "gaming_profile",
    },
    "src/internet_hands/account_mcp.py": {
        "account_me", "account_usage", "account_wallet", "account_limits",
        "monitors_list", "monitor_get",
    },
}


def _decorated_tools(path: Path) -> set[str]:
    module = ast.parse(path.read_text(encoding="utf-8"))
    tools: set[str] = set()
    for node in module.body:
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        for decorator in node.decorator_list:
            target = decorator.func if isinstance(decorator, ast.Call) else decorator
            if (
                isinstance(target, ast.Attribute)
                and target.attr == "tool"
                and isinstance(target.value, ast.Name)
                and target.value.id == "sandbox_mcp"
            ):
                tools.add(node.name)
    return tools


def test_first_party_mcp_inventory_is_exactly_54_tools() -> None:
    actual: set[str] = set()
    for relative_path, expected in EXPECTED.items():
        found = _decorated_tools(ROOT / relative_path)
        assert found == expected, relative_path
        actual.update(found)
    assert len(actual) == 54


def test_production_app_imports_all_registration_modules() -> None:
    source = (ROOT / "src/internet_hands/saas_app.py").read_text(encoding="utf-8")
    fleet = (ROOT / "src/internet_hands/fleet_api.py").read_text(encoding="utf-8")
    assert "account_mcp" in source
    assert "browser_mcp" in fleet
    assert "tool_mcp" in fleet
    assert saas_app.app.title == "Internet Hands"


@pytest.mark.asyncio
async def test_runtime_mcp_server_lists_all_54_callable_tools_with_schemas() -> None:
    tools = await sandbox_mcp.list_tools()
    names = {tool.name for tool in tools}
    expected = set().union(*EXPECTED.values())

    assert names == expected
    assert len(tools) == 54
    assert all(isinstance(tool.input_schema, dict) for tool in tools)
    assert all(tool.name and tool.description for tool in tools)
