from __future__ import annotations

import json
import os
import re
import threading
import uuid
from typing import Any

from fastapi import APIRouter, Request

from .control_api import _json_error, _require_user, _require_verified, store
from .control_store import WALLET_UNITS_PER_USD, ControlError

router = APIRouter()

_REWARD_SCHEMA_READY = False
_REWARD_SCHEMA_LOCK = threading.Lock()

# Reward points are intentionally separate from the USD service wallet.
# By default, every $0.05 of metered OpenCrawl spend earns one reward point.
DEFAULT_REWARD_UNITS_PER_POINT = 250

REWARD_ROWS = (
    (
        "wallet-025",
        "$0.25 wallet credit",
        "Add $0.25 of rollover OpenCrawl balance to your wallet.",
        100,
        "wallet_credit",
        1_250,
        10,
    ),
    (
        "wallet-100",
        "$1 wallet credit",
        "Add $1.00 of rollover OpenCrawl balance to your wallet.",
        350,
        "wallet_credit",
        5_000,
        20,
    ),
    (
        "wallet-500",
        "$5 wallet credit",
        "Add $5.00 of rollover OpenCrawl balance to your wallet.",
        1_500,
        "wallet_credit",
        25_000,
        30,
    ),
)

REWARDS_SCHEMA_SQL = r"""
CREATE TABLE IF NOT EXISTS ih_reward_accounts (
    user_id text PRIMARY KEY REFERENCES ih_users(id) ON DELETE CASCADE,
    points bigint NOT NULL DEFAULT 0 CHECK (points >= 0),
    lifetime_earned bigint NOT NULL DEFAULT 0 CHECK (lifetime_earned >= 0),
    lifetime_redeemed bigint NOT NULL DEFAULT 0 CHECK (lifetime_redeemed >= 0),
    usage_points_credited bigint NOT NULL DEFAULT 0 CHECK (usage_points_credited >= 0),
    usage_wallet_units_processed bigint NOT NULL DEFAULT 0 CHECK (usage_wallet_units_processed >= 0),
    updated_at timestamptz NOT NULL DEFAULT now()
);
ALTER TABLE ih_reward_accounts
    ADD COLUMN IF NOT EXISTS usage_wallet_units_processed bigint NOT NULL DEFAULT 0;

CREATE TABLE IF NOT EXISTS ih_reward_catalog (
    slug text PRIMARY KEY,
    name text NOT NULL,
    description text NOT NULL,
    points_cost bigint NOT NULL CHECK (points_cost > 0),
    fulfillment_type text NOT NULL CHECK (fulfillment_type IN ('wallet_credit', 'manual')),
    fulfillment_value bigint NOT NULL DEFAULT 0 CHECK (fulfillment_value >= 0),
    metadata jsonb NOT NULL DEFAULT '{}'::jsonb,
    active boolean NOT NULL DEFAULT true,
    sort_order integer NOT NULL DEFAULT 0,
    updated_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS ih_reward_redemptions (
    id text PRIMARY KEY,
    user_id text NOT NULL REFERENCES ih_users(id) ON DELETE CASCADE,
    reward_slug text NOT NULL REFERENCES ih_reward_catalog(slug),
    reward_name text NOT NULL,
    points_spent bigint NOT NULL CHECK (points_spent > 0),
    status text NOT NULL CHECK (status IN ('pending', 'fulfilled', 'failed', 'cancelled')),
    fulfillment_type text NOT NULL,
    fulfillment_value bigint NOT NULL DEFAULT 0,
    fulfillment_reference text,
    idempotency_key text,
    metadata jsonb NOT NULL DEFAULT '{}'::jsonb,
    created_at timestamptz NOT NULL DEFAULT now(),
    fulfilled_at timestamptz
);
ALTER TABLE ih_reward_redemptions
    ADD COLUMN IF NOT EXISTS idempotency_key text;
CREATE INDEX IF NOT EXISTS ih_reward_redemptions_user_idx
    ON ih_reward_redemptions(user_id, created_at DESC);
CREATE UNIQUE INDEX IF NOT EXISTS ih_reward_redemptions_user_idempotency_idx
    ON ih_reward_redemptions(user_id, idempotency_key)
    WHERE idempotency_key IS NOT NULL;

CREATE TABLE IF NOT EXISTS ih_reward_ledger (
    id text PRIMARY KEY,
    user_id text NOT NULL REFERENCES ih_users(id) ON DELETE CASCADE,
    amount bigint NOT NULL,
    kind text NOT NULL,
    source text NOT NULL,
    reference_id text,
    dedupe_key text UNIQUE,
    metadata jsonb NOT NULL DEFAULT '{}'::jsonb,
    created_at timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS ih_reward_ledger_user_idx
    ON ih_reward_ledger(user_id, created_at DESC);
"""


def _new_id(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex}"


def _reward_units_per_point() -> int:
    try:
        value = int(os.getenv("OPENCRAWL_REWARD_UNITS_PER_POINT", str(DEFAULT_REWARD_UNITS_PER_POINT)))
    except (TypeError, ValueError):
        value = DEFAULT_REWARD_UNITS_PER_POINT
    return max(1, min(value, WALLET_UNITS_PER_USD * 100))


def _points_from_usage(wallet_units: int) -> int:
    return max(0, int(wallet_units)) // _reward_units_per_point()


def _accrual_delta(
    total_wallet_units: int,
    processed_wallet_units: int,
    units_per_point: int,
) -> tuple[int, int]:
    """Return newly earned points and the wallet units consumed by that accrual."""
    available = max(0, int(total_wallet_units) - max(0, int(processed_wallet_units)))
    rate = max(1, int(units_per_point))
    points = available // rate
    return points, points * rate


def ensure_rewards_schema() -> None:
    global _REWARD_SCHEMA_READY
    if _REWARD_SCHEMA_READY:
        return
    with _REWARD_SCHEMA_LOCK:
        if _REWARD_SCHEMA_READY:
            return
        store.ensure_schema()
        with store._connect() as conn, conn.cursor() as cur:
            cur.execute(REWARDS_SCHEMA_SQL)
            for slug, name, description, points_cost, fulfillment_type, fulfillment_value, sort_order in REWARD_ROWS:
                cur.execute(
                    """
                    INSERT INTO ih_reward_catalog(
                        slug,name,description,points_cost,fulfillment_type,
                        fulfillment_value,sort_order
                    )
                    VALUES (%s,%s,%s,%s,%s,%s,%s)
                    ON CONFLICT (slug) DO UPDATE SET
                        name=EXCLUDED.name,
                        description=EXCLUDED.description,
                        points_cost=EXCLUDED.points_cost,
                        fulfillment_type=EXCLUDED.fulfillment_type,
                        fulfillment_value=EXCLUDED.fulfillment_value,
                        sort_order=EXCLUDED.sort_order,
                        active=true,
                        updated_at=now()
                    """,
                    (
                        slug,
                        name,
                        description,
                        points_cost,
                        fulfillment_type,
                        fulfillment_value,
                        sort_order,
                    ),
                )
            conn.commit()
        _REWARD_SCHEMA_READY = True


def _ensure_reward_account(cur: Any, user_id: str) -> None:
    cur.execute(
        """
        INSERT INTO ih_reward_accounts(user_id)
        VALUES (%s)
        ON CONFLICT (user_id) DO NOTHING
        """,
        (user_id,),
    )


def _sync_usage_points(cur: Any, user_id: str) -> int:
    """Convert only previously unprocessed metered wallet spend into reward points."""
    _ensure_reward_account(cur, user_id)
    cur.execute(
        """
        SELECT COALESCE(sum(credits_charged), 0)::bigint AS wallet_units
        FROM ih_usage_events
        WHERE user_id=%s AND credits_charged > 0
        """,
        (user_id,),
    )
    usage_row = cur.fetchone() or {}
    total_wallet_units = int(usage_row.get("wallet_units") or 0)

    cur.execute(
        """
        SELECT points,lifetime_earned,lifetime_redeemed,usage_points_credited,
               usage_wallet_units_processed
        FROM ih_reward_accounts
        WHERE user_id=%s
        FOR UPDATE
        """,
        (user_id,),
    )
    account = cur.fetchone()
    if not account:
        raise ControlError("reward_account_missing", "reward account is unavailable", 503)

    rate = _reward_units_per_point()
    processed = int(account.get("usage_wallet_units_processed") or 0)

    # Compatibility for accounts that earned points before wallet-unit tracking existed.
    legacy_points = int(account.get("usage_points_credited") or 0)
    if processed == 0 and legacy_points > 0:
        processed = min(total_wallet_units, legacy_points * rate)
        cur.execute(
            """
            UPDATE ih_reward_accounts
            SET usage_wallet_units_processed=%s,updated_at=now()
            WHERE user_id=%s
            """,
            (processed, user_id),
        )

    delta, consumed_units = _accrual_delta(total_wallet_units, processed, rate)
    if delta <= 0:
        return 0

    processed_after = processed + consumed_units
    cur.execute(
        """
        UPDATE ih_reward_accounts
        SET points=points+%s,
            lifetime_earned=lifetime_earned+%s,
            usage_points_credited=usage_points_credited+%s,
            usage_wallet_units_processed=%s,
            updated_at=now()
        WHERE user_id=%s
        """,
        (delta, delta, delta, processed_after, user_id),
    )
    cur.execute(
        """
        INSERT INTO ih_reward_ledger(
            id,user_id,amount,kind,source,reference_id,dedupe_key,metadata
        )
        VALUES (%s,%s,%s,'earn','metered_usage',%s,%s,%s::jsonb)
        ON CONFLICT (dedupe_key) DO NOTHING
        """,
        (
            _new_id("rled"),
            user_id,
            delta,
            str(processed_after),
            f"usage-units:{user_id}:{processed_after}",
            json.dumps(
                {
                    "wallet_units_per_point": rate,
                    "wallet_units_observed": total_wallet_units,
                    "wallet_units_processed": processed_after,
                    "wallet_units_consumed": consumed_units,
                }
            ),
        ),
    )
    return delta


def rewards_snapshot(user_id: str, limit: int = 80) -> dict[str, Any]:
    ensure_rewards_schema()
    bounded = max(1, min(int(limit), 200))
    with store._connect() as conn, conn.cursor() as cur:
        earned_now = _sync_usage_points(cur, user_id)
        cur.execute("SELECT * FROM ih_reward_accounts WHERE user_id=%s", (user_id,))
        account = cur.fetchone()
        cur.execute(
            """
            SELECT slug,name,description,points_cost,fulfillment_type,
                   fulfillment_value,metadata,sort_order
            FROM ih_reward_catalog
            WHERE active=true
            ORDER BY sort_order,points_cost,slug
            """
        )
        catalog = [dict(row) for row in cur.fetchall()]
        cur.execute(
            """
            SELECT id,reward_slug,reward_name,points_spent,status,fulfillment_type,
                   fulfillment_value,fulfillment_reference,idempotency_key,metadata,
                   created_at,fulfilled_at
            FROM ih_reward_redemptions
            WHERE user_id=%s
            ORDER BY created_at DESC
            LIMIT %s
            """,
            (user_id, bounded),
        )
        redemptions = [dict(row) for row in cur.fetchall()]
        cur.execute(
            """
            SELECT id,amount,kind,source,reference_id,metadata,created_at
            FROM ih_reward_ledger
            WHERE user_id=%s
            ORDER BY created_at DESC
            LIMIT %s
            """,
            (user_id, bounded),
        )
        ledger = [dict(row) for row in cur.fetchall()]
        cur.execute(
            """
            SELECT monthly_credits,purchased_credits,reserved_credits
            FROM ih_wallets
            WHERE user_id=%s
            """,
            (user_id,),
        )
        wallet = cur.fetchone()
        conn.commit()

    units_per_point = _reward_units_per_point()
    return {
        "account": dict(account) if account else {
            "user_id": user_id,
            "points": 0,
            "lifetime_earned": 0,
            "lifetime_redeemed": 0,
            "usage_points_credited": 0,
            "usage_wallet_units_processed": 0,
        },
        "catalog": catalog,
        "redemptions": redemptions,
        "ledger": ledger,
        "wallet": dict(wallet) if wallet else None,
        "earned_now": earned_now,
        "display_currency": "USD",
        "wallet_units_per_usd": WALLET_UNITS_PER_USD,
        "earning_rule": {
            "source": "metered_usage",
            "wallet_units_per_point": units_per_point,
            "usd_spend_per_point": units_per_point / WALLET_UNITS_PER_USD,
        },
    }


def redeem_reward(
    user_id: str,
    slug: str,
    *,
    idempotency_key: str | None,
) -> dict[str, Any]:
    ensure_rewards_schema()
    normalized_slug = str(slug or "").strip().lower()
    if not normalized_slug:
        raise ControlError("reward_required", "reward is required", 400)

    key = str(idempotency_key or "").strip()
    if not re.fullmatch(r"[A-Za-z0-9._:-]{8,128}", key):
        raise ControlError(
            "invalid_idempotency_key",
            "Idempotency-Key must be 8-128 URL-safe characters",
            400,
        )

    with store._connect() as conn, conn.cursor() as cur:
        # Serialize retries of the same redemption intent before checking for replay.
        cur.execute(
            "SELECT pg_advisory_xact_lock(hashtextextended(%s, 0))",
            (f"{user_id}:{key}",),
        )
        _sync_usage_points(cur, user_id)
        cur.execute(
            """
            SELECT id,reward_slug,reward_name,points_spent,status,fulfillment_type,
                   fulfillment_value,fulfillment_reference,idempotency_key,metadata,
                   created_at,fulfilled_at
            FROM ih_reward_redemptions
            WHERE user_id=%s AND idempotency_key=%s
            """,
            (user_id, key),
        )
        replay = cur.fetchone()
        if replay:
            cur.execute("SELECT * FROM ih_reward_accounts WHERE user_id=%s", (user_id,))
            updated_account = cur.fetchone()
            cur.execute(
                "SELECT monthly_credits,purchased_credits,reserved_credits FROM ih_wallets WHERE user_id=%s",
                (user_id,),
            )
            wallet = cur.fetchone()
            conn.commit()
            return {
                "ok": True,
                "replayed": True,
                "redemption": dict(replay),
                "account": dict(updated_account) if updated_account else None,
                "wallet": dict(wallet) if wallet else None,
                "display_currency": "USD",
                "wallet_units_per_usd": WALLET_UNITS_PER_USD,
            }
        cur.execute(
            """
            SELECT slug,name,description,points_cost,fulfillment_type,
                   fulfillment_value,metadata
            FROM ih_reward_catalog
            WHERE slug=%s AND active=true
            FOR UPDATE
            """,
            (normalized_slug,),
        )
        reward = cur.fetchone()
        if not reward:
            raise ControlError("reward_not_found", "reward is unavailable", 404)

        cur.execute(
            """
            SELECT points,lifetime_earned,lifetime_redeemed,usage_points_credited
            FROM ih_reward_accounts
            WHERE user_id=%s
            FOR UPDATE
            """,
            (user_id,),
        )
        account = cur.fetchone()
        if not account:
            raise ControlError("reward_account_missing", "reward account is unavailable", 503)

        cost = int(reward["points_cost"])
        balance = int(account["points"])
        if balance < cost:
            raise ControlError(
                "insufficient_reward_points",
                f"{cost - balance} more reward points are required",
                409,
            )

        redemption_id = _new_id("rwd")
        cur.execute(
            """
            UPDATE ih_reward_accounts
            SET points=points-%s,
                lifetime_redeemed=lifetime_redeemed+%s,
                updated_at=now()
            WHERE user_id=%s
            """,
            (cost, cost, user_id),
        )
        cur.execute(
            """
            INSERT INTO ih_reward_ledger(
                id,user_id,amount,kind,source,reference_id,dedupe_key,metadata
            )
            VALUES (%s,%s,%s,'redeem','reward_catalog',%s,%s,%s::jsonb)
            """,
            (
                _new_id("rled"),
                user_id,
                -cost,
                redemption_id,
                f"redeem:{redemption_id}",
                json.dumps({"reward_slug": normalized_slug, "reward_name": reward["name"]}),
            ),
        )
        cur.execute(
            """
            INSERT INTO ih_reward_redemptions(
                id,user_id,reward_slug,reward_name,points_spent,status,
                fulfillment_type,fulfillment_value,idempotency_key,metadata
            )
            VALUES (%s,%s,%s,%s,%s,'pending',%s,%s,%s,%s::jsonb)
            """,
            (
                redemption_id,
                user_id,
                normalized_slug,
                reward["name"],
                cost,
                reward["fulfillment_type"],
                int(reward["fulfillment_value"] or 0),
                key,
                json.dumps(dict(reward.get("metadata") or {})),
            ),
        )

        if reward["fulfillment_type"] == "wallet_credit":
            wallet_units = int(reward["fulfillment_value"] or 0)
            if wallet_units <= 0:
                raise ControlError("invalid_reward", "wallet reward value is invalid", 409)
            cur.execute(
                """
                INSERT INTO ih_wallets(user_id,purchased_credits)
                VALUES (%s,%s)
                ON CONFLICT (user_id) DO UPDATE SET
                    purchased_credits=ih_wallets.purchased_credits+EXCLUDED.purchased_credits,
                    updated_at=now()
                """,
                (user_id, wallet_units),
            )
            credit_ledger_id = store._new_id("led")
            cur.execute(
                """
                INSERT INTO ih_credit_ledger(
                    id,user_id,amount,bucket,kind,source,reference_id,metadata
                )
                VALUES (%s,%s,%s,'purchased','reward','rewards',%s,%s::jsonb)
                """,
                (
                    credit_ledger_id,
                    user_id,
                    wallet_units,
                    redemption_id,
                    json.dumps(
                        {
                            "reward_slug": normalized_slug,
                            "reward_name": reward["name"],
                            "points_spent": cost,
                            "display_currency": "USD",
                            "wallet_units_per_usd": WALLET_UNITS_PER_USD,
                        }
                    ),
                ),
            )
            cur.execute(
                """
                UPDATE ih_reward_redemptions
                SET status='fulfilled',
                    fulfillment_reference=%s,
                    fulfilled_at=now()
                WHERE id=%s
                """,
                (credit_ledger_id, redemption_id),
            )

        cur.execute(
            """
            SELECT id,reward_slug,reward_name,points_spent,status,fulfillment_type,
                   fulfillment_value,fulfillment_reference,metadata,created_at,fulfilled_at
            FROM ih_reward_redemptions
            WHERE id=%s
            """,
            (redemption_id,),
        )
        redemption = cur.fetchone()
        cur.execute("SELECT * FROM ih_reward_accounts WHERE user_id=%s", (user_id,))
        updated_account = cur.fetchone()
        cur.execute(
            "SELECT monthly_credits,purchased_credits,reserved_credits FROM ih_wallets WHERE user_id=%s",
            (user_id,),
        )
        wallet = cur.fetchone()
        conn.commit()

    return {
        "ok": True,
        "redemption": dict(redemption) if redemption else None,
        "account": dict(updated_account) if updated_account else None,
        "wallet": dict(wallet) if wallet else None,
        "display_currency": "USD",
        "wallet_units_per_usd": WALLET_UNITS_PER_USD,
    }


@router.get("/api/rewards")
def rewards(request: Request, limit: int = 80):
    user = _require_user(request)
    return rewards_snapshot(str(user["id"]), limit=limit)


@router.post("/api/rewards/{reward_slug}/redeem")
def redeem(reward_slug: str, request: Request):
    user = _require_verified(_require_user(request))
    try:
        return redeem_reward(
            str(user["id"]),
            reward_slug,
            idempotency_key=request.headers.get("idempotency-key"),
        )
    except ControlError as exc:
        raise _json_error(exc) from exc
