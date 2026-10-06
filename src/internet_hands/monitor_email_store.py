"""Owned opt-in preferences and a transactional, fenced email outbox."""
from __future__ import annotations

import json
import uuid

from .control_store import ControlError
from .monitor_emails import (
    MAX_ATTEMPTS,
    MAX_BATCH,
    SEND_WINDOW_HOURS,
    render_change_email,
    render_test_email,
    selected_changes,
)

SCHEMA = """
CREATE TABLE IF NOT EXISTS ih_monitor_email_preferences (
    monitor_id text PRIMARY KEY REFERENCES ih_monitors(id) ON DELETE CASCADE,
    user_id text NOT NULL REFERENCES ih_users(id) ON DELETE CASCADE,
    enabled boolean NOT NULL DEFAULT false,
    fields jsonb NOT NULL DEFAULT '["price","availability"]'::jsonb,
    version integer NOT NULL DEFAULT 1,
    consent_at timestamptz,
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now()
);
CREATE TABLE IF NOT EXISTS ih_monitor_email_deliveries (
    id text PRIMARY KEY,
    user_id text NOT NULL REFERENCES ih_users(id) ON DELETE CASCADE,
    monitor_id text NOT NULL REFERENCES ih_monitors(id) ON DELETE CASCADE,
    monitor_run_id text UNIQUE REFERENCES ih_monitor_runs(id) ON DELETE CASCADE,
    dataset_id text REFERENCES ih_datasets(id) ON DELETE CASCADE,
    kind text NOT NULL CHECK(kind IN ('change','test')),
    monitor_version integer NOT NULL,
    preference_version integer NOT NULL,
    recipient text NOT NULL,
    message jsonb NOT NULL,
    request_payload jsonb,
    status text NOT NULL DEFAULT 'pending' CHECK(status IN
        ('pending','sending','retry','accepted','delivered','bounced','complained','failed','cancelled','unknown')),
    attempts integer NOT NULL DEFAULT 0,
    next_attempt_at timestamptz NOT NULL DEFAULT now(),
    first_dispatch_at timestamptz,
    send_started_at timestamptz,
    lease_token text,
    lease_until timestamptz,
    may_have_sent boolean NOT NULL DEFAULT false,
    provider_id text,
    provider_event text,
    last_error text,
    accepted_at timestamptz,
    delivered_at timestamptz,
    receipt_attempts integer NOT NULL DEFAULT 0,
    next_receipt_at timestamptz,
    receipt_lease_token text,
    receipt_lease_until timestamptz,
    last_receipt_at timestamptz,
    receipt_error text,
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS ih_monitor_email_due_idx ON ih_monitor_email_deliveries(status,next_attempt_at);
CREATE INDEX IF NOT EXISTS ih_monitor_email_owner_idx ON ih_monitor_email_deliveries(user_id,monitor_id,created_at DESC);
"""

PUBLIC = "id,monitor_run_id,dataset_id,kind,status,attempts,next_attempt_at,last_error,provider_event,accepted_at,delivered_at,receipt_error,last_receipt_at,created_at,updated_at"
ACTIVE = """m.type='product' AND m.enabled=true AND p.enabled=true
    AND m.content_version=d.monitor_version AND p.version=d.preference_version
    AND u.email_verified=true AND u.email=d.recipient"""
RETRYABLE = f"""d.status IN ('failed','unknown') AND d.provider_id IS NULL
    AND (d.first_dispatch_at IS NULL OR d.first_dispatch_at>now()-interval '{SEND_WINDOW_HOURS} hours')
    AND d.created_at>now()-interval '30 days' AND {ACTIVE}"""
CHECKABLE = "d.status='accepted' AND d.provider_id IS NOT NULL AND d.receipt_attempts<24 AND d.accepted_at>now()-interval '7 days'"


def _enqueue(cur, monitor, preferences, recipient, message, *, kind, run_id=None, dataset_id=None):
    event_id = "mail_" + uuid.uuid4().hex
    cur.execute("""INSERT INTO ih_monitor_email_deliveries
        (id,user_id,monitor_id,monitor_run_id,dataset_id,kind,monitor_version,preference_version,recipient,message)
        VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s::jsonb)
        ON CONFLICT(monitor_run_id) DO NOTHING RETURNING *""",
        (event_id, monitor["user_id"], monitor["id"], run_id, dataset_id, kind, monitor["content_version"],
         preferences["version"], recipient, json.dumps(message)))
    row = cur.fetchone()
    return dict(row) if row else None


def enqueue_change_email(cur, monitor, run_id, dataset_id, changes, products):
    # The monitor row is already locked by native completion; preference changes
    # take that same lock before changing consent or cancelling unsent events.
    if not changes:
        return
    cur.execute("""SELECT p.*,u.email,u.email_verified FROM ih_monitor_email_preferences p
        JOIN ih_users u ON u.id=p.user_id WHERE p.monitor_id=%s AND p.enabled=true""", (monitor["id"],))
    preferences = cur.fetchone()
    if not preferences or not preferences["email_verified"]:
        return
    fields = [f for f in preferences["fields"] if f in monitor["config"]["fields"]]
    filtered = selected_changes(changes, fields) if fields else []
    if not filtered:
        return
    message = render_change_email(monitor, filtered, fields, {row["product_id"]: row["name"] for row in products})
    _enqueue(cur, monitor, preferences, preferences["email"], message, kind="change", run_id=run_id, dataset_id=dataset_id)


class MonitorEmailStore:
    def __init__(self, control):
        self.control = control

    @staticmethod
    def _monitor(cur, owner, monitor_id):
        cur.execute("SELECT * FROM ih_monitors WHERE id=%s AND user_id=%s AND type='product' FOR UPDATE", (monitor_id, owner))
        monitor = cur.fetchone()
        if not monitor:
            raise ControlError("monitor_not_found", "Product tracker not found for this account.", 404)
        return monitor

    def settings(self, owner, monitor_id):
        self.control.ensure_schema()
        with self.control._connect() as conn, conn.cursor() as cur:
            monitor = self._monitor(cur, owner, monitor_id)
            cur.execute("SELECT enabled,fields,consent_at,updated_at FROM ih_monitor_email_preferences WHERE monitor_id=%s", (monitor_id,))
            prefs = cur.fetchone() or {"enabled": False, "fields": monitor["config"]["fields"], "consent_at": None}
            cur.execute("SELECT email,email_verified FROM ih_users WHERE id=%s", (owner,))
            user = cur.fetchone()
            cur.execute("SELECT COALESCE(sum(credits_charged),0) AS spent,count(*) AS checks FROM ih_monitor_runs WHERE monitor_id=%s", (monitor_id,))
            stats = cur.fetchone()
            return {"preferences": dict(prefs), "recipient": user["email"], "email_verified": user["email_verified"],
                    "credits_spent": stats["spent"], "checks": stats["checks"]}

    def configure(self, owner, monitor_id, *, enabled, fields, confirm_email):
        if type(enabled) is not bool or type(confirm_email) is not bool:
            raise ControlError("invalid_email_preferences", "Email preferences require boolean consent controls.", 422)
        if not isinstance(fields, list) or any(not isinstance(f, str) or f not in {"price", "availability"} for f in fields):
            raise ControlError("invalid_email_preferences", "Select price and/or availability for email alerts.", 422)
        if enabled and (not confirm_email or not fields):
            raise ControlError("email_consent_required", "Explicitly opt in and select a field before enabling change emails.", 422)
        self.control.ensure_schema()
        with self.control._connect() as conn, conn.cursor() as cur:
            monitor = self._monitor(cur, owner, monitor_id)
            if set(fields) - set(monitor["config"]["fields"]):
                raise ControlError("invalid_email_preferences", "Email fields must be fields this tracker watches.", 422)
            cur.execute("SELECT email_verified FROM ih_users WHERE id=%s", (owner,))
            if enabled and not cur.fetchone()["email_verified"]:
                raise ControlError("email_not_verified", "Verify your account email before enabling alerts.", 403)
            cur.execute("""INSERT INTO ih_monitor_email_preferences(monitor_id,user_id,enabled,fields,consent_at)
                VALUES (%s,%s,%s,%s::jsonb,CASE WHEN %s THEN now() ELSE NULL END)
                ON CONFLICT(monitor_id) DO UPDATE SET enabled=excluded.enabled,fields=excluded.fields,
                version=ih_monitor_email_preferences.version+CASE WHEN
                    ih_monitor_email_preferences.enabled IS DISTINCT FROM excluded.enabled OR
                    ih_monitor_email_preferences.fields IS DISTINCT FROM excluded.fields THEN 1 ELSE 0 END,
                consent_at=CASE WHEN excluded.enabled THEN COALESCE(ih_monitor_email_preferences.consent_at,now()) ELSE NULL END,
                updated_at=now() RETURNING version""", (monitor_id, owner, enabled, json.dumps(sorted(set(fields))), enabled))
            version = cur.fetchone()["version"]
            cur.execute("""UPDATE ih_monitor_email_deliveries SET status='cancelled',lease_token=NULL,lease_until=NULL,
                last_error='Email preferences changed before dispatch.',updated_at=now()
                WHERE monitor_id=%s AND (preference_version<>%s OR %s=false)
                  AND (status IN ('pending','retry') OR (status='sending' AND send_started_at IS NULL))""", (monitor_id, version, enabled))
        return self.settings(owner, monitor_id)

    def test_email(self, owner, monitor_id):
        self.control.ensure_schema()
        with self.control._connect() as conn, conn.cursor() as cur:
            monitor = self._monitor(cur, owner, monitor_id)
            cur.execute("""SELECT p.*,u.email,u.email_verified FROM ih_monitor_email_preferences p
                JOIN ih_users u ON u.id=p.user_id WHERE p.monitor_id=%s""", (monitor_id,))
            prefs = cur.fetchone()
            if not prefs or not prefs["enabled"] or not prefs["email_verified"] or not monitor["enabled"]:
                raise ControlError("email_alerts_disabled", "Enable email alerts on an active tracker before sending a test.", 409)
            # Account/monitor lock makes retries and concurrent test clicks reuse
            # one event. Test mail never creates a collection or charges credits.
            cur.execute("""SELECT * FROM ih_monitor_email_deliveries WHERE monitor_id=%s AND kind='test'
                AND created_at>now()-interval '10 minutes' ORDER BY created_at DESC LIMIT 1""", (monitor_id,))
            existing = cur.fetchone()
            if existing:
                return dict(existing)
            return _enqueue(cur, monitor, prefs, prefs["email"], render_test_email(monitor), kind="test")

    def history(self, owner, monitor_id, limit=25):
        self.control.ensure_schema()
        with self.control._connect() as conn, conn.cursor() as cur:
            self._monitor(cur, owner, monitor_id)
            cur.execute(f"""SELECT {','.join('d.' + f for f in PUBLIC.split(','))},({RETRYABLE}) AS can_retry,({CHECKABLE}) AS can_check
                FROM ih_monitor_email_deliveries d JOIN ih_monitors m ON m.id=d.monitor_id
                JOIN ih_monitor_email_preferences p ON p.monitor_id=m.id JOIN ih_users u ON u.id=d.user_id
                WHERE d.user_id=%s AND d.monitor_id=%s ORDER BY d.created_at DESC,d.id DESC LIMIT %s""", (owner, monitor_id, limit))
            return {"deliveries": [dict(row) for row in cur.fetchall()]}

    def retry(self, owner, monitor_id, event_id):
        self.control.ensure_schema()
        with self.control._connect() as conn, conn.cursor() as cur:
            self._monitor(cur, owner, monitor_id)
            cur.execute(f"""UPDATE ih_monitor_email_deliveries d SET status='pending',attempts=0,
                next_attempt_at=now(),lease_token=NULL,lease_until=NULL,send_started_at=NULL,last_error=NULL,updated_at=now()
                FROM ih_monitors m,ih_monitor_email_preferences p,ih_users u
                WHERE d.id=%s AND d.user_id=%s AND d.monitor_id=%s AND m.id=d.monitor_id
                  AND p.monitor_id=m.id AND u.id=d.user_id AND {RETRYABLE} RETURNING d.id""", (event_id, owner, monitor_id))
            if not cur.fetchone():
                self._event_or_error(cur, owner, monitor_id, event_id)
                raise ControlError("email_not_retryable", "This alert cannot be safely retried. Accepted emails are never resent.", 409)

    @staticmethod
    def _event_or_error(cur, owner, monitor_id, event_id):
        cur.execute("SELECT id FROM ih_monitor_email_deliveries WHERE id=%s AND user_id=%s AND monitor_id=%s", (event_id, owner, monitor_id))
        if not cur.fetchone():
            raise ControlError("delivery_not_found", "Email delivery not found for this account.", 404)

    def request_receipt(self, owner, monitor_id, event_id):
        self.control.ensure_schema()
        with self.control._connect() as conn, conn.cursor() as cur:
            self._monitor(cur, owner, monitor_id)
            self._event_or_error(cur, owner, monitor_id, event_id)
            cur.execute("""UPDATE ih_monitor_email_deliveries SET next_receipt_at=now()
                WHERE id=%s AND status='accepted' AND provider_id IS NOT NULL
                  AND (last_receipt_at IS NULL OR last_receipt_at<now()-interval '30 seconds')
                  AND accepted_at>now()-interval '7 days'""", (event_id,))

    def claim(self, limit=MAX_BATCH, event_id=None):
        self.control.ensure_schema()
        with self.control._connect() as conn, conn.cursor() as cur:
            cur.execute("DELETE FROM ih_monitor_email_deliveries WHERE created_at<now()-interval '30 days'")
            cur.execute(f"""UPDATE ih_monitor_email_deliveries d SET status='cancelled',lease_token=NULL,lease_until=NULL,
                last_error='Tracking, consent, or verified recipient changed before dispatch.',updated_at=now()
                WHERE (status IN ('pending','retry') OR (status='sending' AND lease_until<=now()))
                  AND NOT EXISTS (SELECT 1 FROM ih_monitors m JOIN ih_monitor_email_preferences p ON p.monitor_id=m.id
                      JOIN ih_users u ON u.id=d.user_id WHERE m.id=d.monitor_id AND {ACTIVE})""")
            cur.execute(f"""UPDATE ih_monitor_email_deliveries SET status='unknown',lease_token=NULL,lease_until=NULL,
                last_error='The safe retry window expired; this email may already have been sent.',updated_at=now()
                WHERE (status IN ('pending','retry') OR (status='sending' AND lease_until<=now()))
                  AND first_dispatch_at<=now()-interval '{SEND_WINDOW_HOURS} hours'""")
            cur.execute("""UPDATE ih_monitor_email_deliveries SET status=CASE WHEN may_have_sent OR send_started_at IS NOT NULL
                THEN 'unknown' ELSE 'failed' END,lease_token=NULL,lease_until=NULL,
                last_error='Email delivery could not be confirmed after the final attempt.',updated_at=now()
                WHERE status='sending' AND lease_until<=now() AND attempts>=%s""", (MAX_ATTEMPTS,))
            cur.execute(f"""WITH due AS (
                SELECT d.id FROM ih_monitor_email_deliveries d JOIN ih_monitors m ON m.id=d.monitor_id
                JOIN ih_monitor_email_preferences p ON p.monitor_id=m.id JOIN ih_users u ON u.id=d.user_id
                WHERE {ACTIVE} AND d.attempts<%s AND (%s::text IS NULL OR d.id=%s) AND (
                    (d.status IN ('pending','retry') AND d.next_attempt_at<=now()) OR
                    (d.status='sending' AND d.lease_until<=now()))
                ORDER BY d.next_attempt_at,d.id FOR UPDATE OF d SKIP LOCKED LIMIT %s)
                UPDATE ih_monitor_email_deliveries d SET status='sending',attempts=d.attempts+1,
                    send_started_at=NULL,lease_token=%s,lease_until=now()+interval '90 seconds',updated_at=now()
                FROM due WHERE d.id=due.id RETURNING d.*""", (MAX_ATTEMPTS, event_id, event_id, min(max(1, limit), 3), uuid.uuid4().hex))
            return [dict(row) for row in cur.fetchall()]

    def begin_attempt(self, event, payload):
        with self.control._connect() as conn, conn.cursor() as cur:
            # Fence after claiming and immediately before the external send.
            cur.execute("SELECT id FROM ih_monitors WHERE id=%s FOR UPDATE", (event["monitor_id"],))
            cur.execute(f"""UPDATE ih_monitor_email_deliveries d SET
                request_payload=COALESCE(d.request_payload,%s::jsonb),send_started_at=clock_timestamp(),
                first_dispatch_at=COALESCE(first_dispatch_at,clock_timestamp())
                FROM ih_monitors m,ih_monitor_email_preferences p,ih_users u
                WHERE d.id=%s AND d.status='sending' AND d.lease_token=%s AND d.lease_until>clock_timestamp()
                  AND m.id=d.monitor_id AND p.monitor_id=m.id AND u.id=d.user_id AND {ACTIVE}
                  AND (first_dispatch_at IS NULL OR first_dispatch_at>clock_timestamp()-interval '{SEND_WINDOW_HOURS} hours')
                RETURNING d.*""", (json.dumps(payload), event["id"], event["lease_token"]))
            row = cur.fetchone()
            return dict(row) if row else None

    def finish(self, event, *, message_id=None, error=None, permanent=False, uncertain=False):
        status = "accepted" if message_id else "unknown" if (uncertain or event["may_have_sent"]) and (permanent or event["attempts"] >= MAX_ATTEMPTS) else "failed" if permanent or event["attempts"] >= MAX_ATTEMPTS else "retry"
        delay = min(3600, 60 * 5 ** (event["attempts"] - 1))
        with self.control._connect() as conn, conn.cursor() as cur:
            cur.execute("""UPDATE ih_monitor_email_deliveries SET status=%s,provider_id=%s,last_error=%s,
                may_have_sent=(may_have_sent OR %s),next_attempt_at=now()+(%s * interval '1 second'),
                accepted_at=CASE WHEN %s IS NOT NULL THEN now() ELSE accepted_at END,
                next_receipt_at=CASE WHEN %s IS NOT NULL THEN now() ELSE NULL END,
                lease_token=NULL,lease_until=NULL,updated_at=now()
                WHERE id=%s AND status='sending' AND lease_token=%s""",
                (status, message_id, error, uncertain, delay, message_id, message_id, event["id"], event["lease_token"]))

    def claim_receipts(self, limit=3, event_id=None):
        with self.control._connect() as conn, conn.cursor() as cur:
            cur.execute("""UPDATE ih_monitor_email_deliveries SET
                receipt_error='Delivery confirmation timed out. The email was accepted, but delivery remains unconfirmed.'
                WHERE status='accepted' AND (receipt_attempts>=24 OR accepted_at<=now()-interval '7 days')
                  AND (receipt_lease_until IS NULL OR receipt_lease_until<=now())""")
            cur.execute("""WITH due AS (SELECT id FROM ih_monitor_email_deliveries
                WHERE status='accepted' AND provider_id IS NOT NULL AND receipt_attempts<24
                  AND accepted_at>now()-interval '7 days' AND next_receipt_at<=now()
                  AND (receipt_lease_until IS NULL OR receipt_lease_until<=now()) AND (%s::text IS NULL OR id=%s)
                ORDER BY next_receipt_at,id FOR UPDATE SKIP LOCKED LIMIT %s)
                UPDATE ih_monitor_email_deliveries d SET receipt_attempts=d.receipt_attempts+1,
                    receipt_lease_token=%s,receipt_lease_until=now()+interval '60 seconds'
                FROM due WHERE d.id=due.id RETURNING d.*""", (event_id, event_id, min(max(1, limit), 3), uuid.uuid4().hex))
            return [dict(row) for row in cur.fetchall()]

    def finish_receipt(self, event, *, provider_event=None, error=None):
        terminal = {"delivered": "delivered", "opened": "delivered", "clicked": "delivered", "bounced": "bounced",
                    "complained": "complained", "failed": "failed", "suppressed": "failed", "canceled": "failed"}
        status = terminal.get(provider_event, "accepted")
        delay = min(3600, 60 * 2 ** min(event["receipt_attempts"], 6))
        with self.control._connect() as conn, conn.cursor() as cur:
            cur.execute("""UPDATE ih_monitor_email_deliveries SET status=%s,provider_event=COALESCE(%s,provider_event),
                receipt_error=%s,last_receipt_at=now(),next_receipt_at=now()+(%s * interval '1 second'),
                delivered_at=CASE WHEN %s='delivered' THEN now() ELSE delivered_at END,
                receipt_lease_token=NULL,receipt_lease_until=NULL,updated_at=now()
                WHERE id=%s AND status='accepted' AND receipt_lease_token=%s""",
                (status, provider_event, error, delay, status, event["id"], event["receipt_lease_token"]))
