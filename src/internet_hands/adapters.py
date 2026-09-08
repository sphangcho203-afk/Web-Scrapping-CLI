from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Any

from .fetcher import fetch_url, inspect_api
from .models import FetchResult


class Adapter(ABC):
    """Extension point for public or explicitly authorized platform collectors."""

    name: str

    @abstractmethod
    def supports(self, url: str) -> bool:
        raise NotImplementedError

    @abstractmethod
    async def collect(self, url: str) -> Any:
        raise NotImplementedError


class HttpAdapter(Adapter):
    name = "http"

    def supports(self, url: str) -> bool:
        return url.startswith(("http://", "https://"))

    async def collect(self, url: str) -> FetchResult:
        return await fetch_url(url, include_body=True)


class JsonApiAdapter(Adapter):
    name = "json-api"

    def supports(self, url: str) -> bool:
        return url.startswith(("http://", "https://"))

    async def collect(self, url: str) -> Any:
        return await inspect_api(url)


@dataclass
class AdapterRegistry:
    adapters: list[Adapter]

    @classmethod
    def default(cls) -> AdapterRegistry:
        return cls(adapters=[JsonApiAdapter(), HttpAdapter()])

    def get(self, name: str) -> Adapter:
        for adapter in self.adapters:
            if adapter.name == name:
                return adapter
        raise KeyError(f"Unknown adapter: {name}")
