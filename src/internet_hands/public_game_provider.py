"""Bounded, keyless public game reads with provenance and short-lived caching."""
from __future__ import annotations

import asyncio
import copy
import json
import time
from collections import OrderedDict
from typing import Any
from urllib.parse import urlencode

from .capability_packs import Capability, CapabilityCandidate
from .execution_meter import record_usage
from .fetcher import fetch_url
from .public_game_manifest import PUBLIC_GAMES, game_pack
from .tool_mesh import ToolDescriptor

OPERATIONS = {
    "news": ("News & updates", "Read recent published news and update excerpts.", "ISteamNews/GetNewsForApp/v2/"),
    "activity": ("Current player activity", "Read the current online player count on Steam, not all platforms.", "ISteamUserStats/GetNumberOfCurrentPlayers/v1/"),
    "achievements": ("Global achievement percentages", "Read global unlock percentages where the game publishes achievements.", "ISteamUserStats/GetGlobalAchievementPercentagesForApp/v2/"),
}


def descriptor(app_id: int, operation: str) -> ToolDescriptor:
    label, description, _ = OPERATIONS[operation]
    tool_id = f"{app_id}/{operation}"
    properties = {"count": {"type": "integer", "minimum": 1, "maximum": 20, "default": 5}} if operation == "news" else {}
    return ToolDescriptor(
        ref=f"gamepublic:{tool_id}", provider="gamepublic", tool_id=tool_id,
        name=f"{PUBLIC_GAMES[app_id]} · {label}", description=description,
        input_schema={"type": "object", "properties": properties, "additionalProperties": False},
        tags=["gaming", game_pack(app_id), operation, "public"],
        requires_auth=False, side_effecting=False,
        metadata={"method": "GET", "catalog_url": f"https://store.steampowered.com/app/{app_id}/",
                  "availability": "checked_at_execution", "platform_scope": "Steam"},
    )


def build_public_game_capabilities() -> list[Capability]:
    return [Capability(
        id=f"{game_pack(app_id)}.public.{operation}", name=descriptor(app_id, operation).name,
        description=OPERATIONS[operation][1], pack=game_pack(app_id),
        tags=("gaming", operation, "public"),
        candidates=(CapabilityCandidate(provider="gamepublic", ref=f"gamepublic:{app_id}/{operation}", priority=10,
                                        passthrough_arguments=True),),
        input_schema=descriptor(app_id, operation).input_schema,
    ) for app_id in PUBLIC_GAMES for operation in OPERATIONS]


class PublicGameProvider:
    name = "gamepublic"

    def __init__(self) -> None:
        self._cache: OrderedDict[str, tuple[float, dict[str, Any]]] = OrderedDict()

    async def status(self) -> dict[str, Any]:
        return {"configured": True, "searchable": True, "executable": True,
                "catalog_games": len(PUBLIC_GAMES), "availability": "checked_at_execution"}

    async def describe(self, tool_id: str) -> ToolDescriptor:
        app, _, operation = tool_id.partition("/")
        if not app.isascii() or not app.isdecimal() or int(app) not in PUBLIC_GAMES or operation not in OPERATIONS:
            raise ValueError("Unknown public game operation")
        return descriptor(int(app), operation)

    async def search(self, query: str, *, limit: int = 10) -> list[ToolDescriptor]:
        words = query.casefold().split()
        scored = []
        for app_id in PUBLIC_GAMES:
            for operation in OPERATIONS:
                item = descriptor(app_id, operation)
                haystack = f"{item.name} {item.description} {' '.join(item.tags)}".casefold()
                score = sum(word in haystack for word in words)
                if score or not words:
                    scored.append((score, item))
        scored.sort(key=lambda row: (-row[0], row[1].name))
        return [item for _, item in scored[:max(1, min(limit, 50))]]

    async def execute(self, tool_id: str, arguments: dict[str, Any], *, account=None,
                      wait_seconds=30, timeout_seconds=60, options=None) -> dict[str, Any]:
        await self.describe(tool_id)
        app, operation = tool_id.split("/")
        app_id = int(app)
        allowed = {"count"} if operation == "news" else set()
        if set(arguments) - allowed:
            raise ValueError("Unexpected arguments for this game operation")
        params = {"gameid" if operation == "achievements" else "appid": app_id}
        if operation == "news":
            count = arguments.get("count", 5)
            if isinstance(count, bool) or not isinstance(count, int) or not 1 <= count <= 20:
                raise ValueError("count must be an integer between 1 and 20")
            params.update(count=count, maxlength=1200)
        url = "https://api.steampowered.com/" + OPERATIONS[operation][2] + "?" + urlencode(params)
        cached = self._cache.get(url)
        if cached and time.monotonic() - cached[0] < 60:
            self._cache.move_to_end(url)
            record_usage("public_game_cache_hits")
            return {"status": "completed", "data": {**copy.deepcopy(cached[1]), "cached": True}}
        record_usage("public_game_requests")
        async with asyncio.timeout(max(1, min(timeout_seconds, 18))):
            result = await fetch_url(url, timeout=min(timeout_seconds, 15), max_bytes=1_000_000, max_redirects=2)
        if result.status_code != 200:
            raise RuntimeError(f"Game data is unavailable (HTTP {result.status_code}); retry later.")
        try:
            payload = json.loads(result.body_text or "")
            if operation == "news":
                section = payload["appnews"]
                if int(section["appid"]) != app_id or not isinstance(section["newsitems"], list):
                    raise ValueError("Unexpected game news response")
                data = {"items": section["newsitems"][:params["count"]]}
            elif operation == "activity":
                section = payload["response"]
                count = section.get("player_count")
                if section.get("result") != 1 or isinstance(count, bool) or not isinstance(count, int) or count < 0:
                    raise ValueError("Player activity is unavailable for this game")
                data = {"current_players": count}
            else:
                items = payload["achievementpercentages"]["achievements"]
                if not isinstance(items, list):
                    raise ValueError("Unexpected achievement response")
                data = {"items": items[:1000], "truncated": len(items) > 1000}
        except (KeyError, TypeError, ValueError) as exc:
            raise RuntimeError("This game does not currently expose the requested public data.") from exc
        output = {"game": PUBLIC_GAMES[app_id], "app_id": app_id, "operation": operation,
                  "platform_scope": "Steam", "source_url": url,
                  "captured_at": result.captured_at.isoformat(), "sha256": result.sha256,
                  "cached": False, "empty": "items" in data and not data["items"], **data}
        self._cache[url] = (time.monotonic(), copy.deepcopy(output))
        self._cache.move_to_end(url)
        while len(self._cache) > 256:
            self._cache.popitem(last=False)
        return {"status": "completed", "data": output}

    async def job_status(self, job_id: str, *, wait_seconds=0):
        raise ValueError("Public game reads complete inline")

    async def result_page(self, result_id: str, *, offset=0, limit=100):
        raise ValueError("Public game reads return bounded inline results")
