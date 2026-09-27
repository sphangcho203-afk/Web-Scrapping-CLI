from __future__ import annotations

from types import SimpleNamespace

import pytest
from fastapi import HTTPException

from internet_hands import security_api
from internet_hands.security_store import SecurityStore


class _Request:
    def __init__(self, body: dict | None = None, *, cookies: dict | None = None) -> None:
        self._body = body or {}
        self.cookies = cookies or {}
        self.headers = {"host": "example.test", "x-forwarded-proto": "https"}
        self.url = SimpleNamespace(scheme="https", netloc="example.test")

    async def json(self) -> dict:
        return self._body


@pytest.mark.asyncio
async def test_2fa_backend_decrypt_failure_does_not_burn_login_attempt(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    challenge = {"id": "lch_1", "user_id": "usr_1"}
    failed: list[str] = []

    monkeypatch.setattr(
        security_api.security,
        "login_challenge",
        lambda _token_hash: challenge,
    )
    monkeypatch.setattr(
        security_api.security,
        "totp_record",
        lambda _user_id: {
            "user_id": "usr_1",
            "totp_enabled": True,
            "totp_secret_enc": "encrypted-but-not-readable",
        },
    )
    monkeypatch.setattr(
        security_api,
        "decrypt_secret",
        lambda _token: (_ for _ in ()).throw(RuntimeError("bad encryption material")),
    )
    monkeypatch.setattr(
        security_api.security,
        "fail_login_challenge",
        failed.append,
    )

    with pytest.raises(HTTPException) as exc:
        await security_api.complete_2fa_login(
            _Request(
                {"code": "123456"},
                cookies={security_api.TWO_FACTOR_COOKIE: "challenge-token"},
            )
        )

    assert exc.value.status_code == 503
    assert exc.value.detail["code"] == "two_factor_unavailable"
    assert failed == []


def test_2fa_setup_configuration_failure_does_not_store_partial_secret(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    user = {
        "id": "usr_1",
        "email": "user@example.test",
        "email_verified": True,
    }
    stored: list[tuple[str, str]] = []

    monkeypatch.setattr(security_api, "_require_user", lambda _request: user)
    monkeypatch.setattr(
        security_api.security,
        "account_security",
        lambda _user_id: {"email_verified": True, "totp_enabled": False},
    )
    monkeypatch.setattr(security_api, "encryption_configured", lambda: True)
    monkeypatch.setattr(
        security_api,
        "encrypt_secret",
        lambda _secret: (_ for _ in ()).throw(RuntimeError("bad encryption material")),
    )
    monkeypatch.setattr(
        security_api.security,
        "put_pending_totp",
        lambda user_id, token: stored.append((user_id, token)),
    )

    with pytest.raises(HTTPException) as exc:
        security_api.two_factor_setup(object())

    assert exc.value.status_code == 503
    assert exc.value.detail["code"] == "two_factor_unavailable"
    assert stored == []


class _Cursor:
    def __init__(self) -> None:
        self.rowcount = 1
        self.calls: list[tuple[str, object]] = []

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False

    def execute(self, query: str, params=None) -> None:
        self.calls.append((" ".join(query.split()), params))
        self.rowcount = 1


class _Connection:
    def __init__(self, cursor: _Cursor) -> None:
        self.cursor_instance = cursor
        self.committed = False

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False

    def cursor(self) -> _Cursor:
        return self.cursor_instance

    def commit(self) -> None:
        self.committed = True


def test_setup_confirmation_does_not_consume_first_real_totp_counter(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    cursor = _Cursor()
    connection = _Connection(cursor)
    security = SecurityStore.__new__(SecurityStore)

    monkeypatch.setattr(security, "ensure_schema", lambda: None)
    security.control = SimpleNamespace(_connect=lambda: connection)
    monkeypatch.setattr(security, "_new_id", lambda prefix: f"{prefix}_test")

    security.enable_totp("usr_1", 12345, ["recovery-hash"])

    update_sql, update_params = cursor.calls[0]
    assert "last_totp_counter=NULL" in update_sql
    assert update_params == ("usr_1",)
    assert connection.committed is True
