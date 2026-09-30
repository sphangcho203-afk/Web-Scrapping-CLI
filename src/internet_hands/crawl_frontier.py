"""Versioned, bounded internal state for resuming the account-owned crawler."""
from __future__ import annotations

import json
from typing import Literal

from pydantic import BaseModel, Field, model_validator

MAX_FRONTIER_URLS = 1000
MAX_FRONTIER_URL_BYTES = 500_000
MAX_URL_BYTES = 4096


class CrawlFrontier(BaseModel):
    version: Literal[1] = 1
    config_hash: str = Field(pattern=r"^[a-f0-9]{64}$")
    pending: list[tuple[str, int]] = Field(max_length=MAX_FRONTIER_URLS)
    completed: list[str] = Field(max_length=500)
    truncated: bool = False

    @model_validator(mode="after")
    def bounded(self):
        urls = self.completed + [url for url, _ in self.pending]
        if len(urls) != len(set(urls)) or len(urls) > MAX_FRONTIER_URLS:
            raise ValueError("Frontier URLs must be unique and bounded.")
        sizes = [len(url.encode()) for url in urls]
        if any(size > MAX_URL_BYTES for size in sizes) or sum(sizes) > MAX_FRONTIER_URL_BYTES:
            raise ValueError("Frontier URL bytes exceed their budget.")
        if any(depth < 0 or depth > 50 for _, depth in self.pending):
            raise ValueError("Frontier depths must be between 0 and 50.")
        return self

    def serialized(self) -> str:
        return json.dumps(self.model_dump(mode="json"), ensure_ascii=False)
