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

from .capability_economics import estimate_call, plan_privileges
from .provider_errors import read_retry_budget
from .provider_reliability_store import record_provider_reliability_event

SCHEMA_SQL = r"""
CREATE TABLE IF NOT EXISTS ih_users (
    id text PRIMARY KEY,
    email text NOT NULL,
    password_hash text,
    github_id text UNIQUE,
    display_name text,
    avatar_url text,
    auth_provider text,
    auth_subject text,
    email_verified boolean NOT NULL DEFAULT false,
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now()
);
CREATE UNIQUE INDEX IF NOT EXISTS ih_users_email_lower_idx ON ih_users ((lower(email)));
ALTER TABLE ih_users ADD COLUMN IF NOT EXISTS auth_provider text;
ALTER TABLE ih_users ADD COLUMN IF NOT EXISTS auth_subject text;
CREATE UNIQUE INDEX IF NOT EXISTS ih_users_auth_identity_idx
    ON ih_users(auth_provider, auth_subject)
    WHERE auth_provider IS NOT NULL AND auth_subject IS NOT NULL;

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

CREATE TABLE IF NOT EXISTS ih_connections (
    id text PRIMARY KEY,
    user_id text NOT NULL REFERENCES ih_users(id) ON DELETE CASCADE,
    name text NOT NULL,
    kind text NOT NULL DEFAULT 'mcp',
    endpoint_url text NOT NULL,
    transport text NOT NULL DEFAULT 'streamable_http',
    auth_type text NOT NULL DEFAULT 'none',
    config jsonb NOT NULL DEFAULT '{}'::jsonb,
    secret_config jsonb NOT NULL DEFAULT '{}'::jsonb,
    enabled boolean NOT NULL DEFAULT true,
    last_status text,
    last_checked_at timestamptz,
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS ih_connections_user_idx ON ih_connections(user_id, created_at DESC);

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

CREATE TABLE IF NOT EXISTS ih_provider_usage (
    id text PRIMARY KEY,
    request_id text NOT NULL REFERENCES ih_usage_events(request_id) ON DELETE CASCADE,
    provider text NOT NULL,
    operation text NOT NULL,
    credits_used integer,
    status text NOT NULL,
    ref text,
    latency_ms integer,
    error_class text,
    retryable boolean NOT NULL DEFAULT false,
    error_text text,
    attempt integer,
    created_at timestamptz NOT NULL DEFAULT now()
);
ALTER TABLE ih_provider_usage ADD COLUMN IF NOT EXISTS ref text;
ALTER TABLE ih_provider_usage ADD COLUMN IF NOT EXISTS latency_ms integer;
ALTER TABLE ih_provider_usage ADD COLUMN IF NOT EXISTS error_class text;
ALTER TABLE ih_provider_usage ADD COLUMN IF NOT EXISTS retryable boolean NOT NULL DEFAULT false;
ALTER TABLE ih_provider_usage ADD COLUMN IF NOT EXISTS error_text text;
ALTER TABLE ih_provider_usage ADD COLUMN IF NOT EXISTS attempt integer;
CREATE INDEX IF NOT EXISTS ih_provider_usage_request_idx ON ih_provider_usage(request_id);
CREATE INDEX IF NOT EXISTS ih_provider_usage_provider_time_idx
    ON ih_provider_usage(provider, created_at DESC);

CREATE TABLE IF NOT EXISTS ih_provider_reliability (
    provider text PRIMARY KEY,
    successes bigint NOT NULL DEFAULT 0,
    failures bigint NOT NULL DEFAULT 0,
    neutral bigint NOT NULL DEFAULT 0,
    consecutive_failures integer NOT NULL DEFAULT 0,
    ewma_latency_ms double precision,
    last_success_at timestamptz,
    last_failure_at timestamptz,
    last_error text,
    last_error_class text,
    circuit_open_until timestamptz,
    updated_at timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS ih_provider_reliability_updated_idx
    ON ih_provider_reliability(updated_at DESC);

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

# Internal metering remains integer-based for exact reservations and settlement.
# The product-facing wallet exposes these units as USD service balance.
WALLET_UNITS_PER_USD = 5_000
CUSTOM_TOPUP_MIN_USD_CENTS = 100
CUSTOM_TOPUP_MAX_USD_CENTS = 50_000

# OpenCrawl-supplied execution is deliberately more credit-sensitive than the raw
# provider estimate. This keeps the wallet meaningful while every subscription
# tier shares the same tool catalog. Operators can tune the multiplier without
# changing provider-specific economics.
DEFAULT_CREDIT_BURN_MULTIPLIER = 3


def credit_burn_multiplier() -> int:
    try:
        value = int(os.getenv("OPENCRAWL_CREDIT_BURN_MULTIPLIER", str(DEFAULT_CREDIT_BURN_MULTIPLIER)))
    except (TypeError, ValueError):
        value = DEFAULT_CREDIT_BURN_MULTIPLIER
    return max(1, min(value, 20))


def wallet_credits_for_raw(raw_credits: int) -> int:
    """Convert raw metered work into product-facing wallet units."""
    raw = max(0, int(raw_credits))
    return raw * credit_burn_multiplier()


def raw_credits_from_wallet_reservation(reserved_credits: int) -> int:
    """Recover the raw ceiling from a reservation created by this process."""
    reserved = max(0, int(reserved_credits))
    multiplier = credit_burn_multiplier()
    return reserved // multiplier


def _apply_credit_burn(credits: int) -> int:
    return wallet_credits_for_raw(credits)


def _apply_credit_burn_to_quote(quote: dict[str, Any]) -> dict[str, Any]:
    result = dict(quote)
    raw = max(0, int(result.get("credits") or 0))
    multiplier = credit_burn_multiplier()
    result["raw_credits"] = raw
    result["credit_burn_multiplier"] = multiplier
    result["credits"] = raw * multiplier

    if raw and multiplier > 1:
        breakdown = list(result.get("breakdown") or [])
        breakdown.append(
            {
                "kind": "credit_burn_multiplier",
                "multiplier": multiplier,
                "raw_credits": raw,
                "credits": raw * (multiplier - 1),
            }
        )
        result["breakdown"] = breakdown

    retry = result.get("retry_reservation")
    if isinstance(retry, dict) and multiplier > 1:
        scaled_retry = dict(retry)
        for key in ("quoted_once", "retryable_once", "reserved"):
            if key in scaled_retry:
                scaled_retry[key] = max(0, int(scaled_retry[key])) * multiplier
        scaled_retry["credit_burn_multiplier"] = multiplier
        result["retry_reservation"] = scaled_retry
    return result


FREE_MONTHLY_CREDITS = 250
PLAN_ROWS = [
    # Tool availability is universal; plans differ by wallet/throughput/account limits.
    ("free", "Free", 0, FREE_MONTHLY_CREDITS, 10, 1, 1, 1, True, True, 0),
    ("builder", "Builder", 499, 25000, 60, 4, 5, 10, True, True, 10),
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
    ("repo:*", 1, {"category": "repository"}),
    ("gamecore:*", 1, {"category": "gaming"}),
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
    concurrent_limit: int = 1


def _db_connect_timeout_seconds() -> int:
    try:
        value = int(os.getenv("OPENCRAWL_DB_CONNECT_TIMEOUT_SECONDS", "5"))
    except (TypeError, ValueError):
        value = 5
    return max(1, min(value, 30))


_RETRY_RESERVATION_TOOLS = {
    "mesh_execute",
    "mesh_batch_execute",
    "mesh_capability_execute",
    "gaming_intel",
    "gaming_profile",
}

_NON_RETRYABLE_RAW_PROVIDERS = {"apify", "nativesandbox"}
_NON_RETRYABLE_RAW_REFS = {"firecrawl:interact"}


def _raw_mesh_ref_can_retry(ref: str) -> bool:
    normalized = str(ref or "").strip().lower()
    if not normalized:
        return False
    provider = normalized.split(":", 1)[0]
    if provider in _NON_RETRYABLE_RAW_PROVIDERS:
        return False
    return normalized not in _NON_RETRYABLE_RAW_REFS


def _retryable_quoted_credits(
    tool_name: str,
    arguments: dict[str, Any] | None,
    *,
    plan_slug: str,
    base_quote: dict[str, Any],
) -> int:
    args = arguments or {}
    if tool_name == "mesh_execute":
        ref = str(args.get("ref") or args.get("tool") or "")
        return max(0, int(base_quote.get("credits") or 0)) if _raw_mesh_ref_can_retry(ref) else 0

    if tool_name == "mesh_batch_execute":
        calls = args.get("calls")
        if not isinstance(calls, list):
            return 0
        retryable = 0
        for call in calls:
            if not isinstance(call, dict):
                continue
            ref = str(call.get("ref") or call.get("tool") or "")
            if not _raw_mesh_ref_can_retry(ref):
                continue
            nested = estimate_call("mesh_execute", call, plan_slug)
            if nested.allowed:
                retryable += max(0, int(nested.credits))
        return retryable

    return max(0, int(base_quote.get("credits") or 0))


def _with_retry_reservation(
    tool_name: str,
    quote: dict[str, Any],
    *,
    arguments: dict[str, Any] | None,
    plan_slug: str,
) -> dict[str, Any]:
    """Reserve retry headroom only for work execution is permitted to replay."""
    base_credits = max(0, int(quote.get("credits") or 0))
    retries = read_retry_budget()
    if (
        tool_name not in _RETRY_RESERVATION_TOOLS
        or base_credits <= 0
        or retries <= 0
    ):
        return quote

    retryable_once = _retryable_quoted_credits(
        tool_name,
        arguments,
        plan_slug=plan_slug,
        base_quote=quote,
    )
    if retryable_once <= 0:
        return quote

    attempts = 1 + retries
    extra = retryable_once * retries
    reserved = base_credits + extra
    result = dict(quote)
    result["credits"] = reserved
    breakdown = list(result.get("breakdown") or [])
    breakdown.append(
        {
            "kind": "provider_retry_headroom",
            "attempts": attempts,
            "retries": retries,
            "quoted_once": base_credits,
            "retryable_once": retryable_once,
            "credits": extra,
        }
    )
    result["breakdown"] = breakdown
    result["retry_reservation"] = {
        "attempts": attempts,
        "retries": retries,
        "quoted_once": base_credits,
        "retryable_once": retryable_once,
        "reserved": reserved,
    }
    return result


class ControlStore:
    def __init__(self, dsn: str | None = None) -> None:
        if dsn is not None:
            selected = dsn
        else:
            control_dsn = os.getenv("INTERNET_HANDS_CONTROL_POSTGRES_DSN")
            neon_dsn = os.getenv("INTERNET_HANDS_POSTGRES_DSN")
            primary = (os.getenv("OPENCRAWL_PRIMARY_DATABASE") or "supabase").strip().lower()
            selected = neon_dsn if primary == "neon" and neon_dsn else control_dsn or neon_dsn
        self.dsn = selected
        self._schema_ready = False
        self._schema_lock = threading.Lock()

    @property
    def configured(self) -> bool:
        return bool(self.dsn)

    def _connect(self):
        if not self.dsn:
            raise ControlError("control_plane_unavailable", "control database is not configured", 503)
        options: dict[str, Any] = {
            "row_factory": dict_row,
            "connect_timeout": _db_connect_timeout_seconds(),
        }
        # Supabase's transaction pooler must not receive named prepared
        # statements because a later transaction can land on another backend.
        if "pooler.supabase.com" in self.dsn:
            options["prepare_threshold"] = None
        return psycopg.connect(self.dsn, **options)

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

    def ensure_auth_user(
        self,
        *,
        email: str,
        display_name: str | None,
        provider: str,
        subject: str,
        email_verified: bool = False,
    ) -> dict[str, Any]:
        """Create or link an application user to an external identity provider."""
        self.ensure_schema()
        normalized_email = email.strip().lower()
        normalized_provider = provider.strip().lower()
        normalized_subject = subject.strip()
        if not normalized_email or not normalized_provider or not normalized_subject:
            raise ControlError("invalid_identity", "identity provider fields are required", 400)

        with self._connect() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT * FROM ih_users WHERE lower(email)=lower(%s) FOR UPDATE",
                    (normalized_email,),
                )
                row = cur.fetchone()
                if row:
                    existing_provider = str(row.get("auth_provider") or "")
                    existing_subject = str(row.get("auth_subject") or "")
                    if existing_subject and (
                        existing_provider != normalized_provider
                        or existing_subject != normalized_subject
                    ):
                        raise ControlError(
                            "identity_conflict",
                            "this account is already linked to another identity",
                            409,
                        )
                    cur.execute(
                        """
                        UPDATE ih_users
                        SET auth_provider=%s,
                            auth_subject=%s,
                            display_name=COALESCE(display_name,%s),
                            email_verified=(email_verified OR %s),
                            updated_at=now()
                        WHERE id=%s
                        RETURNING id,email,display_name,avatar_url,email_verified,created_at,updated_at
                        """,
                        (
                            normalized_provider,
                            normalized_subject,
                            display_name,
                            email_verified,
                            row["id"],
                        ),
                    )
                    linked = cur.fetchone()
                    conn.commit()
                    assert linked is not None
                    return dict(linked)

                user_id = self._new_id("usr")
                try:
                    cur.execute(
                        """
                        INSERT INTO ih_users(
                            id,email,display_name,auth_provider,auth_subject,email_verified
                        ) VALUES (%s,%s,%s,%s,%s,%s)
                        RETURNING id,email,display_name,avatar_url,email_verified,created_at,updated_at
                        """,
                        (
                            user_id,
                            normalized_email,
                            display_name,
                            normalized_provider,
                            normalized_subject,
                            email_verified,
                        ),
                    )
                except UniqueViolation as exc:
                    conn.rollback()
                    raise ControlError(
                        "identity_conflict",
                        "this email or identity is already linked",
                        409,
                    ) from exc
                linked = cur.fetchone()
            conn.commit()
            assert linked is not None
            return dict(linked)

    def link_auth_identity(self, user_id: str, *, provider: str, subject: str) -> None:
        self.ensure_schema()
        normalized_provider = provider.strip().lower()
        normalized_subject = subject.strip()
        with self._connect() as conn, conn.cursor() as cur:
            try:
                cur.execute(
                    """
                    UPDATE ih_users
                    SET auth_provider=%s,auth_subject=%s,updated_at=now()
                    WHERE id=%s
                      AND (
                        auth_subject IS NULL
                        OR (auth_provider=%s AND auth_subject=%s)
                      )
                    """,
                    (
                        normalized_provider,
                        normalized_subject,
                        user_id,
                        normalized_provider,
                        normalized_subject,
                    ),
                )
            except UniqueViolation as exc:
                conn.rollback()
                raise ControlError(
                    "identity_conflict",
                    "this external identity is already linked",
                    409,
                ) from exc
            if cur.rowcount != 1:
                conn.rollback()
                raise ControlError(
                    "identity_conflict",
                    "this account is already linked to another identity",
                    409,
                )
            conn.commit()

    def _activate_free_account(self, cur: Any, user_id: str) -> None:
        """Provision account resources once, inside the caller's transaction."""
        now = datetime.now(UTC)
        free_credits = FREE_MONTHLY_CREDITS
        cur.execute(
            """
            INSERT INTO ih_wallets(user_id,monthly_credits)
            VALUES (%s,%s)
            ON CONFLICT (user_id) DO NOTHING
            """,
            (user_id, free_credits),
        )
        cur.execute(
            """
            INSERT INTO ih_credit_ledger(
                id,user_id,amount,bucket,kind,source,reference_id
            )
            SELECT %s,%s,%s,'monthly','grant','signup','free'
            WHERE NOT EXISTS (
                SELECT 1 FROM ih_credit_ledger
                WHERE user_id=%s AND kind='grant' AND source='signup'
            )
            """,
            (self._new_id("led"), user_id, free_credits, user_id),
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
        """Return public account fields only; never return password or provider subjects."""
        self.ensure_schema()
        with self._connect() as conn, conn.cursor() as cur:
            cur.execute(
                """
                SELECT id,email,display_name,avatar_url,email_verified,created_at,updated_at,
                       (github_id IS NOT NULL) AS github_connected
                FROM ih_users WHERE lower(email)=lower(%s)
                """,
                (email.strip(),),
            )
            row = cur.fetchone()
            return dict(row) if row else None

    def get_user_credentials_by_email(self, email: str) -> dict[str, Any] | None:
        """Internal-only legacy credential lookup used during Auth adoption."""
        self.ensure_schema()
        with self._connect() as conn, conn.cursor() as cur:
            cur.execute(
                """
                SELECT id,email,password_hash,display_name,avatar_url,email_verified,
                       created_at,updated_at
                FROM ih_users WHERE lower(email)=lower(%s)
                """,
                (email.strip(),),
            )
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

    def auth_user_id_for_legacy(self, user_id: str) -> str | None:
        """Return the Supabase Auth subject linked to one OpenCrawl identity."""
        self.ensure_schema()
        with self._connect() as conn, conn.cursor() as cur:
            cur.execute(
                """
                SELECT auth_subject
                FROM ih_users
                WHERE id=%s AND auth_provider='supabase' AND auth_subject IS NOT NULL
                """,
                (user_id,),
            )
            linked = cur.fetchone()
            if linked:
                return str(linked["auth_subject"])

            # Transitional compatibility while the source database is still
            # Supabase-backed. Neon never requires this provider-specific table.
            try:
                cur.execute(
                    """
                    SELECT id::text AS auth_user_id
                    FROM profiles
                    WHERE legacy_user_id=%s OR id::text=%s
                    LIMIT 1
                    """,
                    (user_id, user_id),
                )
            except psycopg.Error:
                conn.rollback()
                return None
            row = cur.fetchone()
            if not row:
                return None
            auth_user_id = str(row["auth_user_id"])
            try:
                cur.execute(
                    """
                    UPDATE ih_users
                    SET auth_provider='supabase',auth_subject=%s,updated_at=now()
                    WHERE id=%s AND auth_subject IS NULL
                    """,
                    (auth_user_id, user_id),
                )
                conn.commit()
            except psycopg.Error:
                conn.rollback()
            return auth_user_id

    def has_api_key_hash(self, key_hash: str) -> bool:
        """Detect an already-adopted key, including revoked keys."""
        self.ensure_schema()
        with self._connect() as conn, conn.cursor() as cur:
            cur.execute("SELECT 1 FROM ih_api_keys WHERE key_hash=%s LIMIT 1", (key_hash,))
            return cur.fetchone() is not None

    def adopt_legacy_api_key(self, legacy: ControlStore, key_hash: str) -> bool:
        """Copy one verified legacy key after first successful use.

        The raw key never moves between databases; only its existing one-way
        hash and metadata are copied inside the server process.
        """
        self.ensure_schema()
        legacy.ensure_schema()
        with legacy._connect() as source, source.cursor() as source_cur:
            source_cur.execute(
                """
                SELECT id,user_id,name,prefix,key_hash,scopes,environment,
                       last_used_at,expires_at,revoked_at,created_at
                FROM ih_api_keys
                WHERE key_hash=%s AND revoked_at IS NULL
                  AND (expires_at IS NULL OR expires_at>now())
                LIMIT 1
                """,
                (key_hash,),
            )
            row = source_cur.fetchone()
        if not row:
            return False
        owner = self.get_user(str(row["user_id"]))
        if not owner:
            return False
        with self._connect() as conn, conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO ih_api_keys(
                    id,user_id,name,prefix,key_hash,scopes,environment,
                    last_used_at,expires_at,revoked_at,created_at
                ) VALUES (%s,%s,%s,%s,%s,%s::jsonb,%s,%s,%s,%s,%s)
                ON CONFLICT (key_hash) DO NOTHING
                """,
                (
                    row["id"],
                    row["user_id"],
                    row["name"],
                    row["prefix"],
                    row["key_hash"],
                    json.dumps(row.get("scopes") or []),
                    row["environment"],
                    row.get("last_used_at"),
                    row.get("expires_at"),
                    row.get("revoked_at"),
                    row.get("created_at"),
                ),
            )
            changed = cur.rowcount == 1
            conn.commit()
            return changed

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

    def clear_password_hash(self, user_id: str) -> None:
        """Remove a compatibility password hash after Supabase has adopted it."""
        self.ensure_schema()
        with self._connect() as conn, conn.cursor() as cur:
            cur.execute(
                "UPDATE ih_users SET password_hash=NULL,updated_at=now() WHERE id=%s",
                (user_id,),
            )
            conn.commit()

    def list_plans(self) -> list[dict[str, Any]]:
        self.ensure_schema()
        with self._connect() as conn, conn.cursor() as cur:
            cur.execute("SELECT * FROM ih_plans WHERE active=true ORDER BY monthly_price_inr")
            rows = [dict(row) for row in cur.fetchall()]
        for row in rows:
            row["capability_privileges"] = plan_privileges(str(row["slug"])).to_dict()
        return rows

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
            account = dict(row)
            account["capability_privileges"] = plan_privileges(
                str(account.get("plan_slug") or "free")
            ).to_dict()
            account["display_currency"] = "USD"
            account["wallet_units_per_usd"] = WALLET_UNITS_PER_USD
            return account

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
            concurrent_limit=max(1, int(row.get("concurrent_limit") or 1)),
        )

    def api_key_identity_for_user(self, user_id: str, key_id: str) -> AuthIdentity | None:
        """Resolve one active API key owned by a signed-in user for first-party playground use."""
        self.ensure_schema()
        with self._connect() as conn, conn.cursor() as cur:
            cur.execute(
                """
                SELECT k.user_id,k.id AS api_key_id,k.scopes,p.slug AS plan_slug,p.rpm_limit,p.concurrent_limit
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
                SELECT k.user_id,k.id AS api_key_id,k.scopes,p.slug AS plan_slug,p.rpm_limit,p.concurrent_limit
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
                SELECT t.user_id,t.api_key_id,t.scopes,p.slug AS plan_slug,p.rpm_limit,p.concurrent_limit
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
                "tool_unavailable",
                estimate.reason or "tool cannot be quoted for this request",
                400,
            )
        raw_quote = _with_retry_reservation(
            tool_name,
            quote,
            arguments=arguments,
            plan_slug=identity.plan_slug,
        )
        return _apply_credit_burn_to_quote(raw_quote)

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
                "tool_unavailable",
                estimate.reason or "tool cannot be quoted for this request",
                400,
            )
        return _apply_credit_burn(int(estimate.credits))

    def release_stale_reservations(
        self,
        user_id: str,
        *,
        older_than_minutes: int = 60,
    ) -> dict[str, int]:
        """Release abandoned reservations left behind by crashed request workers."""
        self.ensure_schema()
        cutoff_minutes = max(15, min(int(older_than_minutes), 24 * 60))
        released = 0
        count = 0
        with self._connect() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT request_id,metadata
                    FROM ih_usage_events
                    WHERE user_id=%s
                      AND status='reserved'
                      AND created_at < now() - (%s * interval '1 minute')
                    FOR UPDATE
                    """,
                    (user_id, cutoff_minutes),
                )
                rows = cur.fetchall()
                for row in rows:
                    metadata = dict(row.get("metadata") or {})
                    reservation = dict(metadata.get("reservation") or {})
                    credits = max(0, int(reservation.get("credits") or 0))
                    reservation.update(
                        {
                            "state": "abandoned",
                            "reserved": credits,
                            "settled": 0,
                            "released": credits,
                        }
                    )
                    metadata["reservation"] = reservation
                    cur.execute(
                        """
                        UPDATE ih_usage_events
                        SET status='abandoned',credits_charged=0,metadata=%s::jsonb
                        WHERE request_id=%s AND status='reserved'
                        """,
                        (json.dumps(metadata), row["request_id"]),
                    )
                    if cur.rowcount:
                        released += credits
                        count += 1

                if released:
                    cur.execute(
                        """
                        UPDATE ih_wallets
                        SET reserved_credits=GREATEST(reserved_credits-%s,0),
                            updated_at=now()
                        WHERE user_id=%s
                        """,
                        (released, user_id),
                    )
            conn.commit()
        return {"reservations_released": count, "credits_released": released}

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
        self.release_stale_reservations(identity.user_id)
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

                cur.execute(
                    """
                    SELECT count(*) AS n
                    FROM ih_usage_events
                    WHERE user_id=%s AND status='reserved'
                    """,
                    (identity.user_id,),
                )
                active_reservations = int(cur.fetchone()["n"])
                if active_reservations >= max(1, int(identity.concurrent_limit)):
                    raise ControlError(
                        "concurrency_limited",
                        (
                            "concurrent request limit reached "
                            f"({identity.concurrent_limit})"
                        ),
                        429,
                    )

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
                                    "raw_credits": quote.get("raw_credits", reserved),
                                    "credit_burn_multiplier": quote.get("credit_burn_multiplier", 1),
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
        execution_usage: dict[str, Any] | None = None,
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

                metadata = dict(event.get("metadata") or {})
                if execution_usage is not None:
                    metadata["measured_usage"] = execution_usage

                if event["status"] != "reserved":
                    # Settlement is terminal and idempotent. A duplicated completion,
                    # timeout handler, or late worker must never rewrite a settled or
                    # abandoned request after wallet/ledger state has been finalized.
                    return int(event["credits_charged"] or 0)

                provider_events = (execution_usage or {}).get("provider_events") or []
                for item in provider_events:
                    if not isinstance(item, dict):
                        continue
                    provider = str(item.get("provider") or "").strip().lower()[:80]
                    ref = str(item.get("ref") or "").strip()[:200]
                    if not provider:
                        continue
                    operation = (
                        ref.split(":", 1)[1][:80]
                        if ":" in ref
                        else ref[:80] or "execute"
                    )
                    duration_raw = item.get("duration_ms")
                    duration_ms = (
                        max(0, int(duration_raw))
                        if isinstance(duration_raw, (int, float))
                        and not isinstance(duration_raw, bool)
                        else None
                    )
                    attempt_raw = item.get("attempt")
                    attempt = (
                        max(1, int(attempt_raw))
                        if isinstance(attempt_raw, (int, float))
                        and not isinstance(attempt_raw, bool)
                        else None
                    )
                    error_class = (
                        str(item.get("error_class") or "").strip().lower()[:80]
                        or None
                    )
                    error_text = str(item.get("error") or "").strip()[:500] or None
                    event_status = str(item.get("status") or "unknown")[:40]
                    cur.execute(
                        """
                        INSERT INTO ih_provider_usage(
                            id,request_id,provider,operation,credits_used,status,
                            ref,latency_ms,error_class,retryable,error_text,attempt
                        ) VALUES (%s,%s,%s,%s,NULL,%s,%s,%s,%s,%s,%s,%s)
                        """,
                        (
                            self._new_id("pru"),
                            request_id,
                            provider,
                            operation,
                            event_status,
                            ref or None,
                            duration_ms,
                            error_class,
                            bool(item.get("retryable")),
                            error_text,
                            attempt,
                        ),
                    )
                    record_provider_reliability_event(cur, item)

                provider_usage = (execution_usage or {}).get("provider_usage") or []
                for item in provider_usage:
                    if not isinstance(item, dict):
                        continue
                    provider = str(item.get("provider") or "")[:80]
                    operation = str(item.get("operation") or "")[:80]
                    if not provider or not operation:
                        continue
                    raw_credits = item.get("credits_used")
                    credits_used = (
                        max(0, int(raw_credits))
                        if isinstance(raw_credits, (int, float)) and not isinstance(raw_credits, bool)
                        else None
                    )
                    cur.execute(
                        """
                        INSERT INTO ih_provider_usage(id,request_id,provider,operation,credits_used,status)
                        VALUES (%s,%s,%s,%s,%s,%s)
                        """,
                        (self._new_id("pru"), request_id, provider, operation, credits_used,
                         str(item.get("status") or "unknown")[:40]),
                    )

                reservation = dict(metadata.get("reservation") or {})
                reserved = max(0, int(reservation.get("credits") or 0))
                raw_actual = None if actual_credits is None else max(0, int(actual_credits))
                actual = reserved if raw_actual is None else _apply_credit_burn(raw_actual)
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
                    "measured_usage": metadata.get("measured_usage") or {},
                    "reservation": {
                        "reserved": reserved,
                        "settled": actual,
                        "raw_settled": raw_actual,
                        "credit_burn_multiplier": credit_burn_multiplier(),
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
                        "raw_settled": raw_actual,
                        "credit_burn_multiplier": credit_burn_multiplier(),
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
        self.reserve_tool_call(
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
            actual_credits=None,
        )

    def finish_usage(
        self,
        request_id: str,
        *,
        status: str,
        latency_ms: int,
        output_bytes: int,
        actual_credits: int | None = None,
        execution_usage: dict[str, Any] | None = None,
    ) -> None:
        self.settle_tool_call(
            request_id,
            status=status,
            latency_ms=latency_ms,
            output_bytes=output_bytes,
            actual_credits=actual_credits,
            execution_usage=execution_usage,
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
            return {
                "wallet": dict(wallet) if wallet else None,
                "ledger": [dict(r) for r in cur.fetchall()],
                "display_currency": "USD",
                "wallet_units_per_usd": WALLET_UNITS_PER_USD,
            }

    def list_connections(self, user_id: str) -> list[dict[str, Any]]:
        self.ensure_schema()
        with self._connect() as conn, conn.cursor() as cur:
            cur.execute(
                """SELECT id,name,kind,endpoint_url,transport,auth_type,config,enabled,last_status,last_checked_at,created_at,updated_at
                   FROM ih_connections WHERE user_id=%s ORDER BY created_at DESC""",
                (user_id,),
            )
            rows = []
            for raw in cur.fetchall():
                row = dict(raw)
                config = dict(row.get("config") or {})
                row["header_names"] = list(config.get("header_names") or [])
                row["tool_count"] = int(config.get("last_tool_count") or 0)
                row["last_error"] = str(config.get("last_error") or "") or None
                rows.append(row)
            return rows

    def create_connection(
        self, *, user_id: str, name: str, endpoint_url: str, transport: str,
        auth_type: str, config: dict[str, Any], secret_config: dict[str, Any],
    ) -> dict[str, Any]:
        self.ensure_schema()
        connection_id = self._new_id("con")
        with self._connect() as conn, conn.cursor() as cur:
            cur.execute(
                """INSERT INTO ih_connections(id,user_id,name,kind,endpoint_url,transport,auth_type,config,secret_config)
                   VALUES (%s,%s,%s,'mcp',%s,%s,%s,%s::jsonb,%s::jsonb)
                   RETURNING id,name,kind,endpoint_url,transport,auth_type,config,enabled,last_status,last_checked_at,created_at,updated_at""",
                (connection_id, user_id, name, endpoint_url, transport, auth_type, json.dumps(config), json.dumps(secret_config)),
            )
            row = dict(cur.fetchone())
            conn.commit()
        row["header_names"] = list((row.get("config") or {}).get("header_names") or [])
        return row

    def get_connection_private(self, user_id: str, connection_id: str) -> dict[str, Any] | None:
        """Load one connection including secret runtime material for server-side execution only."""
        self.ensure_schema()
        with self._connect() as conn, conn.cursor() as cur:
            cur.execute(
                """
                SELECT id,user_id,name,kind,endpoint_url,transport,auth_type,config,secret_config,
                       enabled,last_status,last_checked_at,created_at,updated_at
                FROM ih_connections
                WHERE id=%s AND user_id=%s
                """,
                (connection_id, user_id),
            )
            row = cur.fetchone()
            return dict(row) if row else None

    def set_connection_enabled(self, user_id: str, connection_id: str, enabled: bool) -> bool:
        self.ensure_schema()
        with self._connect() as conn, conn.cursor() as cur:
            cur.execute(
                """
                UPDATE ih_connections
                SET enabled=%s,updated_at=now()
                WHERE id=%s AND user_id=%s
                """,
                (enabled, connection_id, user_id),
            )
            changed = cur.rowcount > 0
            conn.commit()
            return changed

    def update_connection_check(
        self,
        user_id: str,
        connection_id: str,
        *,
        status: str,
        tool_count: int | None,
        error: str | None,
    ) -> None:
        self.ensure_schema()
        detail = {
            "last_tool_count": int(tool_count or 0),
            "last_error": (error or "")[:300] or None,
        }
        with self._connect() as conn, conn.cursor() as cur:
            cur.execute(
                """
                UPDATE ih_connections
                SET last_status=%s,
                    last_checked_at=now(),
                    config=COALESCE(config,'{}'::jsonb) || %s::jsonb,
                    updated_at=now()
                WHERE id=%s AND user_id=%s
                """,
                (status, json.dumps(detail), connection_id, user_id),
            )
            conn.commit()

    def delete_connection(self, user_id: str, connection_id: str) -> bool:
        self.ensure_schema()
        with self._connect() as conn, conn.cursor() as cur:
            cur.execute("DELETE FROM ih_connections WHERE id=%s AND user_id=%s", (connection_id, user_id))
            changed = cur.rowcount > 0
            conn.commit()
            return changed

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
        currency: str = "INR",
        metadata: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        self.ensure_schema()
        payment_row_id = self._new_id("pay")
        with self._connect() as conn, conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO ih_payments(
                    id,user_id,order_id,amount_paise,currency,status,purpose,plan_slug,credit_pack_slug,metadata
                ) VALUES (%s,%s,%s,%s,%s,'created',%s,%s,%s,%s::jsonb)
                RETURNING *
                """,
                (
                    payment_row_id, user_id, order_id, amount_paise, currency.upper(), purpose,
                    plan_slug, credit_pack_slug, json.dumps(metadata or {}),
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
                    metadata = dict(payment.get("metadata") or {})
                    pack_slug = payment.get("credit_pack_slug")
                    if pack_slug:
                        cur.execute(
                            "SELECT credits FROM ih_credit_packs WHERE slug=%s AND active=true",
                            (pack_slug,),
                        )
                        pack = cur.fetchone()
                        if not pack:
                            raise ControlError("credit_pack_not_found", "credit pack not found", 404)
                        credits = int(pack["credits"])
                        topup_mode = "preset"
                    else:
                        credits = int(metadata.get("wallet_units") or 0)
                        usd_cents = int(metadata.get("wallet_usd_cents") or 0)
                        if credits <= 0 or usd_cents <= 0:
                            raise ControlError(
                                "invalid_custom_topup",
                                "custom wallet top-up metadata is invalid",
                                409,
                            )
                        if (
                            str(payment.get("currency") or "").upper() != "USD"
                            or int(payment.get("amount_paise") or 0) != usd_cents
                        ):
                            raise ControlError(
                                "wallet_payment_mismatch",
                                "custom wallet top-up does not match the captured payment amount",
                                409,
                            )
                        expected_units = usd_cents * WALLET_UNITS_PER_USD // 100
                        if credits != expected_units:
                            raise ControlError(
                                "wallet_amount_mismatch",
                                "custom wallet top-up amount does not match the configured denomination",
                                409,
                            )
                        topup_mode = "custom"
                    cur.execute(
                        "UPDATE ih_wallets SET purchased_credits=purchased_credits+%s,updated_at=now() WHERE user_id=%s",
                        (credits, user_id),
                    )
                    cur.execute(
                        """
                        INSERT INTO ih_credit_ledger(
                            id,user_id,amount,bucket,kind,source,reference_id,metadata
                        )
                        VALUES (%s,%s,%s,'purchased','purchase','razorpay',%s,%s::jsonb)
                        """,
                        (
                            self._new_id("led"),
                            user_id,
                            credits,
                            order_id,
                            json.dumps(
                                {
                                    "display_currency": "USD",
                                    "wallet_units_per_usd": WALLET_UNITS_PER_USD,
                                    "topup_mode": topup_mode,
                                    "payment_currency": str(payment.get("currency") or "INR"),
                                    "payment_amount_minor": int(payment.get("amount_paise") or 0),
                                    "wallet_usd_cents": int(metadata.get("wallet_usd_cents") or 0)
                                    if topup_mode == "custom"
                                    else None,
                                }
                            ),
                        ),
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

    def password_reset_user(self, token_hash: str) -> dict[str, Any] | None:
        """Resolve a still-valid compatibility reset without consuming it."""
        self.ensure_schema()
        with self._connect() as conn, conn.cursor() as cur:
            cur.execute(
                """
                SELECT u.id,u.email,u.display_name,u.email_verified
                FROM ih_password_resets r
                JOIN ih_users u ON u.id=r.user_id
                WHERE r.token_hash=%s AND r.used_at IS NULL AND r.expires_at>now()
                LIMIT 1
                """,
                (token_hash,),
            )
            row = cur.fetchone()
            return dict(row) if row else None

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
