from __future__ import annotations

import json
import os
import secrets
import threading
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any

import psycopg
from psycopg.errors import UniqueViolation
from psycopg.rows import dict_row

from .capability_economics import estimate_call

SCHEMA_SQL = r"""
CREATE TABLE IF NOT EXISTS ih_users (
    id text PRIMARY KEY,
    email text NOT NULL,
    password_hash text,
    github_id text UNIQUE,
    display_name text,
    avatar_url text,
    email_verified boolean NOT NULL DEFAULT false,
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now()
);
CREATE UNIQUE INDEX IF NOT EXISTS ih_users_email_lower_idx ON ih_users ((lower(email)));

CREATE TABLE IF NOT EXISTS ih_sessions (
    id text PRIMARY KEY,
    user_id text NOT NULL REFERENCES ih_users(id) ON DELETE CASCADE,
    token_hash text NOT NULL UNIQUE,
    expires_at timestamptz NOT NULL,
    created_at timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS ih_sessions_user_idx ON ih_sessions(user_id);

CREATE TABLE IF NOT EXISTS ih_plans (
    slug text PRIMARY KEY,
    name text NOT NULL,
    monthly_price_inr integer NOT NULL,
    included_credits integer NOT NULL,
    rpm_limit integer NOT NULL,
    concurrent_limit integer NOT NULL,
    api_key_limit integer NOT NULL,
    monitor_limit integer NOT NULL,
    browser_enabled boolean NOT NULL DEFAULT false,
    sandbox_enabled boolean NOT NULL DEFAULT false,
    priority integer NOT NULL DEFAULT 0,
    metadata jsonb NOT NULL DEFAULT '{}'::jsonb,
    active boolean NOT NULL DEFAULT true
);

CREATE TABLE IF NOT EXISTS ih_subscriptions (
    id text PRIMARY KEY,
    user_id text NOT NULL REFERENCES ih_users(id) ON DELETE CASCADE,
    plan_slug text NOT NULL REFERENCES ih_plans(slug),
    status text NOT NULL,
    current_period_start timestamptz NOT NULL,
    current_period_end timestamptz NOT NULL,
    provider text,
    provider_subscription_id text,
    cancel_at_period_end boolean NOT NULL DEFAULT false,
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS ih_subscriptions_user_idx ON ih_subscriptions(user_id, status);

CREATE TABLE IF NOT EXISTS ih_wallets (
    user_id text PRIMARY KEY REFERENCES ih_users(id) ON DELETE CASCADE,
    monthly_credits integer NOT NULL DEFAULT 0,
    purchased_credits integer NOT NULL DEFAULT 0,
    reserved_credits integer NOT NULL DEFAULT 0,
    updated_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS ih_credit_ledger (
    id text PRIMARY KEY,
    user_id text NOT NULL REFERENCES ih_users(id) ON DELETE CASCADE,
    amount integer NOT NULL,
    bucket text NOT NULL,
    kind text NOT NULL,
    source text NOT NULL,
    reference_id text,
    metadata jsonb NOT NULL DEFAULT '{}'::jsonb,
    created_at timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS ih_credit_ledger_user_idx ON ih_credit_ledger(user_id, created_at DESC);

CREATE TABLE IF NOT EXISTS ih_api_keys (
    id text PRIMARY KEY,
    user_id text NOT NULL REFERENCES ih_users(id) ON DELETE CASCADE,
    name text NOT NULL,
    prefix text NOT NULL,
    key_hash text NOT NULL UNIQUE,
    scopes jsonb NOT NULL DEFAULT '[]'::jsonb,
    environment text NOT NULL DEFAULT 'live',
    last_used_at timestamptz,
    expires_at timestamptz,
    revoked_at timestamptz,
    created_at timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS ih_api_keys_user_idx ON ih_api_keys(user_id, created_at DESC);

CREATE TABLE IF NOT EXISTS ih_usage_events (
    id text PRIMARY KEY,
    user_id text NOT NULL REFERENCES ih_users(id) ON DELETE CASCADE,
    api_key_id text REFERENCES ih_api_keys(id) ON DELETE SET NULL,
    request_id text NOT NULL UNIQUE,
    tool_ref text,
    capability text,
    provider text,
    status text NOT NULL,
    credits_charged integer NOT NULL DEFAULT 0,
    latency_ms integer,
    input_bytes integer NOT NULL DEFAULT 0,
    output_bytes integer NOT NULL DEFAULT 0,
    metadata jsonb NOT NULL DEFAULT '{}'::jsonb,
    created_at timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS ih_usage_user_time_idx ON ih_usage_events(user_id, created_at DESC);
CREATE INDEX IF NOT EXISTS ih_usage_key_time_idx ON ih_usage_events(api_key_id, created_at DESC);

CREATE TABLE IF NOT EXISTS ih_monitors (
    id text PRIMARY KEY,
    user_id text NOT NULL REFERENCES ih_users(id) ON DELETE CASCADE,
    name text NOT NULL,
    type text NOT NULL,
    target text NOT NULL,
    interval_minutes integer NOT NULL,
    enabled boolean NOT NULL DEFAULT true,
    last_status text,
    last_checked_at timestamptz,
    next_check_at timestamptz,
    config jsonb NOT NULL DEFAULT '{}'::jsonb,
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS ih_monitors_user_idx ON ih_monitors(user_id, created_at DESC);

CREATE TABLE IF NOT EXISTS ih_monitor_runs (
    id text PRIMARY KEY,
    monitor_id text NOT NULL REFERENCES ih_monitors(id) ON DELETE CASCADE,
    status text NOT NULL,
    latency_ms integer,
    http_status integer,
    summary text,
    diff jsonb,
    credits_charged integer NOT NULL DEFAULT 0,
    created_at timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS ih_monitor_runs_monitor_idx ON ih_monitor_runs(monitor_id, created_at DESC);

CREATE TABLE IF NOT EXISTS ih_credit_packs (
    slug text PRIMARY KEY,
    name text NOT NULL,
    price_inr integer NOT NULL,
    credits integer NOT NULL,
    active boolean NOT NULL DEFAULT true
);

CREATE TABLE IF NOT EXISTS ih_payments (
    id text PRIMARY KEY,
    user_id text NOT NULL REFERENCES ih_users(id) ON DELETE CASCADE,
    provider text NOT NULL DEFAULT 'razorpay',
    order_id text UNIQUE,
    payment_id text UNIQUE,
    amount_paise integer NOT NULL,
    currency text NOT NULL DEFAULT 'INR',
    status text NOT NULL,
    purpose text NOT NULL,
    plan_slug text REFERENCES ih_plans(slug),
    credit_pack_slug text REFERENCES ih_credit_packs(slug),
    metadata jsonb NOT NULL DEFAULT '{}'::jsonb,
    created_at timestamptz NOT NULL DEFAULT now(),
    paid_at timestamptz
);
CREATE INDEX IF NOT EXISTS ih_payments_user_idx ON ih_payments(user_id, created_at DESC);

CREATE TABLE IF NOT EXISTS ih_oauth_authorization_codes (
    id text PRIMARY KEY,
    user_id text NOT NULL REFERENCES ih_users(id) ON DELETE CASCADE,
    api_key_id text NOT NULL REFERENCES ih_api_keys(id) ON DELETE CASCADE,
    client_id text NOT NULL,
    redirect_uri text NOT NULL,
    code_hash text NOT NULL UNIQUE,
    code_challenge text NOT NULL,
    scopes jsonb NOT NULL DEFAULT '[]'::jsonb,
    expires_at timestamptz NOT NULL,
    used_at timestamptz,
    created_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS ih_oauth_tokens (
    id text PRIMARY KEY,
    user_id text NOT NULL REFERENCES ih_users(id) ON DELETE CASCADE,
    api_key_id text NOT NULL REFERENCES ih_api_keys(id) ON DELETE CASCADE,
    client_id text NOT NULL,
    access_token_hash text NOT NULL UNIQUE,
    refresh_token_hash text NOT NULL UNIQUE,
    scopes jsonb NOT NULL DEFAULT '[]'::jsonb,
    access_expires_at timestamptz NOT NULL,
    refresh_expires_at timestamptz NOT NULL,
    revoked_at timestamptz,
    created_at timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS ih_oauth_tokens_user_idx ON ih_oauth_tokens(user_id, created_at DESC);

CREATE TABLE IF NOT EXISTS ih_webhook_events (
    id text PRIMARY KEY,
    provider text NOT NULL,
    event_id text NOT NULL,
    event_type text NOT NULL,
    signature_valid boolean NOT NULL,
    payload_hash text NOT NULL,
    status text NOT NULL,
    processed_at timestamptz NOT NULL DEFAULT now(),
    UNIQUE(provider, event_id)
);

CREATE TABLE IF NOT EXISTS ih_password_resets (
    id text PRIMARY KEY,
    user_id text NOT NULL REFERENCES ih_users(id) ON DELETE CASCADE,
    token_hash text NOT NULL UNIQUE,
    expires_at timestamptz NOT NULL,
    used_at timestamptz,
    created_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS ih_tool_costs (
    pattern text PRIMARY KEY,
    base_credits integer NOT NULL,
    metadata jsonb NOT NULL DEFAULT '{}'::jsonb,
    active boolean NOT NULL DEFAULT true
);
"""

PLAN_ROWS = [
    ("free", "Free", 0, 2500, 10, 1, 1, 1, False, False, 0),
    ("builder", "Builder", 499, 25000, 60, 4, 5, 10, True, False, 10),
    ("pro", "Pro", 1499, 150000, 240, 10, 20, 50, True, True, 20),
    ("scale", "Scale", 4999, 750000, 600, 20, 100, 250, True, True, 30),
]

CREDIT_PACK_ROWS = [
    ("starter-5k", "5K credits", 99, 5000),
    ("builder-25k", "25K credits", 399, 25000),
    ("pro-75k", "75K credits", 999, 75000),
    ("scale-250k", "250K credits", 2499, 250000),
]

TOOL_COST_ROWS = [
    ("account_*", 0, {"category": "account"}),
    ("monitors_list", 0, {"category": "account"}),
    ("monitor_get", 0, {"category": "account"}),
    ("mesh_providers", 1, {"category": "discovery"}),
    ("mesh_search", 1, {"category": "discovery"}),
    ("mesh_describe*", 1, {"category": "discovery"}),
    ("mesh_capabilities", 1, {"category": "discovery"}),
    ("gaming_capabilities", 1, {"category": "gaming"}),
    ("gaming_profile_plan", 1, {"category": "gaming"}),
    ("gaming_profile", 5, {"category": "gaming"}),
    ("gaming_intel", 2, {"category": "gaming"}),
    ("sandbox_browser_*", 2, {"category": "browser", "per_minute": 5}),
    ("sandbox_*", 2, {"category": "sandbox", "per_minute": 10}),
    ("mesh_execute", 3, {"category": "provider"}),
    ("mesh_batch_execute", 10, {"category": "provider"}),
    ("mesh_job_status", 1, {"category": "provider"}),
    ("mesh_results", 1, {"category": "provider"}),
    ("playground:crawl", 2, {"category": "playground"}),
    ("*", 1, {"category": "default"}),
]


class ControlError(RuntimeError):
    def __init__(self, code: str, detail: str, status_code: int = 400) -> None:
        super().__init__(detail)
        self.code = code
        self.detail = detail
        self.status_code = status_code


@dataclass(slots=True)
class AuthIdentity:
    user_id: str
    api_key_id: str | None
    scopes: list[str]
    plan_slug: str
    rpm_limit: int
    source: str


class ControlStore:
    def __init__(self, dsn: str | None = None) -> None:
        self.dsn = dsn or os.getenv("INTERNET_HANDS_CONTROL_POSTGRES_DSN") or os.getenv(
            "INTERNET_HANDS_POSTGRES_DSN"
        )
        self._schema_ready = False
        self._schema_lock = threading.Lock()

    @property
    def configured(self) -> bool:
        return bool(self.dsn)

    def _connect(self):
        if not self.dsn:
            raise ControlError("control_plane_unavailable", "control database is not configured", 503)
        return psycopg.connect(self.dsn, row_factory=dict_row)

    def ensure_schema(self) -> None:
        if self._schema_ready:
            return
        with self._schema_lock:
            if self._schema_ready:
                return
            with self._connect() as conn:
                with conn.cursor() as cur:
                    cur.execute(SCHEMA_SQL)
                    for row in PLAN_ROWS:
                        cur.execute(
                            """
                            INSERT INTO ih_plans(
                                slug,name,monthly_price_inr,included_credits,rpm_limit,
                                concurrent_limit,api_key_limit,monitor_limit,browser_enabled,
                                sandbox_enabled,priority
                            ) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
                            ON CONFLICT (slug) DO UPDATE SET
                                name=EXCLUDED.name,
                                monthly_price_inr=EXCLUDED.monthly_price_inr,
                                included_credits=EXCLUDED.included_credits,
                                rpm_limit=EXCLUDED.rpm_limit,
                                concurrent_limit=EXCLUDED.concurrent_limit,
                                api_key_limit=EXCLUDED.api_key_limit,
                                monitor_limit=EXCLUDED.monitor_limit,
                                browser_enabled=EXCLUDED.browser_enabled,
                                sandbox_enabled=EXCLUDED.sandbox_enabled,
                                priority=EXCLUDED.priority
                            """,
                            row,
                        )
                    for row in CREDIT_PACK_ROWS:
                        cur.execute(
                            """
                            INSERT INTO ih_credit_packs(slug,name,price_inr,credits)
                            VALUES (%s,%s,%s,%s)
                            ON CONFLICT (slug) DO UPDATE SET
                                name=EXCLUDED.name, price_inr=EXCLUDED.price_inr,
                                credits=EXCLUDED.credits, active=true
                            """,
                            row,
                        )
                    for pattern, base, metadata in TOOL_COST_ROWS:
                        cur.execute(
                            """
                            INSERT INTO ih_tool_costs(pattern,base_credits,metadata)
                            VALUES (%s,%s,%s::jsonb)
                            ON CONFLICT (pattern) DO UPDATE SET
                                base_credits=EXCLUDED.base_credits,
                                metadata=EXCLUDED.metadata,
                                active=true
                            """,
                            (pattern, base, json.dumps(metadata)),
                        )
                conn.commit()
            self._schema_ready = True

    def _new_id(self, prefix: str) -> str:
        return f"{prefix}_{uuid.uuid4().hex}"

    def create_user(self, *, email: str, password_hash: str, display_name: str | None) -> dict[str, Any]:
        self.ensure_schema()
        user_id = self._new_id("usr")
        try:
            with self._connect() as conn:
                with conn.cursor() as cur:
                    cur.execute(
                        """
                        INSERT INTO ih_users(id,email,password_hash,display_name)
                        VALUES (%s,%s,%s,%s)
                        RETURNING id,email,display_name,avatar_url,created_at
                        """,
                        (user_id, email.strip().lower(), password_hash, display_name),
                    )
                    user = cur.fetchone()
                conn.commit()
                assert user is not None
                return dict(user)
        except UniqueViolation as exc:
            raise ControlError("email_in_use", "an account with this email already exists", 409) from exc

    def _activate_free_account(self, cur: Any, user_id: str) -> None:
        """Provision account resources once, inside the caller's transaction."""
        now = datetime.now(UTC)
        cur.execute(
            """
            INSERT INTO ih_wallets(user_id,monthly_credits)
            VALUES (%s,2500)
            ON CONFLICT (user_id) DO NOTHING
            """,
            (user_id,),
        )
        cur.execute(
            """
            INSERT INTO ih_credit_ledger(
                id,user_id,amount,bucket,kind,source,reference_id
            )
            SELECT %s,%s,2500,'monthly','grant','signup','free'
            WHERE NOT EXISTS (
                SELECT 1 FROM ih_credit_ledger
                WHERE user_id=%s AND kind='grant' AND source='signup'
            )
            """,
            (self._new_id("led"), user_id, user_id),
        )
        cur.execute(
            """
            INSERT INTO ih_subscriptions(
                id,user_id,plan_slug,status,current_period_start,current_period_end,provider
            )
            SELECT %s,%s,'free','active',%s,%s,'internal'
            WHERE NOT EXISTS (
                SELECT 1 FROM ih_subscriptions
                WHERE user_id=%s AND status='active'
            )
            """,
            (self._new_id("sub"), user_id, now, now + timedelta(days=30), user_id),
        )

    def activate_free_account(self, user_id: str) -> None:
        self.ensure_schema()
        with self._connect() as conn, conn.cursor() as cur:
            self._activate_free_account(cur, user_id)
            conn.commit()

    def get_user_by_email(self, email: str) -> dict[str, Any] | None:
        self.ensure_schema()
        with self._connect() as conn, conn.cursor() as cur:
            cur.execute("SELECT * FROM ih_users WHERE lower(email)=lower(%s)", (email.strip(),))
            row = cur.fetchone()
            return dict(row) if row else None

    def get_user(self, user_id: str) -> dict[str, Any] | None:
        self.ensure_schema()
        with self._connect() as conn, conn.cursor() as cur:
            cur.execute(
                """
                SELECT id,email,display_name,avatar_url,email_verified,created_at,
                       (github_id IS NOT NULL) AS github_connected
                FROM ih_users WHERE id=%s
                """,
                (user_id,),
            )
            row = cur.fetchone()
            return dict(row) if row else None

    def upsert_github_user(
        self, *, github_id: str, email: str, display_name: str | None, avatar_url: str | None
    ) -> dict[str, Any]:
        self.ensure_schema()
        with self._connect() as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT * FROM ih_users WHERE github_id=%s", (github_id,))
                existing = cur.fetchone()
                if existing:
                    cur.execute(
                        "UPDATE ih_users SET display_name=COALESCE(%s,display_name), avatar_url=COALESCE(%s,avatar_url), updated_at=now() WHERE id=%s RETURNING *",
                        (display_name, avatar_url, existing["id"]),
                    )
                    row = cur.fetchone()
                    conn.commit()
                    assert row is not None
                    return dict(row)
                cur.execute("SELECT * FROM ih_users WHERE lower(email)=lower(%s)", (email,))
                by_email = cur.fetchone()
                if by_email:
                    cur.execute(
                        "UPDATE ih_users SET github_id=%s, display_name=COALESCE(%s,display_name), avatar_url=COALESCE(%s,avatar_url), updated_at=now() WHERE id=%s RETURNING *",
                        (github_id, display_name, avatar_url, by_email["id"]),
                    )
                    row = cur.fetchone()
                    conn.commit()
                    assert row is not None
                    return dict(row)
                user_id = self._new_id("usr")
                cur.execute(
                    """
                    INSERT INTO ih_users(id,email,github_id,display_name,avatar_url,email_verified)
                    VALUES (%s,%s,%s,%s,%s,false) RETURNING *
                    """,
                    (user_id, email.lower(), github_id, display_name, avatar_url),
                )
                row = cur.fetchone()
            conn.commit()
            assert row is not None
            return dict(row)

    def create_session(self, *, user_id: str, token_hash: str, ttl_days: int = 30) -> None:
        self.ensure_schema()
        with self._connect() as conn, conn.cursor() as cur:
            cur.execute(
                "INSERT INTO ih_sessions(id,user_id,token_hash,expires_at) VALUES (%s,%s,%s,%s)",
                (self._new_id("ses"), user_id, token_hash, datetime.now(UTC) + timedelta(days=ttl_days)),
            )
            conn.commit()

    def session_user(self, token_hash: str) -> dict[str, Any] | None:
        self.ensure_schema()
        with self._connect() as conn, conn.cursor() as cur:
            cur.execute(
                """
                SELECT u.id,u.email,u.display_name,u.avatar_url,u.email_verified,u.created_at,
                       (u.github_id IS NOT NULL) AS github_connected
                FROM ih_sessions s JOIN ih_users u ON u.id=s.user_id
                WHERE s.token_hash=%s AND s.expires_at>now()
                """,
                (token_hash,),
            )
            row = cur.fetchone()
            return dict(row) if row else None

    def delete_session(self, token_hash: str) -> None:
        self.ensure_schema()
        with self._connect() as conn, conn.cursor() as cur:
            cur.execute("DELETE FROM ih_sessions WHERE token_hash=%s", (token_hash,))
            conn.commit()

    def list_sessions(self, user_id: str, current_token_hash: str) -> list[dict[str, Any]]:
        self.ensure_schema()
        with self._connect() as conn, conn.cursor() as cur:
            cur.execute(
                """
                SELECT id,created_at,expires_at,(token_hash=%s) AS current
                FROM ih_sessions
                WHERE user_id=%s AND expires_at>now()
                ORDER BY created_at DESC
                """,
                (current_token_hash, user_id),
            )
            return [dict(row) for row in cur.fetchall()]

    def revoke_session(self, user_id: str, session_id: str) -> bool:
        self.ensure_schema()
        with self._connect() as conn, conn.cursor() as cur:
            cur.execute("DELETE FROM ih_sessions WHERE id=%s AND user_id=%s", (session_id, user_id))
            changed = cur.rowcount == 1
            conn.commit()
            return changed

    def revoke_all_sessions(self, user_id: str) -> None:
        self.ensure_schema()
        with self._connect() as conn, conn.cursor() as cur:
            cur.execute("DELETE FROM ih_sessions WHERE user_id=%s", (user_id,))
            conn.commit()

    def update_display_name(self, user_id: str, display_name: str) -> dict[str, Any]:
        self.ensure_schema()
        with self._connect() as conn, conn.cursor() as cur:
            cur.execute(
                """
                UPDATE ih_users SET display_name=%s,updated_at=now()
                WHERE id=%s
                RETURNING id,email,display_name,avatar_url,email_verified,created_at,
                          (github_id IS NOT NULL) AS github_connected
                """,
                (display_name, user_id),
            )
            row = cur.fetchone()
            conn.commit()
            if not row:
                raise ControlError("account_not_found", "account not found", 404)
            return dict(row)

    def update_password_and_revoke_sessions(self, user_id: str, password_hash: str) -> None:
        self.ensure_schema()
        with self._connect() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "UPDATE ih_users SET password_hash=%s,updated_at=now() WHERE id=%s",
                    (password_hash, user_id),
                )
                if cur.rowcount != 1:
                    raise ControlError("account_not_found", "account not found", 404)
                cur.execute("DELETE FROM ih_sessions WHERE user_id=%s", (user_id,))
            conn.commit()

    def list_plans(self) -> list[dict[str, Any]]:
        self.ensure_schema()
        with self._connect() as conn, conn.cursor() as cur:
            cur.execute("SELECT * FROM ih_plans WHERE active=true ORDER BY monthly_price_inr")
            return [dict(row) for row in cur.fetchall()]

    def list_credit_packs(self) -> list[dict[str, Any]]:
        self.ensure_schema()
        with self._connect() as conn, conn.cursor() as cur:
            cur.execute("SELECT * FROM ih_credit_packs WHERE active=true ORDER BY price_inr")
            return [dict(row) for row in cur.fetchall()]

    def account_snapshot(self, user_id: str) -> dict[str, Any]:
        self.ensure_schema()
        with self._connect() as conn, conn.cursor() as cur:
            cur.execute(
                """
                SELECT u.id,u.email,u.display_name,u.avatar_url,
                       w.monthly_credits,w.purchased_credits,w.reserved_credits,
                       p.slug AS plan_slug,p.name AS plan_name,p.rpm_limit,p.concurrent_limit,
                       p.api_key_limit,p.monitor_limit,p.browser_enabled,p.sandbox_enabled,
                       s.current_period_end,s.cancel_at_period_end
                FROM ih_users u
                JOIN ih_wallets w ON w.user_id=u.id
                LEFT JOIN LATERAL (
                    SELECT * FROM ih_subscriptions sx
                    WHERE sx.user_id=u.id AND sx.status='active'
                    ORDER BY sx.created_at DESC LIMIT 1
                ) s ON true
                LEFT JOIN ih_plans p ON p.slug=COALESCE(s.plan_slug,'free')
                WHERE u.id=%s
                """,
                (user_id,),
            )
            row = cur.fetchone()
            if not row:
                raise ControlError("account_not_found", "account not found", 404)
            return dict(row)

    def create_api_key(
        self,
        *,
        user_id: str,
        name: str,
        prefix: str,
        key_hash: str,
        scopes: list[str],
        environment: str,
    ) -> dict[str, Any]:
        self.ensure_schema()
        account = self.account_snapshot(user_id)
        with self._connect() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT count(*) AS n FROM ih_api_keys WHERE user_id=%s AND revoked_at IS NULL",
                    (user_id,),
                )
                count = int(cur.fetchone()["n"])
                if count >= int(account["api_key_limit"]):
                    raise ControlError("api_key_limit", "API key limit reached for current plan", 403)
                key_id = self._new_id("key")
                cur.execute(
                    """
                    INSERT INTO ih_api_keys(id,user_id,name,prefix,key_hash,scopes,environment)
                    VALUES (%s,%s,%s,%s,%s,%s::jsonb,%s)
                    RETURNING id,name,prefix,scopes,environment,last_used_at,expires_at,revoked_at,created_at
                    """,
                    (key_id, user_id, name, prefix, key_hash, json.dumps(scopes), environment),
                )
                row = cur.fetchone()
            conn.commit()
            assert row is not None
            return dict(row)

    def list_api_keys(self, user_id: str) -> list[dict[str, Any]]:
        self.ensure_schema()
        with self._connect() as conn, conn.cursor() as cur:
            cur.execute(
                """
                SELECT id,name,prefix,scopes,environment,last_used_at,expires_at,revoked_at,created_at
                FROM ih_api_keys WHERE user_id=%s ORDER BY created_at DESC
                """,
                (user_id,),
            )
            return [dict(row) for row in cur.fetchall()]

    def revoke_api_key(self, user_id: str, key_id: str) -> bool:
        self.ensure_schema()
        with self._connect() as conn, conn.cursor() as cur:
            cur.execute(
                "UPDATE ih_api_keys SET revoked_at=now() WHERE id=%s AND user_id=%s AND revoked_at IS NULL",
                (key_id, user_id),
            )
            changed = cur.rowcount > 0
            conn.commit()
            return changed

    def _identity_from_key_row(self, row: dict[str, Any], source: str) -> AuthIdentity:
        return AuthIdentity(
            user_id=row["user_id"],
            api_key_id=row["api_key_id"],
            scopes=list(row.get("scopes") or []),
            plan_slug=row["plan_slug"],
            rpm_limit=int(row["rpm_limit"]),
            source=source,
        )

    def api_key_identity_for_user(self, user_id: str, key_id: str) -> AuthIdentity | None:
        """Resolve one active API key owned by a signed-in user for first-party playground use."""
        self.ensure_schema()
        with self._connect() as conn, conn.cursor() as cur:
            cur.execute(
                """
                SELECT k.user_id,k.id AS api_key_id,k.scopes,p.slug AS plan_slug,p.rpm_limit
                FROM ih_api_keys k
                LEFT JOIN LATERAL (
                    SELECT plan_slug FROM ih_subscriptions s
                    WHERE s.user_id=k.user_id AND s.status='active'
                    ORDER BY s.created_at DESC LIMIT 1
                ) s ON true
                JOIN ih_plans p ON p.slug=COALESCE(s.plan_slug,'free')
                WHERE k.id=%s AND k.user_id=%s AND k.revoked_at IS NULL
                  AND (k.expires_at IS NULL OR k.expires_at>now())
                """,
                (key_id, user_id),
            )
            row = cur.fetchone()
            if not row:
                return None
            cur.execute("UPDATE ih_api_keys SET last_used_at=now() WHERE id=%s", (key_id,))
            conn.commit()
            return self._identity_from_key_row(dict(row), "api_key")


    def authenticate_api_key(self, key_hash: str) -> AuthIdentity | None:
        self.ensure_schema()
        with self._connect() as conn, conn.cursor() as cur:
            cur.execute(
                """
                SELECT k.user_id,k.id AS api_key_id,k.scopes,p.slug AS plan_slug,p.rpm_limit
                FROM ih_api_keys k
                LEFT JOIN LATERAL (
                    SELECT plan_slug FROM ih_subscriptions s
                    WHERE s.user_id=k.user_id AND s.status='active'
                    ORDER BY s.created_at DESC LIMIT 1
                ) s ON true
                JOIN ih_plans p ON p.slug=COALESCE(s.plan_slug,'free')
                WHERE k.key_hash=%s AND k.revoked_at IS NULL
                  AND (k.expires_at IS NULL OR k.expires_at>now())
                """,
                (key_hash,),
            )
            row = cur.fetchone()
            if not row:
                return None
            cur.execute("UPDATE ih_api_keys SET last_used_at=now() WHERE id=%s", (row["api_key_id"],))
            conn.commit()
            return self._identity_from_key_row(dict(row), "api_key")

    def authenticate_access_token(self, token_hash: str) -> AuthIdentity | None:
        self.ensure_schema()
        with self._connect() as conn, conn.cursor() as cur:
            cur.execute(
                """
                SELECT t.user_id,t.api_key_id,t.scopes,p.slug AS plan_slug,p.rpm_limit
                FROM ih_oauth_tokens t
                LEFT JOIN LATERAL (
                    SELECT plan_slug FROM ih_subscriptions s
                    WHERE s.user_id=t.user_id AND s.status='active'
                    ORDER BY s.created_at DESC LIMIT 1
                ) s ON true
                JOIN ih_plans p ON p.slug=COALESCE(s.plan_slug,'free')
                WHERE t.access_token_hash=%s AND t.revoked_at IS NULL AND t.access_expires_at>now()
                """,
                (token_hash,),
            )
            row = cur.fetchone()
            return self._identity_from_key_row(dict(row), "oauth") if row else None

    def quote_tool_call(
        self,
        *,
        identity: AuthIdentity,
        tool_name: str,
        arguments: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        estimate = estimate_call(tool_name, arguments, identity.plan_slug)
        quote = estimate.to_dict()
        if not estimate.allowed:
            raise ControlError(
                "plan_restricted",
                estimate.reason or "tool is unavailable on the current plan",
                403,
            )
        return quote

    def tool_cost(
        self,
        tool_name: str,
        arguments: dict[str, Any] | None = None,
        *,
        plan_slug: str = "free",
    ) -> int:
        estimate = estimate_call(tool_name, arguments, plan_slug)
        if not estimate.allowed:
            raise ControlError(
                "plan_restricted",
                estimate.reason or "tool is unavailable on the current plan",
                403,
            )
        return int(estimate.credits)

    def reserve_tool_call(
        self,
        *,
        identity: AuthIdentity,
        request_id: str,
        tool_name: str,
        arguments: dict[str, Any] | None,
        input_bytes: int,
    ) -> int:
        self.ensure_schema()
        quote = self.quote_tool_call(
            identity=identity,
            tool_name=tool_name,
            arguments=arguments,
        )
        reserved = int(quote["credits"])
        provider = None
        if arguments:
            ref = str(arguments.get("ref") or "")
            if ":" in ref:
                provider = ref.split(":", 1)[0]

        with self._connect() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT count(*) AS n FROM ih_usage_events WHERE user_id=%s AND created_at>now()-interval '1 minute'",
                    (identity.user_id,),
                )
                if int(cur.fetchone()["n"]) >= identity.rpm_limit:
                    raise ControlError("rate_limited", "rate limit exceeded", 429)

                cur.execute(
                    """
                    SELECT monthly_credits,purchased_credits,reserved_credits
                    FROM ih_wallets WHERE user_id=%s FOR UPDATE
                    """,
                    (identity.user_id,),
                )
                wallet = cur.fetchone()
                if not wallet:
                    raise ControlError("wallet_missing", "wallet not found", 500)

                total = int(wallet["monthly_credits"]) + int(wallet["purchased_credits"])
                already_reserved = int(wallet["reserved_credits"])
                available = total - already_reserved
                if available < reserved:
                    raise ControlError(
                        "insufficient_credits",
                        (
                            f"this call requires {reserved} reserved credits but only "
                            f"{max(0, available)} are currently available"
                        ),
                        402,
                    )

                if reserved:
                    cur.execute(
                        """
                        UPDATE ih_wallets
                        SET reserved_credits=reserved_credits+%s,updated_at=now()
                        WHERE user_id=%s
                        """,
                        (reserved, identity.user_id),
                    )

                cur.execute(
                    """
                    INSERT INTO ih_usage_events(
                        id,user_id,api_key_id,request_id,tool_ref,provider,status,
                        credits_charged,input_bytes,metadata
                    ) VALUES (%s,%s,%s,%s,%s,%s,'reserved',0,%s,%s::jsonb)
                    """,
                    (
                        self._new_id("use"),
                        identity.user_id,
                        identity.api_key_id,
                        request_id,
                        tool_name,
                        provider,
                        input_bytes,
                        json.dumps(
                            {
                                "auth_source": identity.source,
                                "arguments_present": bool(arguments),
                                "tool": tool_name,
                                "plan": identity.plan_slug,
                                "reservation": {
                                    "credits": reserved,
                                    "state": "reserved",
                                },
                                "pricing": {
                                    "category": quote["category"],
                                    "provider_class": quote["provider_class"],
                                    "minimum_plan": quote["minimum_plan"],
                                    "breakdown": quote["breakdown"],
                                },
                            }
                        ),
                    ),
                )
            conn.commit()
        return reserved

    def settle_tool_call(
        self,
        request_id: str,
        *,
        status: str,
        latency_ms: int,
        output_bytes: int,
        actual_credits: int | None = None,
    ) -> int:
        self.ensure_schema()
        with self._connect() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT user_id,status,credits_charged,metadata
                    FROM ih_usage_events
                    WHERE request_id=%s
                    FOR UPDATE
                    """,
                    (request_id,),
                )
                event = cur.fetchone()
                if not event:
                    return 0

                if event["status"] != "reserved":
                    cur.execute(
                        """
                        UPDATE ih_usage_events
                        SET status=%s,latency_ms=%s,output_bytes=%s
                        WHERE request_id=%s
                        """,
                        (status, latency_ms, output_bytes, request_id),
                    )
                    conn.commit()
                    return int(event["credits_charged"] or 0)

                metadata = dict(event.get("metadata") or {})
                reservation = dict(metadata.get("reservation") or {})
                reserved = max(0, int(reservation.get("credits") or 0))
                actual = reserved if actual_credits is None else max(0, int(actual_credits))
                if actual > reserved:
                    raise ControlError(
                        "reservation_exceeded",
                        (
                            f"actual cost {actual} exceeds reserved amount {reserved}; "
                            "the estimator must reserve the maximum possible charge"
                        ),
                        500,
                    )

                cur.execute(
                    """
                    SELECT monthly_credits,purchased_credits,reserved_credits
                    FROM ih_wallets
                    WHERE user_id=%s
                    FOR UPDATE
                    """,
                    (event["user_id"],),
                )
                wallet = cur.fetchone()
                if not wallet:
                    raise ControlError("wallet_missing", "wallet not found", 500)

                monthly = int(wallet["monthly_credits"])
                purchased = int(wallet["purchased_credits"])
                from_monthly = min(monthly, actual)
                from_purchased = actual - from_monthly
                if from_purchased > purchased:
                    raise ControlError(
                        "wallet_invariant",
                        "reserved credits can no longer be settled from the wallet",
                        500,
                    )

                cur.execute(
                    """
                    UPDATE ih_wallets
                    SET monthly_credits=monthly_credits-%s,
                        purchased_credits=purchased_credits-%s,
                        reserved_credits=GREATEST(reserved_credits-%s,0),
                        updated_at=now()
                    WHERE user_id=%s
                    """,
                    (from_monthly, from_purchased, reserved, event["user_id"]),
                )

                ledger_metadata = {
                    "tool": metadata.get("tool"),
                    "plan": metadata.get("plan"),
                    "pricing": metadata.get("pricing") or {},
                    "reservation": {
                        "reserved": reserved,
                        "settled": actual,
                        "released": reserved - actual,
                    },
                }
                tool_name = str(metadata.get("tool") or "")
                ledger_metadata["tool"] = tool_name

                if from_monthly:
                    cur.execute(
                        """
                        INSERT INTO ih_credit_ledger(
                            id,user_id,amount,bucket,kind,source,reference_id,metadata
                        ) VALUES (%s,%s,%s,'monthly','usage','mcp',%s,%s::jsonb)
                        """,
                        (
                            self._new_id("led"),
                            event["user_id"],
                            -from_monthly,
                            request_id,
                            json.dumps(ledger_metadata),
                        ),
                    )
                if from_purchased:
                    cur.execute(
                        """
                        INSERT INTO ih_credit_ledger(
                            id,user_id,amount,bucket,kind,source,reference_id,metadata
                        ) VALUES (%s,%s,%s,'purchased','usage','mcp',%s,%s::jsonb)
                        """,
                        (
                            self._new_id("led"),
                            event["user_id"],
                            -from_purchased,
                            request_id,
                            json.dumps(ledger_metadata),
                        ),
                    )

                reservation.update(
                    {
                        "state": "settled",
                        "reserved": reserved,
                        "settled": actual,
                        "released": reserved - actual,
                    }
                )
                metadata["reservation"] = reservation
                cur.execute(
                    """
                    UPDATE ih_usage_events
                    SET status=%s,credits_charged=%s,latency_ms=%s,output_bytes=%s,
                        metadata=%s::jsonb
                    WHERE request_id=%s
                    """,
                    (
                        status,
                        actual,
                        latency_ms,
                        output_bytes,
                        json.dumps(metadata),
                        request_id,
                    ),
                )
            conn.commit()
        return actual

    def release_tool_reservation(
        self,
        request_id: str,
        *,
        status: str = "cancelled",
        latency_ms: int = 0,
        output_bytes: int = 0,
    ) -> int:
        return self.settle_tool_call(
            request_id,
            status=status,
            latency_ms=latency_ms,
            output_bytes=output_bytes,
            actual_credits=0,
        )

    def charge_tool_call(
        self,
        *,
        identity: AuthIdentity,
        request_id: str,
        tool_name: str,
        arguments: dict[str, Any] | None,
        input_bytes: int,
    ) -> int:
        """Compatibility path: reserve and immediately settle the quoted cost."""
        reserved = self.reserve_tool_call(
            identity=identity,
            request_id=request_id,
            tool_name=tool_name,
            arguments=arguments,
            input_bytes=input_bytes,
        )
        return self.settle_tool_call(
            request_id,
            status="accepted",
            latency_ms=0,
            output_bytes=0,
            actual_credits=reserved,
        )

    def finish_usage(
        self,
        request_id: str,
        *,
        status: str,
        latency_ms: int,
        output_bytes: int,
    ) -> None:
        self.settle_tool_call(
            request_id,
            status=status,
            latency_ms=latency_ms,
            output_bytes=output_bytes,
        )

    def usage_summary(self, user_id: str) -> dict[str, Any]:
        self.ensure_schema()
        account = self.account_snapshot(user_id)
        with self._connect() as conn, conn.cursor() as cur:
            cur.execute(
                """
                SELECT count(*) FILTER (WHERE created_at>now()-interval '24 hours') AS calls_24h,
                       count(*) FILTER (WHERE created_at>now()-interval '30 days') AS calls_30d,
                       COALESCE(sum(credits_charged) FILTER (WHERE created_at>now()-interval '30 days'),0) AS credits_30d,
                       COALESCE(avg(latency_ms) FILTER (WHERE created_at>now()-interval '30 days' AND latency_ms IS NOT NULL),0)::int AS avg_latency_ms,
                       COALESCE(100.0*sum(CASE WHEN status='ok' THEN 1 ELSE 0 END) FILTER (WHERE created_at>now()-interval '30 days') / NULLIF(count(*) FILTER (WHERE created_at>now()-interval '30 days'),0),100) AS success_rate
                FROM ih_usage_events WHERE user_id=%s
                """,
                (user_id,),
            )
            usage = dict(cur.fetchone())
            cur.execute(
                """
                SELECT date_trunc('day',created_at)::date AS day,count(*) AS calls,COALESCE(sum(credits_charged),0) AS credits
                FROM ih_usage_events WHERE user_id=%s AND created_at>now()-interval '30 days'
                GROUP BY 1 ORDER BY 1
                """,
                (user_id,),
            )
            series = [dict(r) for r in cur.fetchall()]
            cur.execute(
                """
                SELECT tool_ref,count(*) AS calls,COALESCE(sum(credits_charged),0) AS credits
                FROM ih_usage_events WHERE user_id=%s AND created_at>now()-interval '30 days'
                GROUP BY tool_ref ORDER BY calls DESC LIMIT 8
                """,
                (user_id,),
            )
            top_tools = [dict(r) for r in cur.fetchall()]
        return {"account": account, "usage": usage, "series": series, "top_tools": top_tools}

    def recent_usage(self, user_id: str, limit: int = 100) -> list[dict[str, Any]]:
        self.ensure_schema()
        limit = max(1, min(limit, 500))
        with self._connect() as conn, conn.cursor() as cur:
            cur.execute(
                """
                SELECT request_id,tool_ref,capability,provider,status,credits_charged,latency_ms,
                       input_bytes,output_bytes,created_at
                FROM ih_usage_events WHERE user_id=%s ORDER BY created_at DESC LIMIT %s
                """,
                (user_id, limit),
            )
            return [dict(r) for r in cur.fetchall()]

    def wallet_ledger(self, user_id: str, limit: int = 100) -> dict[str, Any]:
        self.ensure_schema()
        with self._connect() as conn, conn.cursor() as cur:
            cur.execute("SELECT * FROM ih_wallets WHERE user_id=%s", (user_id,))
            wallet = cur.fetchone()
            cur.execute(
                """
                SELECT id,amount,bucket,kind,source,reference_id,metadata,created_at
                FROM ih_credit_ledger WHERE user_id=%s ORDER BY created_at DESC LIMIT %s
                """,
                (user_id, max(1, min(limit, 500))),
            )
            return {"wallet": dict(wallet) if wallet else None, "ledger": [dict(r) for r in cur.fetchall()]}

    def list_monitors(self, user_id: str) -> list[dict[str, Any]]:
        self.ensure_schema()
        with self._connect() as conn, conn.cursor() as cur:
            cur.execute("SELECT * FROM ih_monitors WHERE user_id=%s ORDER BY created_at DESC", (user_id,))
            return [dict(r) for r in cur.fetchall()]

    def get_monitor(self, user_id: str, monitor_id: str) -> dict[str, Any] | None:
        self.ensure_schema()
        with self._connect() as conn, conn.cursor() as cur:
            cur.execute("SELECT * FROM ih_monitors WHERE id=%s AND user_id=%s", (monitor_id, user_id))
            monitor = cur.fetchone()
            if not monitor:
                return None
            cur.execute(
                "SELECT * FROM ih_monitor_runs WHERE monitor_id=%s ORDER BY created_at DESC LIMIT 50",
                (monitor_id,),
            )
            result = dict(monitor)
            result["runs"] = [dict(r) for r in cur.fetchall()]
            return result

    def create_monitor(
        self,
        *,
        user_id: str,
        name: str,
        monitor_type: str,
        target: str,
        interval_minutes: int,
        config: dict[str, Any],
    ) -> dict[str, Any]:
        self.ensure_schema()
        account = self.account_snapshot(user_id)
        with self._connect() as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT count(*) AS n FROM ih_monitors WHERE user_id=%s", (user_id,))
                if int(cur.fetchone()["n"]) >= int(account["monitor_limit"]):
                    raise ControlError("monitor_limit", "monitor limit reached for current plan", 403)
                monitor_id = self._new_id("mon")
                cur.execute(
                    """
                    INSERT INTO ih_monitors(id,user_id,name,type,target,interval_minutes,next_check_at,config)
                    VALUES (%s,%s,%s,%s,%s,%s,now()+(%s || ' minutes')::interval,%s::jsonb)
                    RETURNING *
                    """,
                    (
                        monitor_id, user_id, name, monitor_type, target, interval_minutes,
                        interval_minutes, json.dumps(config),
                    ),
                )
                row = cur.fetchone()
            conn.commit()
            assert row is not None
            return dict(row)

    def toggle_monitor(self, user_id: str, monitor_id: str, enabled: bool) -> bool:
        self.ensure_schema()
        with self._connect() as conn, conn.cursor() as cur:
            cur.execute(
                "UPDATE ih_monitors SET enabled=%s,updated_at=now() WHERE id=%s AND user_id=%s",
                (enabled, monitor_id, user_id),
            )
            changed = cur.rowcount > 0
            conn.commit()
            return changed

    def create_oauth_code(
        self,
        *,
        identity: AuthIdentity,
        client_id: str,
        redirect_uri: str,
        code_hash: str,
        code_challenge: str,
        scopes: list[str],
    ) -> None:
        self.ensure_schema()
        if not identity.api_key_id:
            raise ControlError("invalid_api_key", "OAuth authorization requires an API key", 400)
        with self._connect() as conn, conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO ih_oauth_authorization_codes(
                    id,user_id,api_key_id,client_id,redirect_uri,code_hash,code_challenge,scopes,expires_at
                ) VALUES (%s,%s,%s,%s,%s,%s,%s,%s::jsonb,%s)
                """,
                (
                    self._new_id("cod"), identity.user_id, identity.api_key_id, client_id,
                    redirect_uri, code_hash, code_challenge, json.dumps(scopes),
                    datetime.now(UTC) + timedelta(minutes=5),
                ),
            )
            conn.commit()

    def consume_oauth_code(self, code_hash: str) -> dict[str, Any] | None:
        self.ensure_schema()
        with self._connect() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT * FROM ih_oauth_authorization_codes
                    WHERE code_hash=%s AND used_at IS NULL AND expires_at>now() FOR UPDATE
                    """,
                    (code_hash,),
                )
                row = cur.fetchone()
                if not row:
                    return None
                cur.execute("UPDATE ih_oauth_authorization_codes SET used_at=now() WHERE id=%s", (row["id"],))
            conn.commit()
            return dict(row)

    def create_oauth_token(
        self,
        *,
        user_id: str,
        api_key_id: str,
        client_id: str,
        access_hash: str,
        refresh_hash: str,
        scopes: list[str],
    ) -> None:
        self.ensure_schema()
        with self._connect() as conn, conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO ih_oauth_tokens(
                    id,user_id,api_key_id,client_id,access_token_hash,refresh_token_hash,scopes,
                    access_expires_at,refresh_expires_at
                ) VALUES (%s,%s,%s,%s,%s,%s,%s::jsonb,%s,%s)
                """,
                (
                    self._new_id("tok"), user_id, api_key_id, client_id, access_hash, refresh_hash,
                    json.dumps(scopes), datetime.now(UTC) + timedelta(hours=1),
                    datetime.now(UTC) + timedelta(days=30),
                ),
            )
            conn.commit()

    def consume_refresh_token(self, refresh_hash: str, client_id: str) -> dict[str, Any] | None:
        self.ensure_schema()
        with self._connect() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT * FROM ih_oauth_tokens
                    WHERE refresh_token_hash=%s AND client_id=%s AND revoked_at IS NULL
                      AND refresh_expires_at>now() FOR UPDATE
                    """,
                    (refresh_hash, client_id),
                )
                row = cur.fetchone()
                if not row:
                    return None
                cur.execute("UPDATE ih_oauth_tokens SET revoked_at=now() WHERE id=%s", (row["id"],))
            conn.commit()
            return dict(row)

    def create_payment(
        self,
        *,
        user_id: str,
        order_id: str,
        amount_paise: int,
        purpose: str,
        plan_slug: str | None,
        credit_pack_slug: str | None,
        metadata: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        self.ensure_schema()
        payment_row_id = self._new_id("pay")
        with self._connect() as conn, conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO ih_payments(
                    id,user_id,order_id,amount_paise,status,purpose,plan_slug,credit_pack_slug,metadata
                ) VALUES (%s,%s,%s,%s,'created',%s,%s,%s,%s::jsonb)
                RETURNING *
                """,
                (
                    payment_row_id, user_id, order_id, amount_paise, purpose, plan_slug,
                    credit_pack_slug, json.dumps(metadata or {}),
                ),
            )
            row = cur.fetchone()
            conn.commit()
            assert row is not None
            return dict(row)

    def get_payment_by_order(self, order_id: str) -> dict[str, Any] | None:
        self.ensure_schema()
        with self._connect() as conn, conn.cursor() as cur:
            cur.execute("SELECT * FROM ih_payments WHERE order_id=%s", (order_id,))
            row = cur.fetchone()
            return dict(row) if row else None

    def finalize_payment(self, *, order_id: str, payment_id: str, status: str = "captured") -> dict[str, Any]:
        self.ensure_schema()
        with self._connect() as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT * FROM ih_payments WHERE order_id=%s FOR UPDATE", (order_id,))
                payment = cur.fetchone()
                if not payment:
                    raise ControlError("payment_not_found", "payment order not found", 404)
                if payment["status"] in {"paid", "captured"}:
                    return dict(payment)
                user_id = payment["user_id"]
                if payment["purpose"] == "credits":
                    cur.execute(
                        "SELECT credits FROM ih_credit_packs WHERE slug=%s AND active=true",
                        (payment["credit_pack_slug"],),
                    )
                    pack = cur.fetchone()
                    if not pack:
                        raise ControlError("credit_pack_not_found", "credit pack not found", 404)
                    credits = int(pack["credits"])
                    cur.execute(
                        "UPDATE ih_wallets SET purchased_credits=purchased_credits+%s,updated_at=now() WHERE user_id=%s",
                        (credits, user_id),
                    )
                    cur.execute(
                        """
                        INSERT INTO ih_credit_ledger(id,user_id,amount,bucket,kind,source,reference_id)
                        VALUES (%s,%s,%s,'purchased','purchase','razorpay',%s)
                        """,
                        (self._new_id("led"), user_id, credits, order_id),
                    )
                elif payment["purpose"] == "subscription":
                    plan_slug = payment["plan_slug"]
                    cur.execute("SELECT included_credits FROM ih_plans WHERE slug=%s", (plan_slug,))
                    plan = cur.fetchone()
                    if not plan:
                        raise ControlError("plan_not_found", "plan not found", 404)
                    cur.execute(
                        "UPDATE ih_subscriptions SET status='replaced',updated_at=now() WHERE user_id=%s AND status='active'",
                        (user_id,),
                    )
                    now = datetime.now(UTC)
                    cur.execute(
                        """
                        INSERT INTO ih_subscriptions(
                            id,user_id,plan_slug,status,current_period_start,current_period_end,provider
                        ) VALUES (%s,%s,%s,'active',%s,%s,'razorpay')
                        """,
                        (self._new_id("sub"), user_id, plan_slug, now, now + timedelta(days=30)),
                    )
                    credits = int(plan["included_credits"])
                    cur.execute(
                        "UPDATE ih_wallets SET monthly_credits=%s,updated_at=now() WHERE user_id=%s",
                        (credits, user_id),
                    )
                    cur.execute(
                        """
                        INSERT INTO ih_credit_ledger(id,user_id,amount,bucket,kind,source,reference_id)
                        VALUES (%s,%s,%s,'monthly','grant','subscription',%s)
                        """,
                        (self._new_id("led"), user_id, credits, order_id),
                    )
                cur.execute(
                    """
                    UPDATE ih_payments SET payment_id=%s,status=%s,paid_at=now() WHERE id=%s RETURNING *
                    """,
                    (payment_id, status, payment["id"]),
                )
                result = cur.fetchone()
            conn.commit()
            assert result is not None
            return dict(result)

    def record_webhook(
        self,
        *,
        provider: str,
        event_id: str,
        event_type: str,
        signature_valid: bool,
        payload_hash: str,
        status: str,
    ) -> bool:
        self.ensure_schema()
        with self._connect() as conn, conn.cursor() as cur:
            try:
                cur.execute(
                    """
                    INSERT INTO ih_webhook_events(id,provider,event_id,event_type,signature_valid,payload_hash,status)
                    VALUES (%s,%s,%s,%s,%s,%s,%s)
                    """,
                    (
                        self._new_id("wh"), provider, event_id, event_type, signature_valid,
                        payload_hash, status,
                    ),
                )
                conn.commit()
                return True
            except UniqueViolation:
                conn.rollback()
                return False

    def list_payments(self, user_id: str, limit: int = 100) -> list[dict[str, Any]]:
        self.ensure_schema()
        with self._connect() as conn, conn.cursor() as cur:
            cur.execute(
                "SELECT * FROM ih_payments WHERE user_id=%s ORDER BY created_at DESC LIMIT %s",
                (user_id, max(1, min(limit, 500))),
            )
            return [dict(r) for r in cur.fetchall()]

    def create_password_reset(self, user_id: str, token_hash: str) -> None:
        self.ensure_schema()
        with self._connect() as conn, conn.cursor() as cur:
            cur.execute(
                "UPDATE ih_password_resets SET used_at=now() "
                "WHERE user_id=%s AND used_at IS NULL",
                (user_id,),
            )
            cur.execute(
                "INSERT INTO ih_password_resets(id,user_id,token_hash,expires_at) VALUES (%s,%s,%s,%s)",
                (self._new_id("rst"), user_id, token_hash, datetime.now(UTC) + timedelta(minutes=30)),
            )
            conn.commit()

    def consume_password_reset(self, token_hash: str, password_hash: str) -> bool:
        self.ensure_schema()
        with self._connect() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT * FROM ih_password_resets
                    WHERE token_hash=%s AND used_at IS NULL AND expires_at>now() FOR UPDATE
                    """,
                    (token_hash,),
                )
                row = cur.fetchone()
                if not row:
                    return False
                cur.execute("UPDATE ih_users SET password_hash=%s,updated_at=now() WHERE id=%s", (password_hash, row["user_id"]))
                cur.execute("UPDATE ih_password_resets SET used_at=now() WHERE id=%s", (row["id"],))
                cur.execute("DELETE FROM ih_sessions WHERE user_id=%s", (row["user_id"],))
            conn.commit()
            return True


def random_token(prefix: str = "") -> str:
    return f"{prefix}{secrets.token_urlsafe(32)}"
