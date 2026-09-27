from __future__ import annotations

import re
from typing import Any
from urllib.parse import quote

import httpx

from .policy import validate_public_http_url
from .tool_mesh import ToolDescriptor

_PLATFORMS = ("minecraft", "steam", "xbox", "hytale")


class PlayerDbProvider:
    """Cross-platform public identity resolver backed by PlayerDB."""

    name = "playerdb"

    def __init__(
        self,
        *,
        client: httpx.AsyncClient | None = None,
        validate_urls: bool = True,
    ) -> None:
        self.client = client
        self.validate_urls = validate_urls

    def _descriptors(self) -> dict[str, ToolDescriptor]:
        result: dict[str, ToolDescriptor] = {}
        labels = {
            "minecraft": "Minecraft",
            "steam": "Steam",
            "xbox": "Xbox",
            "hytale": "Hytale",
        }
        for platform in _PLATFORMS:
            label = labels[platform]
            result[platform] = ToolDescriptor(
                ref=f"playerdb:{platform}",
                provider=self.name,
                tool_id=platform,
                name=f"{label} public identity lookup",
                description=(
                    f"Resolve a public {label} player identifier through PlayerDB and return "
                    "normalized username/id/avatar metadata where available."
                ),
                input_schema={
                    "type": "object",
                    "required": ["id"],
                    "properties": {
                        "id": {
                            "type": "string",
                            "description": f"{label} username or supported public identifier",
                        }
                    },
                },
                tags=["gaming", platform, "identity", "player", "ign", "resolve"],
                requires_auth=False,
                side_effecting=False,
                metadata={
                    "source": "PlayerDB",
                    "public_data": True,
                    "upstream": "https://playerdb.co/",
                },
            )
        return result

    async def status(self) -> dict[str, Any]:
        return {
            "configured": True,
            "searchable": True,
            "executable": True,
            "kind": "public-gaming-identity-api",
            "tool_count": len(self._descriptors()),
            "platforms": list(_PLATFORMS),
            "authentication": "none",
        }

    async def search(self, query: str, *, limit: int = 10) -> list[ToolDescriptor]:
        words = [word for word in re.split(r"\W+", query.casefold()) if word]
        ranked: list[tuple[int, ToolDescriptor]] = []
        for descriptor in self._descriptors().values():
            haystack = " ".join(
                [descriptor.tool_id, descriptor.name, descriptor.description, *descriptor.tags]
            ).casefold()
            score = sum(4 if word in descriptor.name.casefold() else 1 for word in words if word in haystack)
            if score or not words:
                ranked.append((score, descriptor))
        ranked.sort(key=lambda row: (-row[0], row[1].tool_id))
        return [item for _, item in ranked[: max(1, min(int(limit), 20))]]

    async def describe(self, tool_id: str) -> ToolDescriptor:
        try:
            return self._descriptors()[tool_id]
        except KeyError as exc:
            raise ValueError(f"unknown PlayerDB platform: {tool_id}") from exc

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
        identifier = str(arguments.get("id") or "").strip()
        if not identifier:
            raise ValueError("id is required")
        if len(identifier) > 160:
            raise ValueError("id is too long")
        url = f"https://playerdb.co/api/player/{tool_id}/{quote(identifier, safe='')}"
        if self.validate_urls:
            validate_public_http_url(url)
        headers = {
            "Accept": "application/json",
            "User-Agent": "OpenCrawl/0.7 (+https://github.com/sphangcho203-afk/Web-Scrapping-CLI)",
        }
        if self.client is not None:
            response = await self.client.get(
                url, headers=headers, timeout=max(1.0, min(float(timeout_seconds), 30.0))
            )
        else:
            async with httpx.AsyncClient(follow_redirects=False) as client:
                response = await client.get(
                    url, headers=headers, timeout=max(1.0, min(float(timeout_seconds), 30.0))
                )
        if response.status_code == 429:
            retry_after = response.headers.get("retry-after")
            raise RuntimeError(
                f"PlayerDB rate limited the request"
                + (f"; retry after {retry_after}s" if retry_after else "")
            )
        response.raise_for_status()
        payload = response.json()
        return {
            "status": "completed",
            "data": payload,
            "metadata": {
                "provider": self.name,
                "platform": tool_id,
                "http_status": response.status_code,
                "public_data": True,
            },
        }

    async def job_status(self, job_id: str, *, wait_seconds: int = 0) -> dict[str, Any]:
        del job_id, wait_seconds
        raise ValueError("PlayerDB calls complete inline")

    async def result_page(
        self,
        result_id: str,
        *,
        offset: int = 0,
        limit: int = 100,
    ) -> dict[str, Any]:
        del result_id, offset, limit
        raise ValueError("PlayerDB calls return bounded inline results")
