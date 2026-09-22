from __future__ import annotations

import base64
import contextvars
import hashlib
import hmac
import os
import secrets
from dataclasses import asdict
from typing import Any

from .control_store import AuthIdentity, ControlStore

PBKDF2_ITERATIONS = 310_000
current_auth: contextvars.ContextVar[AuthIdentity | None] = contextvars.ContextVar(
    "internet_hands_auth", default=None
)


def sha256_text(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def hash_password(password: str) -> str:
    if len(password) < 8:
        raise ValueError("password must contain at least 8 characters")
    salt = secrets.token_bytes(16)
    digest = hashlib.pbkdf2_hmac(
        "sha256", password.encode("utf-8"), salt, PBKDF2_ITERATIONS, dklen=32
    )
    salt_b64 = base64.urlsafe_b64encode(salt).decode().rstrip("=")
    digest_b64 = base64.urlsafe_b64encode(digest).decode().rstrip("=")
    return f"pbkdf2_sha256${PBKDF2_ITERATIONS}${salt_b64}${digest_b64}"


def _b64decode(value: str) -> bytes:
    return base64.urlsafe_b64decode(value + "=" * (-len(value) % 4))


def verify_password(password: str, encoded: str | None) -> bool:
    if not encoded:
        return False
    try:
        algorithm, iterations, salt_b64, digest_b64 = encoded.split("$", 3)
        if algorithm != "pbkdf2_sha256":
            return False
        salt = _b64decode(salt_b64)
        expected = _b64decode(digest_b64)
        actual = hashlib.pbkdf2_hmac(
            "sha256", password.encode("utf-8"), salt, int(iterations), dklen=len(expected)
        )
        return hmac.compare_digest(actual, expected)
    except (ValueError, TypeError):
        return False


def generate_api_key(environment: str = "live") -> str:
    env = "test" if environment == "test" else "live"
    return f"ih_{env}_{secrets.token_urlsafe(32)}"


def api_key_prefix(raw: str) -> str:
    return raw[:16]


def pkce_s256(verifier: str) -> str:
    digest = hashlib.sha256(verifier.encode("ascii")).digest()
    return base64.urlsafe_b64encode(digest).decode().rstrip("=")


def verify_pkce(verifier: str, challenge: str) -> bool:
    try:
        return hmac.compare_digest(pkce_s256(verifier), challenge)
    except UnicodeEncodeError:
        return False


def serialize_identity(identity: AuthIdentity) -> dict[str, Any]:
    return asdict(identity)


def _legacy_store(primary: ControlStore) -> ControlStore | None:
    dsn = os.getenv("INTERNET_HANDS_POSTGRES_DSN")
    if not dsn or dsn == primary.dsn:
        return None
    return ControlStore(dsn)


def authenticate_secret(store: ControlStore, secret: str) -> AuthIdentity | None:
    hashed = sha256_text(secret)
    identity = store.authenticate_access_token(hashed)
    if identity:
        return identity

    identity = store.authenticate_api_key(hashed)
    if identity:
        return identity

    # A key already seen by the Supabase control plane must never fall back to
    # legacy storage. This prevents a revoked migrated key being resurrected.
    if store.has_api_key_hash(hashed):
        return None

    legacy = _legacy_store(store)
    if not legacy:
        return None

    legacy_identity = legacy.authenticate_access_token(hashed)
    if legacy_identity:
        return legacy_identity

    legacy_identity = legacy.authenticate_api_key(hashed)
    if not legacy_identity:
        return None

    # Adopt only after the old database has proved possession of the key.
    # Subsequent requests authenticate entirely against Supabase.
    store.adopt_legacy_api_key(legacy, hashed)
    return store.authenticate_api_key(hashed) or legacy_identity
