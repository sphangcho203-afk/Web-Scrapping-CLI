from __future__ import annotations

import os
import re
import time
from typing import Any
from urllib.parse import quote

import httpx

from .execution_meter import record_usage
from .policy import validate_public_http_url
from .tool_mesh import ToolDescriptor


def _schema(properties: dict[str, Any], required: list[str] | None = None) -> dict[str, Any]:
    result: dict[str, Any] = {
        "type": "object",
        "properties": properties,
        "additionalProperties": False,
    }
    if required:
        result["required"] = required
    return result


def _str(description: str = "", *, max_length: int | None = None) -> dict[str, Any]:
    result: dict[str, Any] = {"type": "string"}
    if description:
        result["description"] = description
    if max_length is not None:
        result["maxLength"] = max_length
    return result


def _rank_tools(
    tools: dict[str, ToolDescriptor],
    query: str,
    *,
    limit: int,
) -> list[ToolDescriptor]:
    words = [word for word in re.split(r"\W+", query.casefold()) if word]
    rows: list[tuple[int, ToolDescriptor]] = []
    for descriptor in tools.values():
        haystack = " ".join(
            [descriptor.tool_id, descriptor.name, descriptor.description, *descriptor.tags]
        ).casefold()
        score = sum(
            4 if word in descriptor.name.casefold() else 1
            for word in words
            if word in haystack
        )
        if score or not words:
            rows.append((score, descriptor))
    rows.sort(key=lambda row: (-row[0], row[1].tool_id))
    return [descriptor for _, descriptor in rows[: max(1, min(int(limit), 50))]]


class RawgGamingCatalogProvider:
    """RAWG documented game metadata/search API."""

    name = "rawg"
    base_url = "https://api.rawg.io/api"

    def __init__(
        self,
        api_key: str | None = None,
        *,
        client: httpx.AsyncClient | None = None,
    ) -> None:
        self.api_key = api_key if api_key is not None else os.getenv("RAWG_API_KEY", "").strip()
        self.client = client
        self._tools = self._build_tools()

    @staticmethod
    def _build_tools() -> dict[str, ToolDescriptor]:
        return {
            "search-games": ToolDescriptor(
                ref="rawg:search-games",
                provider="rawg",
                tool_id="search-games",
                name="RAWG game search",
                description="Search RAWG's documented video-game catalog and metadata index.",
                input_schema=_schema(
                    {
                        "query": _str("Game title or search text", max_length=200),
                        "limit": {"type": "integer", "minimum": 1, "maximum": 40},
                        "page": {"type": "integer", "minimum": 1, "maximum": 1000},
                        "platforms": _str(max_length=120),
                        "dates": _str("YYYY-MM-DD,YYYY-MM-DD", max_length=32),
                        "metacritic": _str("Score range such as 80,100", max_length=16),
                        "ordering": _str(max_length=40),
                        "search_precise": {"type": "boolean"},
                        "search_exact": {"type": "boolean"},
                    },
                    ["query"],
                ),
                tags=["gaming", "games", "catalog", "search", "rawg", "metadata"],
                requires_auth=True,
                side_effecting=False,
                metadata={"endpoint": "/games", "official": True},
            ),
            "game-detail": ToolDescriptor(
                ref="rawg:game-detail",
                provider="rawg",
                tool_id="game-detail",
                name="RAWG game detail",
                description="Retrieve rich metadata for a RAWG game id or slug.",
                input_schema=_schema(
                    {"id_or_slug": _str("RAWG numeric id or slug", max_length=160)},
                    ["id_or_slug"],
                ),
                tags=["gaming", "games", "detail", "rawg", "metadata"],
                requires_auth=True,
                side_effecting=False,
                metadata={"endpoint": "/games/{id_or_slug}", "official": True},
            ),
            "platforms-search": ToolDescriptor(
                ref="rawg:platforms-search",
                provider="rawg",
                tool_id="platforms-search",
                name="RAWG platform catalog",
                description="Search and browse RAWG gaming platforms.",
                input_schema=_schema(
                    {
                        "query": _str(max_length=120),
                        "limit": {"type": "integer", "minimum": 1, "maximum": 40},
                        "page": {"type": "integer", "minimum": 1, "maximum": 1000},
                    }
                ),
                tags=["gaming", "platforms", "catalog", "rawg"],
                requires_auth=True,
                side_effecting=False,
                metadata={"endpoint": "/platforms", "official": True},
            ),
            "developers-search": ToolDescriptor(
                ref="rawg:developers-search",
                provider="rawg",
                tool_id="developers-search",
                name="RAWG developer catalog",
                description="Search game developers in RAWG's documented catalog.",
                input_schema=_schema(
                    {
                        "query": _str(max_length=160),
                        "limit": {"type": "integer", "minimum": 1, "maximum": 40},
                        "page": {"type": "integer", "minimum": 1, "maximum": 1000},
                    }
                ),
                tags=["gaming", "developers", "studios", "catalog", "rawg"],
                requires_auth=True,
                side_effecting=False,
                metadata={"endpoint": "/developers", "official": True},
            ),
            "publishers-search": ToolDescriptor(
                ref="rawg:publishers-search",
                provider="rawg",
                tool_id="publishers-search",
                name="RAWG publisher catalog",
                description="Search game publishers in RAWG's documented catalog.",
                input_schema=_schema(
                    {
                        "query": _str(max_length=160),
                        "limit": {"type": "integer", "minimum": 1, "maximum": 40},
                        "page": {"type": "integer", "minimum": 1, "maximum": 1000},
                    }
                ),
                tags=["gaming", "publishers", "catalog", "rawg"],
                requires_auth=True,
                side_effecting=False,
                metadata={"endpoint": "/publishers", "official": True},
            ),
        }

    async def status(self) -> dict[str, Any]:
        return {
            "configured": bool(self.api_key),
            "searchable": True,
            "executable": bool(self.api_key),
            "kind": "documented-game-catalog-api",
            "tool_count": len(self._tools),
            "tools": sorted(self._tools),
        }

    async def search(self, query: str, *, limit: int = 10) -> list[ToolDescriptor]:
        return _rank_tools(self._tools, query, limit=limit)

    async def describe(self, tool_id: str) -> ToolDescriptor:
        try:
            return self._tools[tool_id]
        except KeyError as exc:
            raise ValueError(f"unknown RAWG tool: {tool_id}") from exc

    async def _get(
        self,
        path: str,
        params: dict[str, Any],
        *,
        timeout_seconds: int,
    ) -> Any:
        if not self.api_key:
            raise RuntimeError("RAWG_API_KEY is not configured")
        url = f"{self.base_url}{path}"
        validate_public_http_url(url)
        query_params = {**params, "key": self.api_key}
        timeout = max(1.0, min(float(timeout_seconds), 60.0))
        if self.client is not None:
            response = await self.client.get(url, params=query_params, timeout=timeout)
            response.raise_for_status()
        else:
            async with httpx.AsyncClient(follow_redirects=False, timeout=timeout) as client:
                response = await client.get(url, params=query_params)
                response.raise_for_status()
        return response.json()

    async def execute(
        self,
        tool_id: str,
        arguments: dict[str, Any],
        *,
        account: str | None = None,
        wait_seconds: int = 30,
        timeout_seconds: int = 60,
        options: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        del account, wait_seconds, options
        await self.describe(tool_id)
        params: dict[str, Any] = {}

        if tool_id == "search-games":
            query = str(arguments.get("query") or "").strip()
            if not query:
                raise ValueError("query is required")
            path = "/games"
            params = {
                "search": query[:200],
                "page_size": max(1, min(int(arguments.get("limit", 20)), 40)),
                "page": max(1, min(int(arguments.get("page", 1)), 1000)),
            }
            for key in ("platforms", "dates", "metacritic", "ordering"):
                value = arguments.get(key)
                if value is not None:
                    params[key] = str(value)
            if arguments.get("search_precise") is not None:
                params["search_precise"] = bool(arguments["search_precise"])
            if arguments.get("search_exact") is not None:
                params["search_exact"] = bool(arguments["search_exact"])

        elif tool_id == "game-detail":
            raw = str(arguments.get("id_or_slug") or "").strip()
            if not raw or not re.fullmatch(r"[A-Za-z0-9._-]{1,160}", raw):
                raise ValueError("id_or_slug contains unsupported characters")
            path = f"/games/{quote(raw, safe='')}"
        elif tool_id in {"platforms-search", "developers-search", "publishers-search"}:
            path = {
                "platforms-search": "/platforms",
                "developers-search": "/developers",
                "publishers-search": "/publishers",
            }[tool_id]
            params = {
                "page_size": max(1, min(int(arguments.get("limit", 20)), 40)),
                "page": max(1, min(int(arguments.get("page", 1)), 1000)),
            }
            query = str(arguments.get("query") or "").strip()
            if query:
                params["search"] = query[:160]
        else:
            raise ValueError(f"unknown RAWG tool: {tool_id}")

        data = await self._get(path, params, timeout_seconds=timeout_seconds)
        record_usage("rawg_calls", 1)
        return {
            "status": "completed",
            "data": data,
            "metadata": {"provider": self.name, "official": True},
        }

    async def job_status(self, job_id: str, *, wait_seconds: int = 0) -> dict[str, Any]:
        del job_id, wait_seconds
        raise ValueError("RAWG tools complete inline")

    async def result_page(
        self,
        result_id: str,
        *,
        offset: int = 0,
        limit: int = 100,
    ) -> dict[str, Any]:
        del result_id, offset, limit
        raise ValueError("RAWG tools return bounded inline results")


class IgdbGamingCatalogProvider:
    """IGDB v4 provider using Twitch client credentials without caller-controlled scopes."""

    name = "igdb"
    base_url = "https://api.igdb.com/v4"
    token_url = "https://id.twitch.tv/oauth2/token"

    def __init__(
        self,
        client_id: str | None = None,
        client_secret: str | None = None,
        access_token: str | None = None,
        *,
        client: httpx.AsyncClient | None = None,
    ) -> None:
        self.client_id = (
            client_id if client_id is not None else os.getenv("IGDB_CLIENT_ID", "").strip()
        )
        self.client_secret = (
            client_secret
            if client_secret is not None
            else os.getenv("IGDB_CLIENT_SECRET", "").strip()
        )
        self.access_token = (
            access_token
            if access_token is not None
            else os.getenv("IGDB_ACCESS_TOKEN", "").strip()
        )
        self.client = client
        self._cached_token: str | None = self.access_token or None
        self._token_expires_at = float("inf") if self.access_token else 0.0
        self._tools = self._build_tools()

    @staticmethod
    def _build_tools() -> dict[str, ToolDescriptor]:
        return {
            "search-games": ToolDescriptor(
                ref="igdb:search-games",
                provider="igdb",
                tool_id="search-games",
                name="IGDB game search",
                description="Search Twitch/IGDB's documented game database with a fixed safe field set.",
                input_schema=_schema(
                    {
                        "query": _str("Game title", max_length=200),
                        "limit": {"type": "integer", "minimum": 1, "maximum": 50},
                    },
                    ["query"],
                ),
                tags=["gaming", "games", "catalog", "search", "igdb", "twitch"],
                requires_auth=True,
                side_effecting=False,
                metadata={"endpoint": "/games", "official": True},
            ),
            "game-by-id": ToolDescriptor(
                ref="igdb:game-by-id",
                provider="igdb",
                tool_id="game-by-id",
                name="IGDB game detail",
                description="Retrieve a fixed rich metadata projection for one IGDB game id.",
                input_schema=_schema(
                    {"game_id": {"type": "integer", "minimum": 1}},
                    ["game_id"],
                ),
                tags=["gaming", "games", "detail", "igdb", "twitch"],
                requires_auth=True,
                side_effecting=False,
                metadata={"endpoint": "/games", "official": True},
            ),
            "search-platforms": ToolDescriptor(
                ref="igdb:search-platforms",
                provider="igdb",
                tool_id="search-platforms",
                name="IGDB platform search",
                description="Search IGDB's documented platform catalog.",
                input_schema=_schema(
                    {
                        "query": _str("Platform name", max_length=160),
                        "limit": {"type": "integer", "minimum": 1, "maximum": 50},
                    },
                    ["query"],
                ),
                tags=["gaming", "platforms", "catalog", "search", "igdb"],
                requires_auth=True,
                side_effecting=False,
                metadata={"endpoint": "/platforms", "official": True},
            ),
        }

    async def status(self) -> dict[str, Any]:
        configured = bool(self.client_id and (self.access_token or self.client_secret))
        return {
            "configured": configured,
            "searchable": True,
            "executable": configured,
            "kind": "documented-game-catalog-api",
            "auth": "twitch-client-credentials",
            "tool_count": len(self._tools),
            "tools": sorted(self._tools),
        }

    async def search(self, query: str, *, limit: int = 10) -> list[ToolDescriptor]:
        return _rank_tools(self._tools, query, limit=limit)

    async def describe(self, tool_id: str) -> ToolDescriptor:
        try:
            return self._tools[tool_id]
        except KeyError as exc:
            raise ValueError(f"unknown IGDB tool: {tool_id}") from exc

    async def _token(self, *, timeout_seconds: int) -> str:
        if self._cached_token and time.monotonic() < self._token_expires_at - 60:
            return self._cached_token
        if not self.client_id or not self.client_secret:
            raise RuntimeError(
                "IGDB requires IGDB_CLIENT_ID plus IGDB_ACCESS_TOKEN or IGDB_CLIENT_SECRET"
            )
        validate_public_http_url(self.token_url)
        params = {
            "client_id": self.client_id,
            "client_secret": self.client_secret,
            "grant_type": "client_credentials",
        }
        timeout = max(1.0, min(float(timeout_seconds), 30.0))
        if self.client is not None:
            response = await self.client.post(self.token_url, params=params, timeout=timeout)
            response.raise_for_status()
        else:
            async with httpx.AsyncClient(follow_redirects=False, timeout=timeout) as client:
                response = await client.post(self.token_url, params=params)
                response.raise_for_status()
        data = response.json()
        token = str(data.get("access_token") or "")
        if not token:
            raise RuntimeError("Twitch client-credentials response did not contain an access token")
        expires_in = max(300, int(data.get("expires_in") or 3600))
        self._cached_token = token
        self._token_expires_at = time.monotonic() + expires_in
        return token

    @staticmethod
    def _escaped_search(value: Any, *, maximum: int) -> str:
        text = str(value or "").strip()[:maximum]
        if not text:
            raise ValueError("query is required")
        return text.replace("\\", "\\\\").replace('"', '\\"')

    async def _post(
        self,
        path: str,
        body: str,
        *,
        timeout_seconds: int,
    ) -> Any:
        if not self.client_id:
            raise RuntimeError("IGDB_CLIENT_ID is not configured")
        token = await self._token(timeout_seconds=timeout_seconds)
        url = f"{self.base_url}{path}"
        validate_public_http_url(url)
        headers = {
            "Client-ID": self.client_id,
            "Authorization": f"Bearer {token}",
            "Accept": "application/json",
            "Content-Type": "text/plain",
        }
        timeout = max(1.0, min(float(timeout_seconds), 60.0))
        if self.client is not None:
            response = await self.client.post(url, headers=headers, content=body, timeout=timeout)
            response.raise_for_status()
        else:
            async with httpx.AsyncClient(follow_redirects=False, timeout=timeout) as client:
                response = await client.post(url, headers=headers, content=body)
                response.raise_for_status()
        return response.json()

    async def execute(
        self,
        tool_id: str,
        arguments: dict[str, Any],
        *,
        account: str | None = None,
        wait_seconds: int = 30,
        timeout_seconds: int = 60,
        options: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        del account, wait_seconds, options
        await self.describe(tool_id)
        limit = max(1, min(int(arguments.get("limit", 20)), 50))

        if tool_id == "search-games":
            query = self._escaped_search(arguments.get("query"), maximum=200)
            body = (
                f'search "{query}"; '
                "fields id,name,slug,summary,first_release_date,"
                "platforms.name,genres.name,involved_companies.company.name,"
                "rating,total_rating,url; "
                "where version_parent = null; "
                f"limit {limit};"
            )
            path = "/games"
        elif tool_id == "game-by-id":
            game_id = int(arguments.get("game_id") or 0)
            if game_id <= 0:
                raise ValueError("game_id must be a positive integer")
            body = (
                "fields id,name,slug,summary,storyline,first_release_date,"
                "platforms.name,genres.name,involved_companies.company.name,"
                "involved_companies.developer,involved_companies.publisher,"
                "rating,total_rating,aggregated_rating,websites.url,url; "
                f"where id = {game_id}; limit 1;"
            )
            path = "/games"
        elif tool_id == "search-platforms":
            query = self._escaped_search(arguments.get("query"), maximum=160)
            body = (
                f'search "{query}"; '
                "fields id,name,abbreviation,alternative_name,slug,summary,url; "
                f"limit {limit};"
            )
            path = "/platforms"
        else:
            raise ValueError(f"unknown IGDB tool: {tool_id}")

        data = await self._post(path, body, timeout_seconds=timeout_seconds)
        record_usage("igdb_calls", 1)
        return {
            "status": "completed",
            "data": data,
            "metadata": {
                "provider": self.name,
                "official": True,
                "auth": "twitch-client-credentials",
            },
        }

    async def job_status(self, job_id: str, *, wait_seconds: int = 0) -> dict[str, Any]:
        del job_id, wait_seconds
        raise ValueError("IGDB tools complete inline")

    async def result_page(
        self,
        result_id: str,
        *,
        offset: int = 0,
        limit: int = 100,
    ) -> dict[str, Any]:
        del result_id, offset, limit
        raise ValueError("IGDB tools return bounded inline results")


def build_game_catalog_providers() -> list[
    RawgGamingCatalogProvider | IgdbGamingCatalogProvider
]:
    return [RawgGamingCatalogProvider(), IgdbGamingCatalogProvider()]
