"""Transactional outbox and account-owned webhook settings."""
from __future__ import annotations

import json
import secrets
import uuid
from typing import Any

from .control_store import ControlError, ControlStore
from .dataset_webhooks import MAX_ATTEMPTS, MAX_BATCH, validate_webhook_url
from .totp import encrypt_secret, encryption_configured

PUBLIC_ENDPOINT = "url,enabled,created_at,updated_at"
PUBLIC_DELIVERY = "id,dataset_id,status,attempts,next_attempt_at,http_status,last_error,created_at,updated_at"


def enqueue_dataset_event(cur, user_id: str, dataset: dict[str, Any]) -> None:
    """Called inside the dataset insert transaction; one event per saved dataset."""
    event_id = f"wh_{uuid.uuid4().hex}"
    body = json.dumps({"id": event_id, "type": "dataset.saved", "version": 1,
                       "created_at": dataset["created_at"].isoformat(),
                       "data": {"dataset_id": dataset["id"], "request_id": dataset["request_id"],
                                "operation": dataset["operation"], "row_count": dataset["row_count"],
                                "path": f"/api/datasets/{dataset['id']}"}},
                      ensure_ascii=False, separators=(",", ":"))
    cur.execute("""INSERT INTO ih_dataset_webhook_deliveries(id,user_id,dataset_id,body)
        SELECT %s,user_id,%s,%s FROM ih_dataset_webhook_endpoints
        WHERE user_id=%s AND enabled=true ON CONFLICT(dataset_id) DO NOTHING""",
                (event_id, dataset["id"], body, user_id))


class WebhookStore:
    def __init__(self, control: ControlStore):
        self.control = control

    def endpoint(self, user_id: str) -> dict[str, Any] | None:
        self.control.ensure_schema()
        with self.control._connect() as conn, conn.cursor() as cur:
            cur.execute(f"SELECT {PUBLIC_ENDPOINT} FROM ih_dataset_webhook_endpoints WHERE user_id=%s", (user_id,))
            row = cur.fetchone()
            return dict(row) if row else None

    def configure(self, user_id: str, url: str, enabled: bool, rotate: bool = False) -> dict[str, Any]:
        url = validate_webhook_url(url)
        if not encryption_configured():
            raise ControlError("encryption_unavailable", "Webhook secret encryption is not configured.", 503)
        self.control.ensure_schema()
        with self.control._connect() as conn, conn.cursor() as cur:
            # Serialize configurations for the account, including concurrent first writes.
            cur.execute("SELECT id FROM ih_users WHERE id=%s FOR UPDATE", (user_id,))
            cur.execute("SELECT url,secret_enc FROM ih_dataset_webhook_endpoints WHERE user_id=%s", (user_id,))
            current = cur.fetchone()
            secret = "whsec_" + secrets.token_urlsafe(32) if not current or current["url"] != url or rotate else None
            encrypted = encrypt_secret(secret) if secret else current["secret_enc"]
            cur.execute(f"""INSERT INTO ih_dataset_webhook_endpoints(user_id,url,secret_enc,enabled)
                VALUES (%s,%s,%s,%s) ON CONFLICT(user_id) DO UPDATE
                SET url=excluded.url,secret_enc=excluded.secret_enc,enabled=excluded.enabled,updated_at=now()
                RETURNING {PUBLIC_ENDPOINT}""", (user_id, url, encrypted, enabled))
            result = {"endpoint": dict(cur.fetchone())}
            if secret:
                result["signing_secret"] = secret
            return result

    def delete_endpoint(self, user_id: str) -> None:
        self.control.ensure_schema()
        with self.control._connect() as conn, conn.cursor() as cur:
            cur.execute("DELETE FROM ih_dataset_webhook_endpoints WHERE user_id=%s", (user_id,))

    def history(self, user_id: str, limit: int = 25, offset: int = 0) -> dict[str, Any]:
        self.control.ensure_schema()
        with self.control._connect() as conn, conn.cursor() as cur:
            cur.execute("SELECT count(*) AS total FROM ih_dataset_webhook_deliveries WHERE user_id=%s", (user_id,))
            total = cur.fetchone()["total"]
            cur.execute(f"SELECT {PUBLIC_DELIVERY} FROM ih_dataset_webhook_deliveries WHERE user_id=%s "
                        "ORDER BY created_at DESC,id DESC LIMIT %s OFFSET %s", (user_id, limit, offset))
            return {"deliveries": [dict(row) for row in cur.fetchall()], "total": total,
                    "limit": limit, "offset": offset}

    def retry(self, user_id: str, event_id: str) -> dict[str, Any]:
        self.control.ensure_schema()
        with self.control._connect() as conn, conn.cursor() as cur:
            cur.execute(f"""UPDATE ih_dataset_webhook_deliveries d SET status='pending',attempts=0,
                next_attempt_at=now(),lease_token=NULL,lease_until=NULL,last_error=NULL,updated_at=now()
                FROM ih_dataset_webhook_endpoints e
                WHERE d.id=%s AND d.user_id=%s AND e.user_id=d.user_id AND e.enabled=true
                  AND d.status='failed' AND d.created_at > now()-interval '30 days'
                RETURNING {','.join('d.' + col for col in PUBLIC_DELIVERY.split(','))}""", (event_id, user_id))
            row = cur.fetchone()
            if not row:
                cur.execute("SELECT id FROM ih_dataset_webhook_deliveries WHERE id=%s AND user_id=%s", (event_id, user_id))
                if not cur.fetchone():
                    raise ControlError("delivery_not_found", "Delivery not found for this account.", 404)
                raise ControlError("delivery_not_retryable", "Only failed, unexpired deliveries with an enabled endpoint can be retried.", 409)
            return dict(row)

    def claim(self, limit: int = MAX_BATCH) -> list[dict[str, Any]]:
        self.control.ensure_schema()
        token = uuid.uuid4().hex
        with self.control._connect() as conn, conn.cursor() as cur:
            cur.execute("DELETE FROM ih_dataset_webhook_deliveries WHERE created_at < now()-interval '30 days'")
            cur.execute("""UPDATE ih_dataset_webhook_deliveries SET status='failed',lease_token=NULL,
                lease_until=NULL,last_error='Delivery lease expired after the final attempt.',updated_at=now()
                WHERE status='delivering' AND lease_until<=now() AND attempts>=%s""", (MAX_ATTEMPTS,))
            cur.execute("""WITH due AS (
                SELECT d.id FROM ih_dataset_webhook_deliveries d
                JOIN ih_dataset_webhook_endpoints e ON e.user_id=d.user_id
                WHERE e.enabled=true AND d.attempts<%s AND (
                    (d.status IN ('pending','retry') AND d.next_attempt_at<=now()) OR
                    (d.status='delivering' AND d.lease_until<=now()))
                ORDER BY d.next_attempt_at,d.id FOR UPDATE OF d SKIP LOCKED LIMIT %s
            ) UPDATE ih_dataset_webhook_deliveries d
            SET status='delivering',attempts=d.attempts+1,lease_token=%s,
                lease_until=now()+interval '60 seconds',updated_at=now()
            FROM due,ih_dataset_webhook_endpoints e WHERE d.id=due.id AND e.user_id=d.user_id
            RETURNING d.*,e.url,e.secret_enc""", (MAX_ATTEMPTS, max(1, min(limit, MAX_BATCH)), token))
            return [dict(row) for row in cur.fetchall()]

    def begin_attempt(self, event: dict[str, Any]) -> bool:
        """Persist one send intent while owning a live lease; false forbids sending."""
        with self.control._connect() as conn, conn.cursor() as cur:
            # Use the same delivery -> journal lock order as claim and finish.
            cur.execute("""SELECT id FROM ih_dataset_webhook_deliveries
                WHERE id=%s AND status='delivering' AND lease_token=%s
                FOR UPDATE""", (event['id'], event['lease_token']))
            if not cur.fetchone():
                return False
            cur.execute("""UPDATE ih_webhook_attempt_measurements SET dispatch_intent_at=clock_timestamp()
                WHERE delivery_id=%s AND lease_token=%s AND dispatch_intent_at IS NULL
                  AND outcome_recorded_at IS NULL AND EXISTS (
                    SELECT 1 FROM ih_dataset_webhook_deliveries d
                    WHERE d.id=%s AND d.lease_until>clock_timestamp())""",
                        (event['id'], event['lease_token'], event['id']))
            return cur.rowcount == 1

    def finish(self, event: dict[str, Any], *, http_status: int | None, error: str | None,
               permanent: bool = False) -> None:
        delivered = http_status is not None and 200 <= http_status < 300
        status = "delivered" if delivered else "failed" if permanent or event["attempts"] >= MAX_ATTEMPTS else "retry"
        delay = min(3600, 60 * 5 ** (event["attempts"] - 1))
        with self.control._connect() as conn, conn.cursor() as cur:
            cur.execute("""UPDATE ih_dataset_webhook_deliveries SET status=%s,http_status=%s,last_error=%s,
                next_attempt_at=now()+(%s * interval '1 second'),lease_token=NULL,lease_until=NULL,updated_at=now()
                WHERE id=%s AND status='delivering' AND lease_token=%s""",
                        (status, http_status, None if delivered else error, delay, event["id"], event["lease_token"]))
            # An expired worker may report its own real outcome, but cannot change
            # the active outbox lease. First recorded evidence is retained.
            cur.execute("""UPDATE ih_webhook_attempt_measurements
                SET outcome_recorded_at=clock_timestamp(),http_status=%s,outcome=%s
                WHERE delivery_id=%s AND lease_token=%s AND outcome_recorded_at IS NULL""",
                        (http_status, status, event['id'], event['lease_token']))
