from __future__ import annotations

from internet_hands import control_api


def test_razorpay_secret_prefers_exact_supabase_vault_name(monkeypatch) -> None:
    monkeypatch.setenv("RAZORPAY_KEY_ID", "env-key-id")

    def fake_vault(name: str):
        return "vault-key-id" if name == "RAZORPAY_KEY_ID" else None

    monkeypatch.setattr(control_api, "supabase_vault_secret", fake_vault)

    value, source = control_api._razorpay_secret("RAZORPAY_KEY_ID")

    assert value == "vault-key-id"
    assert source == "supabase_vault"


def test_razorpay_secret_supports_prefixed_vault_alias(monkeypatch) -> None:
    monkeypatch.delenv("RAZORPAY_KEY_SECRET", raising=False)

    def fake_vault(name: str):
        return "vault-key-secret" if name == "opencrawl_razorpay_key_secret" else None

    monkeypatch.setattr(control_api, "supabase_vault_secret", fake_vault)

    value, source = control_api._razorpay_secret("RAZORPAY_KEY_SECRET")

    assert value == "vault-key-secret"
    assert source == "supabase_vault"


def test_razorpay_secret_falls_back_to_environment(monkeypatch) -> None:
    monkeypatch.setenv("RAZORPAY_WEBHOOK_SECRET", "env-webhook-secret")
    monkeypatch.setattr(control_api, "supabase_vault_secret", lambda name: None)

    value, source = control_api._razorpay_secret("RAZORPAY_WEBHOOK_SECRET")

    assert value == "env-webhook-secret"
    assert source == "environment"


def test_razorpay_status_reports_vault_without_exposing_secret(monkeypatch) -> None:
    values = {
        "RAZORPAY_KEY_ID": "rzp_live_public_id",
        "RAZORPAY_KEY_SECRET": "live-secret",
        "RAZORPAY_WEBHOOK_SECRET": "webhook-secret",
    }

    monkeypatch.setattr(
        control_api,
        "_razorpay_secret",
        lambda name: (values[name], "supabase_vault"),
    )

    status = control_api._razorpay_status()

    assert status["configured"] is True
    assert status["webhook_configured"] is True
    assert status["credential_source"] == "supabase_vault"
    assert status["webhook_source"] == "supabase_vault"
    assert status["key_id"] == "rzp_live_public_id"
    assert "live-secret" not in status.values()
    assert "webhook-secret" not in status.values()


def test_razorpay_config_reads_all_three_vault_backed_values(monkeypatch) -> None:
    values = {
        "RAZORPAY_KEY_ID": "rzp_live_public_id",
        "RAZORPAY_KEY_SECRET": "live-secret",
        "RAZORPAY_WEBHOOK_SECRET": "webhook-secret",
    }
    monkeypatch.setattr(
        control_api,
        "_razorpay_secret",
        lambda name: (values[name], "supabase_vault"),
    )

    assert control_api._razorpay_config() == (
        "rzp_live_public_id",
        "live-secret",
        "webhook-secret",
    )


def test_preview_disables_live_billing_and_does_not_touch_vault(monkeypatch) -> None:
    monkeypatch.setenv("VERCEL_ENV", "preview")
    monkeypatch.delenv("OPENCRAWL_ALLOW_PREVIEW_BILLING", raising=False)
    touched = {"vault": False}

    def fake_vault(name: str):
        touched["vault"] = True
        return "should-not-be-read"

    monkeypatch.setattr(control_api, "supabase_vault_secret", fake_vault)

    value, source = control_api._razorpay_secret("RAZORPAY_KEY_ID")

    assert value is None
    assert source == "disabled_on_preview"
    assert touched["vault"] is False


def test_preview_billing_can_be_explicitly_enabled_for_controlled_testing(monkeypatch) -> None:
    monkeypatch.setenv("VERCEL_ENV", "preview")
    monkeypatch.setenv("OPENCRAWL_ALLOW_PREVIEW_BILLING", "true")
    monkeypatch.setattr(
        control_api,
        "supabase_vault_secret",
        lambda name: "vault-key" if name == "RAZORPAY_KEY_ID" else None,
    )

    value, source = control_api._razorpay_secret("RAZORPAY_KEY_ID")

    assert value == "vault-key"
    assert source == "supabase_vault"
