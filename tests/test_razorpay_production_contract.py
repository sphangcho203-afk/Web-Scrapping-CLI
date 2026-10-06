from __future__ import annotations

from pathlib import Path


def _source(path: str) -> str:
    return Path(path).read_text(encoding="utf-8")


def test_order_creation_freezes_credit_and_plan_entitlements() -> None:
    source = _source("src/internet_hands/control_api.py")
    assert '"credits_snapshot": int(item["credits"])' in source
    assert '"price_inr_snapshot": int(item["price_inr"])' in source
    assert '"included_credits_snapshot": int(item["included_credits"])' in source
    assert '"monthly_price_inr_snapshot": int(item["monthly_price_inr"])' in source


def test_only_hardened_billing_routes_are_registered() -> None:
    control = _source("src/internet_hands/control_api.py")
    hardening = _source("src/internet_hands/control_hardening.py")
    assert '@router.post("/api/billing/verify")' not in control
    assert '@router.post("/api/webhooks/razorpay")' not in control
    assert hardening.count('@router.post("/api/billing/verify")') == 1
    assert hardening.count('@router.post("/api/webhooks/razorpay")') == 1


def test_credit_fulfillment_is_preset_pack_only() -> None:
    source = _source("src/internet_hands/control_store.py")
    start = source.index("    def finalize_payment(")
    end = source.index("    def record_webhook(", start)
    finalize = source[start:end]
    assert "credits_snapshot" in finalize
    assert "preset_credit_pack" in finalize
    assert "wallet_usd_cents" not in finalize
    assert "invalid_custom_topup" not in finalize
    assert "usage-credit purchases must reference a preset credit pack" in finalize


def test_failed_payment_webhook_never_fulfills_credits() -> None:
    source = _source("src/internet_hands/control_hardening.py")
    assert 'if event_type == "payment.failed":' in source
    assert "store.mark_payment_failed(" in source
    failed_block = source.split('if event_type == "payment.failed":', 1)[1].split(
        'if event_type not in {"payment.captured", "order.paid"}:', 1
    )[0]
    assert "finalize_payment(" not in failed_block


def test_ledger_uses_payment_currency_not_legacy_usd_wallet_labels() -> None:
    source = _source("src/internet_hands/control_store.py")
    start = source.index("    def finalize_payment(")
    end = source.index("    def record_webhook(", start)
    finalize = source[start:end]
    assert '"display_currency": payment_currency' in finalize
    assert '"credit_pack_slug": pack_slug' in finalize
    assert '"credit_pack_credits": credits' in finalize
