from __future__ import annotations

import pytest

from internet_hands.auth import (
    api_key_prefix,
    generate_api_key,
    hash_password,
    pkce_s256,
    verify_password,
    verify_pkce,
)


def test_password_hash_round_trip() -> None:
    encoded = hash_password("correct horse battery staple")
    assert encoded.startswith("pbkdf2_sha256$")
    assert verify_password("correct horse battery staple", encoded)
    assert not verify_password("wrong password", encoded)


def test_password_rejects_short_values() -> None:
    with pytest.raises(ValueError, match="at least 8"):
        hash_password("short")


def test_api_key_shape_and_prefix() -> None:
    live = generate_api_key("live")
    test = generate_api_key("test")
    assert live.startswith("ih_live_")
    assert test.startswith("ih_test_")
    assert api_key_prefix(live) == live[:16]


def test_pkce_s256_round_trip() -> None:
    verifier = "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789-._~"
    challenge = pkce_s256(verifier)
    assert verify_pkce(verifier, challenge)
    assert not verify_pkce(verifier + "x", challenge)
