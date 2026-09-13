from __future__ import annotations

import json
from typing import Any

from .models import ExtractedDocument, FetchResult, SearchHit
from .object_store import ObjectStore


class PostgresCaptureStore:
    """Shared capture/document metadata store backed by PostgreSQL."""

    def __init__(self, dsn: str, *, object_store: ObjectStore | None = None) -> None:
        if not dsn.strip():
            raise ValueError("Postgres DSN cannot be empty")
        try:
            import psycopg
        except ImportError as exc:  # pragma: no cover - optional dependency
            raise RuntimeError("Install internet-hands[postgres] for Postgres capture storage") from exc
        self._psycopg = psycopg
        self.dsn = dsn
        self.object_store = object_store
        self._init_schema()

    def _connect(self):
        return self._psycopg.connect(self.dsn)

    def _init_schema(self) -> None:
        with self._connect() as conn, conn.cursor() as cur:
            cur.execute(
                """
                CREATE TABLE IF NOT EXISTS captures (
                    id BIGSERIAL PRIMARY KEY,
                    request_url TEXT NOT NULL,
                    final_url TEXT NOT NULL,
                    status_code INTEGER NOT NULL,
                    content_type TEXT,
                    content_length BIGINT NOT NULL,
                    sha256 TEXT NOT NULL,
                    elapsed_ms DOUBLE PRECISION NOT NULL,
                    captured_at TIMESTAMPTZ NOT NULL,
                    headers JSONB NOT NULL,
                    content_location TEXT,
                    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
                )
                """
            )
            cur.execute("CREATE INDEX IF NOT EXISTS captures_url_idx ON captures(final_url)")
            cur.execute("CREATE INDEX IF NOT EXISTS captures_sha_idx ON captures(sha256)")
            cur.execute(
                """
                CREATE TABLE IF NOT EXISTS documents (
                    id BIGSERIAL PRIMARY KEY,
                    capture_id BIGINT NOT NULL UNIQUE REFERENCES captures(id) ON DELETE CASCADE,
                    url TEXT NOT NULL,
                    title TEXT,
                    description TEXT,
                    text TEXT NOT NULL,
                    headings JSONB NOT NULL,
                    links JSONB NOT NULL,
                    sha256 TEXT NOT NULL,
                    created_at TIMESTAMPTZ NOT NULL,
                    search_vector TSVECTOR GENERATED ALWAYS AS (
                        setweight(to_tsvector('simple', COALESCE(title, '')), 'A') ||
                        setweight(to_tsvector('simple', COALESCE(description, '')), 'B') ||
                        setweight(to_tsvector('simple', COALESCE(text, '')), 'C')
                    ) STORED
                )
                """
            )
            cur.execute("CREATE INDEX IF NOT EXISTS documents_url_idx ON documents(url)")
            cur.execute(
                "CREATE INDEX IF NOT EXISTS documents_search_idx ON documents USING GIN(search_vector)"
            )
            conn.commit()

    def save_fetch(self, result: FetchResult, document: ExtractedDocument | None = None) -> int:
        if self.object_store is None:
            raise RuntimeError(
                "Distributed capture writes require an object store; configure S3/MinIO for workers"
            )
        content_location = self.object_store.put_capture(result)
        with self._connect() as conn, conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO captures (
                    request_url, final_url, status_code, content_type, content_length,
                    sha256, elapsed_ms, captured_at, headers, content_location
                ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s::jsonb, %s)
                RETURNING id
                """,
                (
                    result.request_url,
                    result.final_url,
                    result.status_code,
                    result.content_type,
                    result.content_length,
                    result.sha256,
                    result.elapsed_ms,
                    result.captured_at,
                    json.dumps(result.headers, sort_keys=True),
                    content_location,
                ),
            )
            capture_id = int(cur.fetchone()[0])
            if document is not None:
                cur.execute(
                    """
                    INSERT INTO documents (
                        capture_id, url, title, description, text, headings,
                        links, sha256, created_at
                    ) VALUES (%s, %s, %s, %s, %s, %s::jsonb, %s::jsonb, %s, %s)
                    """,
                    (
                        capture_id,
                        document.url,
                        document.title,
                        document.description,
                        document.text,
                        json.dumps(document.headings),
                        json.dumps(document.links),
                        document.sha256,
                        document.captured_at,
                    ),
                )
            conn.commit()
        return capture_id

    def search(self, query: str, limit: int = 20) -> list[SearchHit]:
        if not query.strip():
            return []
        if not 1 <= limit <= 200:
            raise ValueError("limit must be between 1 and 200")
        with self._connect() as conn, conn.cursor() as cur:
            cur.execute(
                """
                WITH q AS (SELECT websearch_to_tsquery('simple', %s) AS query)
                SELECT d.id, d.url, d.title, d.description, d.created_at, d.sha256,
                       ts_headline(
                           'simple', d.text, q.query,
                           'StartSel=[, StopSel=], MaxWords=24, MinWords=8'
                       ) AS snippet,
                       ts_rank_cd(d.search_vector, q.query) AS score
                FROM documents d, q
                WHERE d.search_vector @@ q.query
                ORDER BY score DESC, d.id DESC
                LIMIT %s
                """,
                (query, limit),
            )
            rows = cur.fetchall()
        return [
            SearchHit(
                document_id=int(row[0]),
                url=str(row[1]),
                title=row[2],
                description=row[3],
                captured_at=row[4],
                sha256=str(row[5]),
                snippet=str(row[6] or ""),
                score=float(row[7]),
            )
            for row in rows
        ]

    def stats(self) -> dict[str, int]:
        with self._connect() as conn, conn.cursor() as cur:
            cur.execute("SELECT COUNT(*) FROM captures")
            captures = int(cur.fetchone()[0])
            cur.execute("SELECT COUNT(*) FROM documents")
            documents = int(cur.fetchone()[0])
            cur.execute("SELECT COUNT(DISTINCT final_url) FROM captures")
            urls = int(cur.fetchone()[0])
        return {"captures": captures, "documents": documents, "urls": urls}

    def recent_captures(self, *, limit: int = 100) -> list[dict[str, Any]]:
        if not 1 <= limit <= 1000:
            raise ValueError("limit must be between 1 and 1000")
        with self._connect() as conn, conn.cursor() as cur:
            cur.execute(
                """
                SELECT id, final_url, status_code, content_type, content_length,
                       sha256, elapsed_ms, captured_at, content_location
                FROM captures
                ORDER BY id DESC
                LIMIT %s
                """,
                (limit,),
            )
            rows = cur.fetchall()
        return [
            {
                "id": int(row[0]),
                "url": row[1],
                "status_code": row[2],
                "content_type": row[3],
                "content_length": int(row[4]),
                "sha256": row[5],
                "elapsed_ms": float(row[6]),
                "captured_at": row[7].isoformat(),
                "content_location": row[8],
            }
            for row in rows
        ]