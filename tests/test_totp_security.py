from __future__ import annotations

from internet_hands.totp import (
    decrypt_secret,
    encrypt_secret,
    generate_recovery_codes,
    normalize_recovery_code,
    provisioning_uri,
    totp_code,
    verify_totp,
)


def test_rfc6238_sha1_six_digit_projection() -> None:
    # RFC 6238 SHA-1 test secret; 8-digit vector at t=59 is 94287082.
    secret = "GEZDGNBVGY3TQOJQGEZDGNBVGY3TQOJQ"
    assert totp_code(secret, at=59) == "287082"
    assert verify_totp(secret, "287082", at=59, window=0) == 1
    assert verify_totp(secret, "000000", at=59, window=0) is None


def test_encrypted_totp_secret_roundtrip(monkeypatch) -> None:
    monkeypatch.setenv(
        "INTERNET_HANDS_ENCRYPTION_KEY",
        "test-only-encryption-material-that-is-long-enough-123456",
    )
    token = encrypt_secret("JBSWY3DPEHPK3PXP")
    assert token != "JBSWY3DPEHPK3PXP"
    assert decrypt_secret(token) == "JBSWY3DPEHPK3PXP"


def test_recovery_codes_are_unique_and_normalizable() -> None:
    codes = generate_recovery_codes(8)
    assert len(codes) == 8
    assert len(set(codes)) == 8
    assert all(len(normalize_recovery_code(code)) == 12 for code in codes)


def test_provisioning_uri_contains_issuer_and_account() -> None:
    uri = provisioning_uri("JBSWY3DPEHPK3PXP", "user@example.com")
    assert uri.startswith("otpauth://totp/")
    assert "issuer=Internet+Hands" in uri
    assert "secret=JBSWY3DPEHPK3PXP" in uri
