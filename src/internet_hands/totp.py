from __future__ import annotations

import base64
import hashlib
import hmac
import os
import secrets
import struct
import time
from urllib.parse import quote, urlencode

from cryptography.fernet import Fernet, InvalidToken

TOTP_PERIOD = 30
TOTP_DIGITS = 6


def _encryption_material() -> str:
    value = os.getenv("INTERNET_HANDS_ENCRYPTION_KEY")
    if not value:
        raise RuntimeError(
            "INTERNET_HANDS_ENCRYPTION_KEY is required for TOTP secret storage"
        )
    if len(value) < 24:
        raise RuntimeError("Internet Hands encryption material is too short")
    return value


def encryption_configured() -> bool:
    value = os.getenv("INTERNET_HANDS_ENCRYPTION_KEY")
    return bool(value and len(value) >= 24)


def _fernet() -> Fernet:
    digest = hashlib.sha256(_encryption_material().encode("utf-8")).digest()
    return Fernet(base64.urlsafe_b64encode(digest))


def encrypt_secret(secret: str) -> str:
    return _fernet().encrypt(secret.encode("ascii")).decode("ascii")


def decrypt_secret(token: str) -> str:
    try:
        return _fernet().decrypt(token.encode("ascii")).decode("ascii")
    except InvalidToken as exc:
        raise RuntimeError("stored TOTP secret cannot be decrypted") from exc


def generate_totp_secret() -> str:
    return base64.b32encode(os.urandom(20)).decode("ascii").rstrip("=")


def _decode_base32(secret: str) -> bytes:
    cleaned = "".join(secret.upper().split())
    padding = "=" * ((8 - len(cleaned) % 8) % 8)
    return base64.b32decode(cleaned + padding, casefold=True)


def hotp(secret: str, counter: int, digits: int = TOTP_DIGITS) -> str:
    key = _decode_base32(secret)
    digest = hmac.new(key, struct.pack(">Q", counter), hashlib.sha1).digest()
    offset = digest[-1] & 0x0F
    binary = (
        ((digest[offset] & 0x7F) << 24)
        | ((digest[offset + 1] & 0xFF) << 16)
        | ((digest[offset + 2] & 0xFF) << 8)
        | (digest[offset + 3] & 0xFF)
    )
    return str(binary % (10**digits)).zfill(digits)


def totp_code(secret: str, *, at: float | None = None) -> str:
    now = int(time.time() if at is None else at)
    return hotp(secret, now // TOTP_PERIOD)


def verify_totp(
    secret: str,
    code: str,
    *,
    at: float | None = None,
    window: int = 1,
) -> int | None:
    candidate = "".join(ch for ch in str(code) if ch.isdigit())
    if len(candidate) != TOTP_DIGITS:
        return None
    now = int(time.time() if at is None else at)
    current = now // TOTP_PERIOD
    for delta in range(-window, window + 1):
        counter = current + delta
        if counter < 0:
            continue
        if hmac.compare_digest(hotp(secret, counter), candidate):
            return counter
    return None


def provisioning_uri(secret: str, email: str, issuer: str = "Internet Hands") -> str:
    label = f"{issuer}:{email}"
    query = urlencode(
        {
            "secret": secret,
            "issuer": issuer,
            "algorithm": "SHA1",
            "digits": str(TOTP_DIGITS),
            "period": str(TOTP_PERIOD),
        }
    )
    return f"otpauth://totp/{quote(label, safe='')}?{query}"


def generate_recovery_codes(count: int = 8) -> list[str]:
    letters = "ABCDEFGHJKLMNPQRSTUVWXYZ"
    alphabet = letters + "23456789"
    codes: list[str] = []
    for _ in range(max(4, min(count, 12))):
        # Guarantee at least one letter so recovery input can never be mistaken for TOTP.
        raw = secrets.choice(letters) + "".join(secrets.choice(alphabet) for _ in range(11))
        codes.append(f"{raw[:4]}-{raw[4:8]}-{raw[8:]}")
    return codes


def normalize_recovery_code(value: str) -> str:
    return "".join(ch for ch in value.upper() if ch.isalnum())
