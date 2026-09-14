from __future__ import annotations

import hmac
import json
import threading
import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

from psycopg.errors import UniqueViolation

from .control_store import ControlError, ControlStore

SECURITY_SCHEMA_SQL = r"""
CREATE TABLE IF NOT EXISTS ih_user_security (
    user_id text PRIMARY KEY REFERENCES ih_users(id) ON DELETE CASCADE,
    totp_secret_enc text,
    totp_enabled boolean NOT NULL DEFAULT false,
    totp_confirmed_at timestamptz,
    last_totp_counter bigint,
    updated_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS ih_email_verifications (
    id text PRIMARY KEY,
    user_id text NOT NULL REFERENCES ih_users(id) ON DELETE CASCADE,
    email text NOT NULL,
    token_hash text NOT NULL UNIQUE,
    code_hash text NOT NULL,
    expires_at timestamptz NOT NULL,
    attempts integer NOT NULL DEFAULT 0,
    used_at timestamptz,
    created_at timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS ih_email_verifications_user_idx
    ON ih_email_verifications(user_id, created_at DESC);

CREATE TABLE IF NOT EXISTS ih_login_challenges (
    id text PRIMARY KEY,
    user_id text NOT NULL REFERENCES ih_users(id) ON DELETE CASCADE,
    token_hash text NOT NULL UNIQUE,
    expires_at timestamptz NOT NULL,
    used_at timestamptz,
    created_at timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS ih_login_challenges_user_idx
    ON ih_login_challenges(user_id, created_at DESC);

CREATE TABLE IF NOT EXISTS ih_2fa_recovery_codes (
    id text PRIMARY KEY,
    user_id text NOT NULL REFERENCES ih_users(id) ON DELETE CASCADE,
    code_hash text NOT NULL UNIQUE,
    used_at timestamptz,
    created_at timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS ih_2fa_recovery_codes_user_idx
    ON ih_2fa_recovery_codes(user_id, created_at DESC);

CREATE TABLE IF NOT EXISTS ih_email_events (
    id text PRIMARY KEY,
    user_id text REFERENCES ih_users(id) ON DELETE SET NULL,
    email text NOT NULL,
    event_type text NOT NULL,
    provider text,
    status text NOT NULL,
    message_id text,
    dedupe_key text UNIQUE,
    error text,
    metadata jsonb NOT NULL DEFAULT '{}'::jsonb,
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS ih_email_events_user_idx
    ON ih_email_events(user_id, created_at DESC);
"""


class SecurityStore:
    def __init__(self, control: ControlStore) -> None:
        self.control = control
        self._schema_ready = False
        self._schema_lock = threading.Lock()

    def _new_id(self, prefix: str) -> str:
        return f"{prefix}_{uuid.uuid4().hex}"

    def ensure_schema(self) -> None:
        if self._schema_ready:
            return
        with self._schema_lock:
            if self._schema_ready:
                return
            self.control.ensure_schema()
            with self.control._connect() as conn, conn.cursor() as cur:
                cur.execute(SECURITY_SCHEMA_SQL)
                # Repair legacy provisional identities that were incorrectly
                # provisioned before email verification. The identity and its
                # verification challenge remain; active resources do not.
                cur.execute(
                    "DELETE FROM ih_api_keys WHERE user_id IN "
                    "(SELECT id FROM ih_users WHERE email_verified=false)"
                )
                cur.execute(
                    "DELETE FROM ih_subscriptions WHERE user_id IN "
                    "(SELECT id FROM ih_users WHERE email_verified=false)"
                )
                cur.execute(
                    "DELETE FROM ih_credit_ledger WHERE user_id IN "
                    "(SELECT id FROM ih_users WHERE email_verified=false)"
                )
                cur.execute(
                    "DELETE FROM ih_wallets WHERE user_id IN "
                    "(SELECT id FROM ih_users WHERE email_verified=false)"
                )
                conn.commit()
            self._schema_ready = True

    def account_security(self, user_id: str) -> dict[str, Any]:
        self.ensure_schema()
        with self.control._connect() as conn, conn.cursor() as cur:
            cur.execute(
                """
                SELECT u.id,u.email,u.email_verified,
                       COALESCE(s.totp_enabled,false) AS totp_enabled,
                       s.totp_confirmed_at
                FROM ih_users u
                LEFT JOIN ih_user_security s ON s.user_id=u.id
                WHERE u.id=%s
                """,
                (user_id,),
            )
            row = cur.fetchone()
            if not row:
                raise ControlError("account_not_found", "account not found", 404)
            return dict(row)

    def set_email_verified(self, user_id: str, verified: bool) -> None:
        self.ensure_schema()
        with self.control._connect() as conn, conn.cursor() as cur:
            cur.execute(
                "UPDATE ih_users SET email_verified=%s,updated_at=now() WHERE id=%s",
                (verified, user_id),
            )
            if verified and cur.rowcount == 1:
                self.control._activate_free_account(cur, user_id)
            conn.commit()

    def create_email_verification(
        self,
        *,
        user_id: str,
        email: str,
        token_hash: str,
        code_hash: str,
        ttl_minutes: int = 15,
    ) -> None:
        self.ensure_schema()
        with self.control._connect() as conn, conn.cursor() as cur:
            cur.execute(
                """
                UPDATE ih_email_verifications SET used_at=now()
                WHERE user_id=%s AND used_at IS NULL
                """,
                (user_id,),
            )
            cur.execute(
                """
                INSERT INTO ih_email_verifications(
                    id,user_id,email,token_hash,code_hash,expires_at
                ) VALUES (%s,%s,%s,%s,%s,%s)
                """,
                (
                    self._new_id("emv"),
                    user_id,
                    email.strip().lower(),
                    token_hash,
                    code_hash,
                    datetime.now(UTC) + timedelta(minutes=ttl_minutes),
                ),
            )
            conn.commit()

    def consume_email_token(self, token_hash: str) -> dict[str, Any] | None:
        self.ensure_schema()
        with self.control._connect() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT * FROM ih_email_verifications
                    WHERE token_hash=%s AND used_at IS NULL AND expires_at>now()
                    FOR UPDATE
                    """,
                    (token_hash,),
                )
                row = cur.fetchone()
                if not row:
                    return None
                cur.execute(
                    """
                    UPDATE ih_users SET email_verified=true,updated_at=now()
                    WHERE id=%s AND lower(email)=lower(%s)
                    """,
                    (row["user_id"], row["email"]),
                )
                if cur.rowcount != 1:
                    conn.rollback()
                    return None
                self.control._activate_free_account(cur, row["user_id"])
                cur.execute(
                    "UPDATE ih_email_verifications SET used_at=now() WHERE id=%s",
                    (row["id"],),
                )
            conn.commit()
            return dict(row)

    def consume_email_code(self, user_id: str, code_hash: str) -> dict[str, Any] | None:
        self.ensure_schema()
        with self.control._connect() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT * FROM ih_email_verifications
                    WHERE user_id=%s AND used_at IS NULL AND expires_at>now()
                    ORDER BY created_at DESC LIMIT 1 FOR UPDATE
                    """,
                    (user_id,),
                )
                row = cur.fetchone()
                if not row:
                    return None
                if int(row["attempts"] or 0) >= 8:
                    return None
                if not hmac.compare_digest(str(row["code_hash"]), code_hash):
                    cur.execute(
                        "UPDATE ih_email_verifications SET attempts=attempts+1 WHERE id=%s",
                        (row["id"],),
                    )
                    conn.commit()
                    return None
                cur.execute(
                    """
                    UPDATE ih_users SET email_verified=true,updated_at=now()
                    WHERE id=%s AND lower(email)=lower(%s)
                    """,
                    (row["user_id"], row["email"]),
                )
                if cur.rowcount != 1:
                    conn.rollback()
                    return None
                self.control._activate_free_account(cur, row["user_id"])
                cur.execute(
                    "UPDATE ih_email_verifications SET used_at=now() WHERE id=%s",
                    (row["id"],),
                )
            conn.commit()
            return dict(row)

    def put_pending_totp(self, user_id: str, encrypted_secret: str) -> None:
        self.ensure_schema()
        with self.control._connect() as conn, conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO ih_user_security(user_id,totp_secret_enc,totp_enabled,updated_at)
                VALUES (%s,%s,false,now())
                ON CONFLICT (user_id) DO UPDATE SET
                    totp_secret_enc=EXCLUDED.totp_secret_enc,
                    totp_enabled=false,
                    totp_confirmed_at=NULL,
                    last_totp_counter=NULL,
                    updated_at=now()
                WHERE ih_user_security.totp_enabled=false
                """,
                (user_id, encrypted_secret),
            )
            if cur.rowcount != 1:
                conn.rollback()
                raise ControlError(
                    "totp_already_enabled",
                    "disable the existing two-factor method before starting a new setup",
                    409,
                )
            cur.execute("DELETE FROM ih_2fa_recovery_codes WHERE user_id=%s", (user_id,))
            conn.commit()

    def totp_record(self, user_id: str) -> dict[str, Any] | None:
        self.ensure_schema()
        with self.control._connect() as conn, conn.cursor() as cur:
            cur.execute("SELECT * FROM ih_user_security WHERE user_id=%s", (user_id,))
            row = cur.fetchone()
            return dict(row) if row else None

    def enable_totp(self, user_id: str, counter: int, recovery_hashes: list[str]) -> None:
        self.ensure_schema()
        with self.control._connect() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    UPDATE ih_user_security SET
                        totp_enabled=true,totp_confirmed_at=now(),last_totp_counter=%s,updated_at=now()
                    WHERE user_id=%s AND totp_secret_enc IS NOT NULL AND totp_enabled=false
                    """,
                    (counter, user_id),
                )
                if cur.rowcount != 1:
                    raise ControlError("totp_setup_missing", "start TOTP setup first", 409)
                cur.execute("DELETE FROM ih_2fa_recovery_codes WHERE user_id=%s", (user_id,))
                for code_hash in recovery_hashes:
                    cur.execute(
                        """
                        INSERT INTO ih_2fa_recovery_codes(id,user_id,code_hash)
                        VALUES (%s,%s,%s)
                        """,
                        (self._new_id("rcv"), user_id, code_hash),
                    )
            conn.commit()

    def replace_recovery_codes(self, user_id: str, recovery_hashes: list[str]) -> None:
        self.ensure_schema()
        with self.control._connect() as conn:
            with conn.cursor() as cur:
                cur.execute("DELETE FROM ih_2fa_recovery_codes WHERE user_id=%s", (user_id,))
                for code_hash in recovery_hashes:
                    cur.execute(
                        "INSERT INTO ih_2fa_recovery_codes(id,user_id,code_hash) VALUES (%s,%s,%s)",
                        (self._new_id("rcv"), user_id, code_hash),
                    )
            conn.commit()

    def accept_totp_counter(self, user_id: str, counter: int) -> bool:
        self.ensure_schema()
        with self.control._connect() as conn, conn.cursor() as cur:
            cur.execute(
                """
                UPDATE ih_user_security
                SET last_totp_counter=%s,updated_at=now()
                WHERE user_id=%s AND totp_enabled=true
                  AND (last_totp_counter IS NULL OR last_totp_counter<%s)
                """,
                (counter, user_id, counter),
            )
            accepted = cur.rowcount == 1
            conn.commit()
            return accepted

    def consume_recovery_code(self, user_id: str, code_hash: str) -> bool:
        self.ensure_schema()
        with self.control._connect() as conn, conn.cursor() as cur:
            cur.execute(
                """
                UPDATE ih_2fa_recovery_codes SET used_at=now()
                WHERE user_id=%s AND code_hash=%s AND used_at IS NULL
                """,
                (user_id, code_hash),
            )
            accepted = cur.rowcount == 1
            conn.commit()
            return accepted

    def disable_totp(self, user_id: str) -> None:
        self.ensure_schema()
        with self.control._connect() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    UPDATE ih_user_security SET
                        totp_secret_enc=NULL,totp_enabled=false,totp_confirmed_at=NULL,
                        last_totp_counter=NULL,updated_at=now()
                    WHERE user_id=%s
                    """,
                    (user_id,),
                )
                cur.execute("DELETE FROM ih_2fa_recovery_codes WHERE user_id=%s", (user_id,))
            conn.commit()

    def create_login_challenge(
        self, *, user_id: str, token_hash: str, ttl_minutes: int = 10
    ) -> None:
        self.ensure_schema()
        with self.control._connect() as conn, conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO ih_login_challenges(id,user_id,token_hash,expires_at)
                VALUES (%s,%s,%s,%s)
                """,
                (
                    self._new_id("lch"),
                    user_id,
                    token_hash,
                    datetime.now(UTC) + timedelta(minutes=ttl_minutes),
                ),
            )
            conn.commit()

    def login_challenge(self, token_hash: str) -> dict[str, Any] | None:
        self.ensure_schema()
        with self.control._connect() as conn, conn.cursor() as cur:
            cur.execute(
                """
                SELECT * FROM ih_login_challenges
                WHERE token_hash=%s AND used_at IS NULL AND expires_at>now()
                """,
                (token_hash,),
            )
            row = cur.fetchone()
            return dict(row) if row else None

    def finish_login_challenge(self, challenge_id: str) -> bool:
        self.ensure_schema()
        with self.control._connect() as conn, conn.cursor() as cur:
            cur.execute(
                """
                UPDATE ih_login_challenges SET used_at=now()
                WHERE id=%s AND used_at IS NULL AND expires_at>now()
                """,
                (challenge_id,),
            )
            accepted = cur.rowcount == 1
            conn.commit()
            return accepted

    def email_send_allowed(
        self,
        user_id: str,
        event_type: str,
        *,
        min_interval_seconds: int = 60,
    ) -> bool:
        self.ensure_schema()
        interval = max(1, min(int(min_interval_seconds), 3600))
        with self.control._connect() as conn, conn.cursor() as cur:
            cur.execute(
                """
                SELECT NOT EXISTS (
                    SELECT 1 FROM ih_email_events
                    WHERE user_id=%s AND event_type=%s
                      AND created_at > now() - (%s * interval '1 second')
                ) AS allowed
                """,
                (user_id, event_type, interval),
            )
            row = cur.fetchone()
            return bool(row and row["allowed"])

    def claim_email_event(
        self,
        *,
        user_id: str | None,
        email: str,
        event_type: str,
        dedupe_key: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> str | None:
        self.ensure_schema()
        event_id = self._new_id("mail")
        encoded_metadata = json.dumps(metadata or {})
        with self.control._connect() as conn, conn.cursor() as cur:
            try:
                cur.execute(
                    """
                    INSERT INTO ih_email_events(
                        id,user_id,email,event_type,status,dedupe_key,metadata
                    ) VALUES (%s,%s,%s,%s,'queued',%s,%s::jsonb)
                    """,
                    (
                        event_id,
                        user_id,
                        email,
                        event_type,
                        dedupe_key,
                        encoded_metadata,
                    ),
                )
                conn.commit()
                return event_id
            except UniqueViolation:
                conn.rollback()
                if not dedupe_key:
                    raise
                cur.execute(
                    """
                    UPDATE ih_email_events SET
                        user_id=%s,email=%s,event_type=%s,status='queued',provider=NULL,
                        message_id=NULL,error=NULL,metadata=%s::jsonb,updated_at=now()
                    WHERE dedupe_key=%s AND status='failed'
                    RETURNING id
                    """,
                    (user_id, email, event_type, encoded_metadata, dedupe_key),
                )
                row = cur.fetchone()
                conn.commit()
                return str(row["id"]) if row else None

    def finish_email_event(
        self,
        event_id: str,
        *,
        status: str,
        provider: str | None = None,
        message_id: str | None = None,
        error: str | None = None,
    ) -> None:
        self.ensure_schema()
        with self.control._connect() as conn, conn.cursor() as cur:
            cur.execute(
                """
                UPDATE ih_email_events SET
                    status=%s,provider=%s,message_id=%s,error=%s,updated_at=now()
                WHERE id=%s
                """,
                (status, provider, message_id, error[:500] if error else None, event_id),
            )
            conn.commit()
