from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field


class FetchResult(BaseModel):
    request_url: str
    final_url: str
    status_code: int
    headers: dict[str, str]
    content_type: str | None = None
    content_length: int
    sha256: str
    elapsed_ms: float
    captured_at: datetime
    body_text: str | None = None
    body_base64: str | None = None


class LinkResult(BaseModel):
    source_url: str
    links: list[str] = Field(default_factory=list)


class HealthResult(BaseModel):
    url: str
    ok: bool
    status_code: int | None = None
    elapsed_ms: float | None = None
    content_type: str | None = None
    error: str | None = None


class MonitorState(BaseModel):
    url: str
    sha256: str
    checked_at: datetime
    status_code: int
    content_length: int


class MonitorResult(BaseModel):
    changed: bool
    previous: MonitorState | None = None
    current: MonitorState


class CrawlPage(BaseModel):
    url: str
    status_code: int | None = None
    sha256: str | None = None
    links_found: int = 0
    error: str | None = None


class CrawlResult(BaseModel):
    seed_url: str
    pages: list[CrawlPage]


class DownloadInfo(BaseModel):
    request_url: str
    final_url: str
    status_code: int
    content_type: str | None = None
    content_length: int | None = None
    filename: str | None = None
    disposition: str | None = None
    headers: dict[str, str]


class ApiEnvelope(BaseModel):
    fetch: FetchResult
    parsed: Any | None = None


class ExtractedDocument(BaseModel):
    url: str
    title: str | None = None
    description: str | None = None
    text: str
    headings: list[str] = Field(default_factory=list)
    links: list[str] = Field(default_factory=list)
    captured_at: datetime
    sha256: str


class IndexResult(BaseModel):
    capture_id: int
    url: str
    title: str | None = None
    sha256: str
    text_length: int
    links_found: int


class SearchHit(BaseModel):
    document_id: int
    url: str
    title: str | None = None
    description: str | None = None
    snippet: str
    score: float
    captured_at: datetime
    sha256: str


class WatchJob(BaseModel):
    id: int
    url: str
    interval_seconds: int
    enabled: bool
    last_checked_at: datetime | None = None
    last_sha256: str | None = None
    next_run_at: datetime


class WatchRun(BaseModel):
    watch_id: int
    url: str
    checked_at: datetime
    changed: bool
    status_code: int | None = None
    sha256: str | None = None
    error: str | None = None


class BrowserResult(BaseModel):
    request_url: str
    final_url: str
    status_code: int | None = None
    title: str | None = None
    html: str
    sha256: str
    captured_at: datetime
