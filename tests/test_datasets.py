from __future__ import annotations

import csv
import io
import json
import os
import uuid
from copy import deepcopy

import pytest
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient

from internet_hands import datasets_api, playground_api
from internet_hands.control_store import AuthIdentity, ControlError, ControlStore
from internet_hands.datasets import DatasetStore, export_rows, result_rows


class MemoryDatasets:
    def __init__(self):
        self.item = {"id": "ds_one", "user_id": "owner", "name": "Search", "request_id": "req_one",
                     "operation": "search", "columns": ["url", "title"], "row_count": 2,
                     "rows": [{"url": "https://example.com", "title": "Alpha"},
                              {"url": "https://example.org", "title": "Beta"}], "output": {}}

    def get(self, user_id, dataset_id):
        if not self.item or user_id != self.item["user_id"] or dataset_id != self.item["id"]:
            raise ControlError("dataset_not_found", "Dataset not found for this account.", 404)
        return deepcopy(self.item)

    def rename(self, user_id, dataset_id, name):
        self.get(user_id, dataset_id)
        self.item["name"] = name
        return deepcopy(self.item)

    def delete(self, user_id, dataset_id):
        self.get(user_id, dataset_id)
        self.item = None


@pytest.fixture
def client(monkeypatch):
    monkeypatch.setattr(datasets_api, "datasets", MemoryDatasets())
    monkeypatch.setattr(datasets_api, "_require_user", lambda request: {"id": "owner"})
    app = FastAPI()
    app.include_router(datasets_api.router)
    return TestClient(app)


def test_detail_filter_pagination_and_private_metadata(client):
    data = client.get("/api/datasets/ds_one?q=BETA&limit=1").json()
    assert data["total"] == 1 and data["rows"][0]["title"] == "Beta"
    assert "user_id" not in data["dataset"] and "output" not in data["dataset"]
    assert client.get("/api/datasets/ds_one?offset=1&limit=1").json()["rows"][0]["title"] == "Beta"


def test_foreign_account_cannot_read_rename_export_or_delete(client, monkeypatch):
    monkeypatch.setattr(datasets_api, "_require_user", lambda request: {"id": "intruder"})
    for method, path, kwargs in [
        ("get", "/api/datasets/ds_one", {}),
        ("get", "/api/datasets/ds_one/export", {}),
        ("patch", "/api/datasets/ds_one", {"json": {"name": "Stolen"}}),
        ("delete", "/api/datasets/ds_one", {}),
    ]:
        response = getattr(client, method)(path, **kwargs)
        assert response.status_code == 404


def test_unauthenticated_and_invalid_key_fail(client, monkeypatch):
    def denied(request):
        raise HTTPException(401)
    monkeypatch.setattr(datasets_api, "_require_user", denied)
    assert client.get("/api/datasets/ds_one").status_code == 401
    monkeypatch.setattr(datasets_api, "authenticate_secret", lambda *_: None)
    assert client.get("/api/datasets/ds_one", headers={"X-API-Key": "bad"}).status_code == 401


def test_read_key_cannot_mutate(client, monkeypatch):
    identity = AuthIdentity("owner", "key", ["mcp:read"], "free", 30, "api_key")
    monkeypatch.setattr(datasets_api, "authenticate_secret", lambda *_: identity)
    headers = {"Authorization": "Bearer valid"}
    assert client.get("/api/datasets/ds_one", headers=headers).status_code == 200
    assert client.delete("/api/datasets/ds_one", headers=headers).status_code == 403
    identity.scopes = ["mcp:execute"]
    assert client.delete("/api/datasets/ds_one", headers=headers).status_code == 200


def test_rename_validation_delete_and_exports(client):
    assert client.patch("/api/datasets/ds_one", json={"name": "  Saved  "}).json()["dataset"]["name"] == "Saved"
    for payload in ([], {"name": ""}, {"name": 42}, {"name": "x" * 121}):
        assert client.patch("/api/datasets/ds_one", json=payload).status_code == 422
    assert client.patch("/api/datasets/ds_one", content="{bad").status_code == 400
    assert client.get("/api/datasets/ds_one/export?format=html").status_code == 422
    response = client.get("/api/datasets/ds_one/export?format=csv")
    assert response.headers["cache-control"] == "no-store"
    assert 'filename="ds_one.csv"' in response.headers["content-disposition"]
    assert next(iter(csv.DictReader(io.StringIO(response.text))))["title"] == "Alpha"
    assert client.delete("/api/datasets/ds_one").json() == {"deleted": True}
    assert client.get("/api/datasets/ds_one").status_code == 404


def test_exports_nested_unicode_empty_and_formula_protection():
    rows = [{"text": ' \t=HYPERLINK("bad")', "nested": ["অসম"], "number": -10},
            {"text": "@attack\nline", "null": None}]
    assert json.loads(export_rows(rows, "json")[0]) == rows
    assert [json.loads(line) for line in export_rows(rows, "jsonl")[0].splitlines()] == rows
    cells = list(csv.DictReader(io.StringIO(export_rows(rows, "csv")[0])))
    assert cells[0]["text"].startswith("'") and cells[1]["text"].startswith("'")
    assert cells[0]["number"] == "-10"
    assert json.loads(cells[0]["nested"]) == ["অসম"]
    assert json.loads(export_rows([], "json")[0]) == []
    assert export_rows([], "jsonl")[0] == ""


def test_source_rows_keep_failures_and_provenance():
    rows = result_rows({"search_results": [{"url": "https://example.com", "title": "Found"}],
                        "pages": [{"url": "https://bad.example", "error": "timeout"}],
                        "evidence": [{"url": "https://example.com", "text": "Evidence"}]})
    assert [row["record_type"] for row in rows] == ["search_results", "pages", "evidence"]
    assert rows[1]["error"] == "timeout"


def test_persistence_failure_is_visible_and_does_not_claim_saved(monkeypatch):
    class Failed:
        def save(self, *args):
            raise ControlError("unavailable", "internal database detail", 503)
    monkeypatch.setattr(playground_api, "DatasetStore", lambda _: Failed())
    result = playground_api._save_output("owner", "req_one", "search", {}, "query")
    assert result["dataset"] is None
    assert result["warnings"][0]["code"] == "dataset_not_saved"
    assert "internal database detail" not in str(result)


def test_oversized_output_rejected_before_database_access():
    store = DatasetStore(None)
    for result in ({"search_results": [{"url": "x"}] * 1001},
                   {"evidence": [{"text": "x" * 2_000_001}]}):
        with pytest.raises(ControlError, match="exceeds"):
            store.save("owner", "request", "search", result, "name")


def test_dataset_postgres_lifecycle():
    """Opt-in against an isolated database; never fall back to production DSNs."""
    dsn = os.getenv("OPENCRAWL_TEST_DATASET_DSN")
    if not dsn:
        pytest.skip("Set OPENCRAWL_TEST_DATASET_DSN to an isolated PostgreSQL database.")
    control = ControlStore(dsn)
    control.ensure_schema()
    suffix = uuid.uuid4().hex
    owner, foreign, request_id = f"owner_{suffix}", f"other_{suffix}", f"req_{suffix}"
    with control._connect() as conn, conn.cursor() as cur:
        cur.execute("INSERT INTO ih_users(id,email) VALUES (%s,%s),(%s,%s)",
                    (owner, f"{owner}@test.invalid", foreign, f"{foreign}@test.invalid"))
        cur.execute("INSERT INTO ih_usage_events(id,user_id,request_id,status) VALUES (%s,%s,%s,'ok')",
                    (f"ev_{suffix}", owner, request_id))
    datasets = DatasetStore(control)
    try:
        saved = datasets.save(owner, request_id, "search", {"search_results": [{"url": "https://example.com"}]}, "Saved")
        assert datasets.save(owner, request_id, "search", {}, "Again")["id"] == saved["id"]
        assert datasets.list(owner, limit=25, offset=0)["total"] == 1
        assert datasets.list(foreign, limit=25, offset=0)["total"] == 0
        assert datasets.get(owner, saved["id"])["rows"][0]["record_type"] == "search_results"
        with pytest.raises(ControlError, match="not found"):
            datasets.get(foreign, saved["id"])
        with pytest.raises(ControlError, match="owned run"):
            datasets.save(foreign, request_id, "search", {}, "Stolen")
        assert datasets.rename(owner, saved["id"], "Renamed")["name"] == "Renamed"
        datasets.delete(owner, saved["id"])
        assert datasets.list(owner, limit=25, offset=0)["total"] == 0
    finally:
        with control._connect() as conn, conn.cursor() as cur:
            cur.execute("DELETE FROM ih_users WHERE id IN (%s,%s)", (owner, foreign))
