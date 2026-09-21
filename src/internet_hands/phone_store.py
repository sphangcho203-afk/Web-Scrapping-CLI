from __future__ import annotations

import json
import threading
import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

from .control_store import ControlError, ControlStore


PHONE_SECURITY_SCHEMA_SQL = r"""
CREATE TABLE IF NOT EXISTS ih_phone_identities (
    user_id text PRIMARY KEY REFERENCES ih_users(id) ON DELETE CASCADE,
    phone_e164 text NOT NULL,
    country_code integer,
    region_code text,
    number_type text,
    verified_at timestamptz,
    verification_provider text,
    carrier_name text,
    line_type text,
    risk_metadata jsonb NOT NULL DEFAULT '{}'::jsonb,
    updated_at timestamptz NOT NULL DEFAULT now()
);
CREATE UNIQUE INDEX IF NOT EXISTS ih_phone_identities_verified_number_idx
    ON ih_phone_identities(phone_e164)
    WHERE verified_at IS NOT NULL;

CREATE TABLE IF NOT EXISTS ih_phone_verifications (
    id text PRIMARY KEY,
    user_id text NOT NULL REFERENCES ih_users(id) ON DELETE CASCADE,
    phone_e164 text NOT NULL,
    provider text NOT NULL,
    provider_request_id text NOT NULL,
    channel text NOT NULL,
    status text NOT NULL DEFAULT 'pending',
    attempts integer NOT NULL DEFAULT 0,
    expires_at timestamptz NOT NULL,
    completed_at timestamptz,
    metadata jsonb NOT NULL DEFAULT '{}'::jsonb,
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS ih_phone_verifications_user_idx
    ON ih_phone_verifications(user_id, created_at DESC);
CREATE INDEX IF NOT EXISTS ih_phone_verifications_request_idx
    ON ih_phone_verifications(provider, provider_request_id);
"""


class PhoneIdentityStore:
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
                cur.execute(PHONE_SECURITY_SCHEMA_SQL)
                conn.commit()
            self._schema_ready = True

    def status(self, user_id: str) -> dict[str, Any]:
        self.ensure_schema()
        with self.control._connect() as conn, conn.cursor() as cur:
            cur.execute(
                """
                SELECT user_id,phone_e164,country_code,region_code,number_type,
                       verified_at,verification_provider,carrier_name,line_type,
                       risk_metadata,updated_at
                FROM ih_phone_identities
                WHERE user_id=%s
                """,
                (user_id,),
            )
            row = cur.fetchone()
            if row:
                return dict(row)
            return {
                "user_id": user_id,
                "phone_e164": None,
                "country_code": None,
                "region_code": None,
                "number_type": None,
                "verified_at": None,
                "verification_provider": None,
                "carrier_name": None,
                "line_type": None,
                "risk_metadata": {},
                "updated_at": None,
            }

    def send_allowed(
        self,
        user_id: str,
        *,
        min_interval_seconds: int = 60,
        hourly_limit: int = 5,
    ) -> bool:
        self.ensure_schema()
        interval = max(15, min(int(min_interval_seconds), 3600))
        hourly = max(1, min(int(hourly_limit), 20))
        with self.control._connect() as conn, conn.cursor() as cur:
            cur.execute(
                """
                SELECT
                    NOT EXISTS (
                        SELECT 1 FROM ih_phone_verifications
                        WHERE user_id=%s
                          AND created_at > now() - (%s * interval '1 second')
                    ) AS interval_ok,
                    (
                        SELECT count(*) FROM ih_phone_verifications
                        WHERE user_id=%s
                          AND created_at > now() - interval '1 hour'
                    ) < %s AS hourly_ok
                """,
                (user_id, interval, user_id, hourly),
            )
            row = cur.fetchone()
            return bool(row and row["interval_ok"] and row["hourly_ok"])

    def begin_verification(
        self,
        *,
        user_id: str,
        phone_e164: str,
        country_code: int,
        region_code: str | None,
        number_type: str,
        provider: str,
        provider_request_id: str,
        channel: str,
        metadata: dict[str, Any] | None = None,
        ttl_minutes: int = 10,
    ) -> dict[str, Any]:
        self.ensure_schema()
        verification_id = self._new_id("phv")
        expires_at = datetime.now(UTC) + timedelta(minutes=max(3, min(ttl_minutes, 30)))

        with self.control._connect() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    UPDATE ih_phone_verifications
                    SET status='superseded',updated_at=now()
                    WHERE user_id=%s
                      AND status='pending'
                      AND completed_at IS NULL
                    """,
                    (user_id,),
                )
                cur.execute(
                    """
                    INSERT INTO ih_phone_identities(
                        user_id,phone_e164,country_code,region_code,number_type,
                        verified_at,verification_provider,carrier_name,line_type,
                        risk_metadata,updated_at
                    )
                    VALUES (%s,%s,%s,%s,%s,NULL,NULL,NULL,NULL,'{}'::jsonb,now())
                    ON CONFLICT (user_id) DO UPDATE SET
                        phone_e164=EXCLUDED.phone_e164,
                        country_code=EXCLUDED.country_code,
                        region_code=EXCLUDED.region_code,
                        number_type=EXCLUDED.number_type,
                        verified_at=NULL,
                        verification_provider=NULL,
                        carrier_name=NULL,
                        line_type=NULL,
                        risk_metadata='{}'::jsonb,
                        updated_at=now()
                    """,
                    (user_id, phone_e164, country_code, region_code, number_type),
                )
                cur.execute(
                    """
                    INSERT INTO ih_phone_verifications(
                        id,user_id,phone_e164,provider,provider_request_id,
                        channel,status,attempts,expires_at,metadata
                    )
                    VALUES (%s,%s,%s,%s,%s,%s,'pending',0,%s,%s::jsonb)
                    """,
                    (
                        verification_id,
                        user_id,
                        phone_e164,
                        provider,
                        provider_request_id,
                        channel,
                        expires_at,
                        json.dumps(metadata or {}),
                    ),
                )
            conn.commit()

        return {
            "id": verification_id,
            "user_id": user_id,
            "phone_e164": phone_e164,
            "provider": provider,
            "provider_request_id": provider_request_id,
            "channel": channel,
            "status": "pending",
            "attempts": 0,
            "expires_at": expires_at,
            "metadata": metadata or {},
        }

    def pending(self, user_id: str) -> dict[str, Any] | None:
        self.ensure_schema()
        with self.control._connect() as conn, conn.cursor() as cur:
            cur.execute(
                """
                SELECT * FROM ih_phone_verifications
                WHERE user_id=%s
                  AND status='pending'
                  AND completed_at IS NULL
                  AND expires_at>now()
                ORDER BY created_at DESC
                LIMIT 1
                """,
                (user_id,),
            )
            row = cur.fetchone()
            return dict(row) if row else None

    def record_failed_attempt(
        self,
        verification_id: str,
        *,
        provider_status: str | None = None,
        max_attempts: int = 5,
    ) -> int:
        self.ensure_schema()
        with self.control._connect() as conn, conn.cursor() as cur:
            cur.execute(
                """
                UPDATE ih_phone_verifications
                SET attempts=attempts+1,
                    status=CASE
                        WHEN attempts+1 >= %s THEN 'failed'
                        ELSE status
                    END,
                    metadata = CASE
                        WHEN %s IS NULL THEN metadata
                        ELSE metadata || jsonb_build_object('last_provider_status', %s::text)
                    END,
                    updated_at=now()
                WHERE id=%s
                  AND completed_at IS NULL
                RETURNING attempts
                """,
                (max_attempts, provider_status, provider_status, verification_id),
            )
            row = cur.fetchone()
            conn.commit()
            return int(row["attempts"]) if row else max_attempts

    def complete(
        self,
        *,
        verification_id: str,
        user_id: str,
        provider: str,
        metadata: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        self.ensure_schema()
        with self.control._connect() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT * FROM ih_phone_verifications
                    WHERE id=%s AND user_id=%s
                      AND status='pending'
                      AND completed_at IS NULL
                      AND expires_at>now()
                    FOR UPDATE
                    """,
                    (verification_id, user_id),
                )
                row = cur.fetchone()
                if not row:
                    raise ControlError(
                        "phone_verification_expired",
                        "phone verification is missing or expired",
                        409,
                    )

                cur.execute(
                    """
                    SELECT user_id FROM ih_phone_identities
                    WHERE phone_e164=%s AND verified_at IS NOT NULL AND user_id<>%s
                    LIMIT 1
                    """,
                    (row["phone_e164"], user_id),
                )
                if cur.fetchone():
                    raise ControlError(
                        "phone_already_verified",
                        "this phone number is already verified on another account",
                        409,
                    )

                now = datetime.now(UTC)
                cur.execute(
                    """
                    UPDATE ih_phone_verifications
                    SET status='verified',completed_at=%s,updated_at=now(),
                        metadata=metadata || %s::jsonb
                    WHERE id=%s
                    """,
                    (now, json.dumps(metadata or {}), verification_id),
                )
                cur.execute(
                    """
                    UPDATE ih_phone_identities
                    SET verified_at=%s,verification_provider=%s,updated_at=now()
                    WHERE user_id=%s AND phone_e164=%s
                    """,
                    (now, provider, user_id, row["phone_e164"]),
                )
            conn.commit()
            return {**dict(row), "status": "verified", "completed_at": now}

    def update_intelligence(
        self,
        user_id: str,
        *,
        carrier_name: str | None,
        line_type: str | None,
        risk_metadata: dict[str, Any],
    ) -> None:
        self.ensure_schema()
        with self.control._connect() as conn, conn.cursor() as cur:
            cur.execute(
                """
                UPDATE ih_phone_identities
                SET carrier_name=%s,line_type=%s,risk_metadata=%s::jsonb,updated_at=now()
                WHERE user_id=%s AND verified_at IS NOT NULL
                """,
                (carrier_name, line_type, json.dumps(risk_metadata), user_id),
            )
            conn.commit()

    def remove(self, user_id: str) -> bool:
        self.ensure_schema()
        with self.control._connect() as conn, conn.cursor() as cur:
            cur.execute("DELETE FROM ih_phone_identities WHERE user_id=%s", (user_id,))
            deleted = cur.rowcount == 1
            cur.execute(
                """
                UPDATE ih_phone_verifications
                SET status='removed',updated_at=now()
                WHERE user_id=%s AND status='pending'
                """,
                (user_id,),
            )
            conn.commit()
            return deleted
