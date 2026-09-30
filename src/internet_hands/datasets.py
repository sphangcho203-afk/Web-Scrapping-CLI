"""Durable, account-owned outputs of metered Playground runs."""
from __future__ import annotations

import csv
import io
import json
import uuid
from contextlib import nullcontext
from typing import Any

from .control_store import ControlError, ControlStore
from .dataset_webhook_store import enqueue_dataset_event

MAX_DATASET_BYTES = 2_000_000
MAX_DATASET_ROWS = 1000
METADATA_COLUMNS = "id,request_id,name,operation,row_count,columns,created_at,updated_at"


def result_rows(result: dict[str, Any]) -> list[dict[str, Any]]:
    """Preserve each source record, including failures, with its collection type."""
    rows = []
    for collection in ("search_results", "pages", "evidence", "records"):
        for item in result.get(collection) or []:
            if isinstance(item, dict):
                rows.append({**item, "record_type": collection})
    return rows


def export_rows(rows: list[dict[str, Any]], format: str) -> tuple[str, str]:
    if format == "json":
        return json.dumps(rows, ensure_ascii=False, indent=2), "application/json"
    if format == "jsonl":
        return "".join(json.dumps(row, ensure_ascii=False) + "\n" for row in rows), "application/x-ndjson"
    if format != "csv":
        raise ValueError("Export format must be json, jsonl, or csv.")
    columns = sorted({key for row in rows for key in row})
    stream = io.StringIO(newline="")
    writer = csv.DictWriter(stream, fieldnames=columns)
    writer.writeheader()
    for row in rows:
        cells = {}
        for key, value in row.items():
            if isinstance(value, (dict, list)):
                value = json.dumps(value, ensure_ascii=False)
            # Quoting alone does not prevent spreadsheet formula execution.
            if isinstance(value, str) and value.lstrip().startswith(("=", "+", "-", "@")):
                value = "'" + value
            cells[key] = value
        writer.writerow(cells)
    return stream.getvalue(), "text/csv; charset=utf-8"


class DatasetStore:
    def __init__(self, control: ControlStore):
        self.control = control

    def save(self, user_id: str, request_id: str, operation: str,
             result: dict[str, Any], name: str, *, transaction=None) -> dict[str, Any]:
        rows = result_rows(result)
        payload = json.dumps(result, ensure_ascii=False, default=str)
        if len(rows) > MAX_DATASET_ROWS or len(payload.encode()) > MAX_DATASET_BYTES:
            raise ControlError("dataset_too_large", "Output exceeds the saved dataset limit (2 MB / 1000 rows).", 413)
        columns = sorted({key for row in rows for key in row})
        self.control.ensure_schema()
        with (self.control._connect() if transaction is None else nullcontext(transaction)) as conn, conn.cursor() as cur:
            # Bind the owner to the existing reservation, never a client-supplied user ID.
            cur.execute(
                """INSERT INTO ih_datasets(id,user_id,request_id,name,operation,row_count,columns,rows,output)
                SELECT %s,user_id,request_id,%s,%s,%s,%s::jsonb,%s::jsonb,%s::jsonb
                FROM ih_usage_events WHERE request_id=%s AND user_id=%s
                ON CONFLICT(request_id) DO NOTHING""",
                (f"ds_{uuid.uuid4().hex}", name[:120] or operation, operation, len(rows),
                 json.dumps(columns), json.dumps(rows, default=str), payload, request_id, user_id),
            )
            inserted = cur.rowcount > 0
            cur.execute(f"SELECT {METADATA_COLUMNS} FROM ih_datasets WHERE request_id=%s AND user_id=%s",
                        (request_id, user_id))
            row = cur.fetchone()
            if not row:
                raise ControlError("dataset_run_not_found", "No owned run exists for this output.", 404)
            metadata = dict(row)
            if inserted:
                enqueue_dataset_event(cur, user_id, metadata)
            return metadata

    def list(self, user_id: str, *, limit: int, offset: int) -> dict[str, Any]:
        self.control.ensure_schema()
        with self.control._connect() as conn, conn.cursor() as cur:
            cur.execute("SELECT count(*) AS total FROM ih_datasets WHERE user_id=%s", (user_id,))
            total = cur.fetchone()["total"]
            cur.execute(f"SELECT {METADATA_COLUMNS} FROM ih_datasets WHERE user_id=%s "
                        "ORDER BY created_at DESC,id DESC LIMIT %s OFFSET %s", (user_id, limit, offset))
            return {"datasets": [dict(row) for row in cur.fetchall()], "total": total,
                    "limit": limit, "offset": offset}

    def get(self, user_id: str, dataset_id: str) -> dict[str, Any]:
        self.control.ensure_schema()
        with self.control._connect() as conn, conn.cursor() as cur:
            cur.execute("SELECT * FROM ih_datasets WHERE id=%s AND user_id=%s", (dataset_id, user_id))
            row = cur.fetchone()
            if not row:
                raise ControlError("dataset_not_found", "Dataset not found for this account.", 404)
            return dict(row)

    def rename(self, user_id: str, dataset_id: str, name: str) -> dict[str, Any]:
        self.control.ensure_schema()
        with self.control._connect() as conn, conn.cursor() as cur:
            cur.execute(f"UPDATE ih_datasets SET name=%s,updated_at=now() WHERE id=%s AND user_id=%s "
                        f"RETURNING {METADATA_COLUMNS}", (name, dataset_id, user_id))
            row = cur.fetchone()
            if not row:
                raise ControlError("dataset_not_found", "Dataset not found for this account.", 404)
            return dict(row)

    def delete(self, user_id: str, dataset_id: str) -> None:
        self.control.ensure_schema()
        with self.control._connect() as conn, conn.cursor() as cur:
            cur.execute("DELETE FROM ih_datasets WHERE id=%s AND user_id=%s RETURNING id", (dataset_id, user_id))
            if not cur.fetchone():
                raise ControlError("dataset_not_found", "Dataset not found for this account.", 404)
