from __future__ import annotations

from pathlib import Path


def test_docs_only_contain_secret_variable_names() -> None:
    text = Path("docs/SAAS_CONTROL_PLANE.md").read_text(encoding="utf-8")
    assert "RAZORPAY_KEY_SECRET=" in text
    assert "GITHUB_CLIENT_SECRET=" in text
    assert "RAZORPAY_WEBHOOK_SECRET=" in text
    assert "rzp_live_" not in text
    assert "gho_" not in text
    assert "github_pat_" not in text
