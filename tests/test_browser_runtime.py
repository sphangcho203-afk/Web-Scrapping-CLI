from __future__ import annotations

import json
import shutil
import subprocess

import pytest

from internet_hands.browser_runtime import BROWSER_PACKAGE_JSON, BROWSER_RUNTIME_JS


def test_browser_package_manifest_is_valid_json() -> None:
    manifest = json.loads(BROWSER_PACKAGE_JSON)
    assert manifest["type"] == "module"
    assert manifest["dependencies"]["playwright"] == "1.55.0"


def test_embedded_browser_runtime_parses_with_node(tmp_path) -> None:
    node = shutil.which("node")
    if node is None:
        pytest.skip("node is not installed")
    runtime = tmp_path / "runtime.mjs"
    runtime.write_text(BROWSER_RUNTIME_JS, encoding="utf-8")
    result = subprocess.run(
        [node, "--check", str(runtime)],
        capture_output=True,
        text=True,
        check=False,
        timeout=10,
    )
    assert result.returncode == 0, result.stderr
