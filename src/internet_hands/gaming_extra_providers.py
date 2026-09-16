from __future__ import annotations

import os
import re
from typing import Any
from urllib.parse import quote

import httpx

from .policy import validate_public_http_url
from .tool_mesh import ToolDescriptor

_RIOT_PLATFORMS = {
    "br1",
    "eun1",
    "euw1",
    "jp1",
    "kr",
    "la1",
    "la2",
    "na1",
    "oc1",
    "tr1",
    "ru",
    "ph2",
    "sg2",
    "th2",
    "tw2",
    "vn2",
}
_RIOT_REGIONALS = {"americas", "asia", "europe", "sea"}


def _schema(
    properties: dict[str, dict[str, Any]],
    required: list[str],
) -> dict[str, Any]:
    return {"type": "object", "properties": properties, "required": required}


def _string(description: str = "") -> dict[str, Any]:
    result: dict[str, Any] = {"type": "string"}
    if description:
        result["description"] = description
    return result


class _GamingProviderBase:
    name: str

    def __init__(
        self,
        descriptors: list[ToolDescriptor],
        *,
        client: httpx.AsyncClient | None = None,
        validate_urls: bool = True,
    ) -> None:
        self.descriptors = {item.tool_id: item for item in descriptors}
        self.client = client
        self.validate_urls = validate_urls

    async def search(self, query: str, *, limit: int = 10) -> list[ToolDescriptor]:
        words = [word for word in re.split(r"\W+", query.casefold()) if word]
        ranked: list[tuple[int, ToolDescriptor]] = []
        for descriptor in self.descriptors.values():
            haystack = " ".join(
                [
                    descriptor.tool_id,
                    descriptor.name,
                    descriptor.description,
                    *descriptor.tags,
                ]
            ).casefold()
            score = sum(
                5 if word in descriptor.name.casefold() else 1
                for word in words
                if word in haystack
            )
            if score or not words:
                ranked.append((score, descriptor))
        ranked.sort(key=lambda row: (-row[0], row[1].tool_id))
        return [item for _, item in ranked[: max(1, min(limit, 50))]]

    async def describe(self, tool_id: str) -> ToolDescriptor:
        try:
            return self.descriptors[tool_id]
        except KeyError as exc:
            raise ValueError(f"unknown {self.name} tool: {tool_id}") from exc

    async def _request(
        self,
        method: str,
        url: str,
        **kwargs: Any,
    ) -> httpx.Response:
        if self.validate_urls:
            validate_public_http_url(url)
        if self.client is not None:
            response = await self.client.request(method, url, **kwargs)
            response.raise_for_status()
            return response
        async with httpx.AsyncClient(follow_redirects=False) as client:
            response = await client.request(method, url, **kwargs)
            response.raise_for_status()
            return response

    async def job_status(self, job_id: str, *, wait_seconds: int = 0) -> dict[str, Any]:
        del job_id, wait_seconds
        raise NotImplementedError(f"{self.name} tools return results inline")

    async def result_page(
        self,
        result_id: str,
        *,
        offset: int = 0,
        limit: int = 100,
    ) -> dict[str, Any]:
        del result_id, offset, limit
        raise NotImplementedError(f"{self.name} tools return results inline")


class SteamGamingProvider(_GamingProviderBase):
    name = "steam"

    def __init__(
        self,
        api_key: str | None = None,
        *,
        client: httpx.AsyncClient | None = None,
        validate_urls: bool = True,
    ) -> None:
        self.api_key = (
            api_key
            if api_key is not None
            else os.getenv("STEAM_WEB_API_KEY", "").strip()
        )
        descriptors = [
            ToolDescriptor(
                ref="steam:resolve-vanity",
                provider="steam",
                tool_id="resolve-vanity",
                name="Steam vanity/IGN resolver",
                description="Resolve a public Steam vanity profile name to a SteamID64.",
                input_schema=_schema(
                    {
                        "vanityurl": _string("Steam vanity profile name"),
                        "url_type": {"type": "integer", "enum": [1, 2, 3]},
                    },
                    ["vanityurl"],
                ),
                tags=["gaming", "steam", "ign", "vanity", "steamid", "resolve"],
                requires_auth=True,
                side_effecting=False,
                metadata={"source": "Steamworks Web API", "official": True},
            ),
            ToolDescriptor(
                ref="steam:player-summaries",
                provider="steam",
                tool_id="player-summaries",
                name="Steam public player summaries",
                description="Get public Steam profile summaries for one or more SteamID64 values.",
                input_schema=_schema(
                    {"steamids": _string("Comma-delimited SteamID64 values, max 100")},
                    ["steamids"],
                ),
                tags=["gaming", "steam", "player", "profile", "persona"],
                requires_auth=True,
                side_effecting=False,
                metadata={"source": "Steamworks Web API", "official": True},
            ),
            ToolDescriptor(
                ref="steam:recent-games",
                provider="steam",
                tool_id="recent-games",
                name="Steam recently played games",
                description="Get recently played games and playtime for a public Steam profile.",
                input_schema=_schema(
                    {
                        "steamid": _string("SteamID64"),
                        "count": {"type": "integer", "minimum": 0, "maximum": 100},
                    },
                    ["steamid"],
                ),
                tags=["gaming", "steam", "games", "recent", "playtime"],
                requires_auth=True,
                side_effecting=False,
                metadata={"source": "Steamworks Web API", "official": True},
            ),
            ToolDescriptor(
                ref="steam:owned-games",
                provider="steam",
                tool_id="owned-games",
                name="Steam public owned games",
                description=(
                    "Get games owned by a player when their game details are public, including "
                    "playtime and optional app metadata."
                ),
                input_schema=_schema(
                    {
                        "steamid": _string("SteamID64"),
                        "include_appinfo": {"type": "boolean"},
                        "include_played_free_games": {"type": "boolean"},
                    },
                    ["steamid"],
                ),
                tags=["gaming", "steam", "library", "games", "playtime"],
                requires_auth=True,
                side_effecting=False,
                metadata={"source": "Steamworks Web API", "official": True},
            ),
        ]
        super().__init__(descriptors, client=client, validate_urls=validate_urls)

    async def status(self) -> dict[str, Any]:
        return {
            "configured": bool(self.api_key),
            "searchable": True,
            "executable": bool(self.api_key),
            "kind": "official-gaming-api",
            "tool_count": len(self.descriptors),
            "authentication": "server-side query key",
        }

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
        if not self.api_key:
            raise RuntimeError("STEAM_WEB_API_KEY is required for Steam intelligence")

        params: dict[str, Any] = {"key": self.api_key}
        if tool_id == "resolve-vanity":
            vanity = str(arguments.get("vanityurl") or "").strip()
            if not vanity:
                raise ValueError("vanityurl is required")
            url = "https://api.steampowered.com/ISteamUser/ResolveVanityURL/v1/"
            params["vanityurl"] = vanity
            if arguments.get("url_type") is not None:
                params["url_type"] = int(arguments["url_type"])
        elif tool_id == "player-summaries":
            steamids = str(arguments.get("steamids") or "").strip()
            if not steamids:
                raise ValueError("steamids is required")
            url = "https://api.steampowered.com/ISteamUser/GetPlayerSummaries/v2/"
            params["steamids"] = steamids
        elif tool_id == "recent-games":
            steamid = str(arguments.get("steamid") or "").strip()
            if not steamid:
                raise ValueError("steamid is required")
            url = "https://api.steampowered.com/IPlayerService/GetRecentlyPlayedGames/v1/"
            params["steamid"] = steamid
            if arguments.get("count") is not None:
                params["count"] = max(0, min(int(arguments["count"]), 100))
        elif tool_id == "owned-games":
            steamid = str(arguments.get("steamid") or "").strip()
            if not steamid:
                raise ValueError("steamid is required")
            url = "https://api.steampowered.com/IPlayerService/GetOwnedGames/v1/"
            params.update(
                {
                    "steamid": steamid,
                    "include_appinfo": str(
                        bool(arguments.get("include_appinfo", True))
                    ).lower(),
                    "include_played_free_games": str(
                        bool(arguments.get("include_played_free_games", True))
                    ).lower(),
                }
            )
        else:
            raise ValueError(f"unknown Steam tool: {tool_id}")

        response = await self._request(
            "GET",
            url,
            params=params,
            headers={"Accept": "application/json"},
            timeout=max(1.0, min(float(timeout_seconds), 60.0)),
        )
        return {
            "status": "completed",
            "data": response.json(),
            "metadata": {
                "provider": "steam",
                "http_status": response.status_code,
                "official": True,
            },
        }


class RiotGamingProvider(_GamingProviderBase):
    name = "riot"

    def __init__(
        self,
        api_key: str | None = None,
        *,
        client: httpx.AsyncClient | None = None,
        validate_urls: bool = True,
    ) -> None:
        self.api_key = (
            api_key if api_key is not None else os.getenv("RIOT_API_KEY", "").strip()
        )
        route_prop = {
            "type": "string",
            "description": "Riot routing value; values are allowlisted by Internet Hands.",
        }
        descriptors = [
            ToolDescriptor(
                ref="riot:account-by-riot-id",
                provider="riot",
                tool_id="account-by-riot-id",
                name="Riot ID to PUUID",
                description="Resolve a Riot ID (game name + tag line) to its public PUUID.",
                input_schema=_schema(
                    {
                        "regional": route_prop,
                        "game_name": _string("Riot ID game name"),
                        "tag_line": _string("Riot ID tag line"),
                    },
                    ["regional", "game_name", "tag_line"],
                ),
                tags=["gaming", "riot", "league", "tft", "riot-id", "ign", "puuid"],
                requires_auth=True,
                side_effecting=False,
                metadata={"source": "Riot Games API", "official": True},
            ),
            ToolDescriptor(
                ref="riot:account-by-puuid",
                provider="riot",
                tool_id="account-by-puuid",
                name="Riot PUUID to Riot ID",
                description="Resolve a public PUUID to current Riot ID account information.",
                input_schema=_schema(
                    {"regional": route_prop, "puuid": _string("Riot PUUID")},
                    ["regional", "puuid"],
                ),
                tags=["gaming", "riot", "league", "tft", "puuid", "riot-id"],
                requires_auth=True,
                side_effecting=False,
                metadata={"source": "Riot Games API", "official": True},
            ),
            ToolDescriptor(
                ref="riot:lol-summoner-by-puuid",
                provider="riot",
                tool_id="lol-summoner-by-puuid",
                name="League summoner profile by PUUID",
                description="Get League summoner/profile metadata from a PUUID.",
                input_schema=_schema(
                    {"platform": route_prop, "puuid": _string("Riot PUUID")},
                    ["platform", "puuid"],
                ),
                tags=["gaming", "league", "lol", "player", "profile", "puuid"],
                requires_auth=True,
                side_effecting=False,
                metadata={"source": "Riot Games API", "official": True},
            ),
            ToolDescriptor(
                ref="riot:lol-champion-mastery",
                provider="riot",
                tool_id="lol-champion-mastery",
                name="League champion mastery",
                description=(
                    "Get League champion mastery rows for a PUUID, suitable for identifying "
                    "mains and most-played/mastered champions."
                ),
                input_schema=_schema(
                    {"platform": route_prop, "puuid": _string("Riot PUUID")},
                    ["platform", "puuid"],
                ),
                tags=["gaming", "league", "lol", "champions", "mastery", "mains"],
                requires_auth=True,
                side_effecting=False,
                metadata={"source": "Riot Games API", "official": True},
            ),
            ToolDescriptor(
                ref="riot:lol-ranked-entries",
                provider="riot",
                tool_id="lol-ranked-entries",
                name="League ranked entries",
                description="Get current League ranked queue entries for a PUUID.",
                input_schema=_schema(
                    {"platform": route_prop, "puuid": _string("Riot PUUID")},
                    ["platform", "puuid"],
                ),
                tags=["gaming", "league", "lol", "rank", "lp", "tier"],
                requires_auth=True,
                side_effecting=False,
                metadata={"source": "Riot Games API", "official": True},
            ),
            ToolDescriptor(
                ref="riot:lol-match-ids",
                provider="riot",
                tool_id="lol-match-ids",
                name="League recent match IDs",
                description="Get League match IDs for a PUUID from Match-V5.",
                input_schema=_schema(
                    {
                        "regional": route_prop,
                        "puuid": _string("Riot PUUID"),
                        "start": {"type": "integer", "minimum": 0},
                        "count": {"type": "integer", "minimum": 1, "maximum": 100},
                        "queue": {"type": "integer"},
                        "type": _string("Optional Riot Match-V5 type filter"),
                    },
                    ["regional", "puuid"],
                ),
                tags=["gaming", "league", "lol", "matches", "recent", "history"],
                requires_auth=True,
                side_effecting=False,
                metadata={"source": "Riot Games API", "official": True},
            ),
            ToolDescriptor(
                ref="riot:lol-match",
                provider="riot",
                tool_id="lol-match",
                name="League match detail",
                description="Get one League Match-V5 match payload by match ID.",
                input_schema=_schema(
                    {"regional": route_prop, "match_id": _string("Riot match ID")},
                    ["regional", "match_id"],
                ),
                tags=["gaming", "league", "lol", "match", "stats"],
                requires_auth=True,
                side_effecting=False,
                metadata={"source": "Riot Games API", "official": True},
            ),
            ToolDescriptor(
                ref="riot:tft-match-ids",
                provider="riot",
                tool_id="tft-match-ids",
                name="TFT recent match IDs",
                description="Get recent Teamfight Tactics match IDs for a PUUID.",
                input_schema=_schema(
                    {
                        "regional": route_prop,
                        "puuid": _string("Riot PUUID"),
                        "start": {"type": "integer", "minimum": 0},
                        "count": {"type": "integer", "minimum": 1, "maximum": 100},
                    },
                    ["regional", "puuid"],
                ),
                tags=["gaming", "tft", "teamfight-tactics", "matches", "recent"],
                requires_auth=True,
                side_effecting=False,
                metadata={"source": "Riot Games API", "official": True},
            ),
            ToolDescriptor(
                ref="riot:tft-match",
                provider="riot",
                tool_id="tft-match",
                name="TFT match detail",
                description="Get one Teamfight Tactics match payload by match ID.",
                input_schema=_schema(
                    {"regional": route_prop, "match_id": _string("TFT match ID")},
                    ["regional", "match_id"],
                ),
                tags=["gaming", "tft", "teamfight-tactics", "match", "placement"],
                requires_auth=True,
                side_effecting=False,
                metadata={"source": "Riot Games API", "official": True},
            ),
        ]
        super().__init__(descriptors, client=client, validate_urls=validate_urls)

    async def status(self) -> dict[str, Any]:
        return {
            "configured": bool(self.api_key),
            "searchable": True,
            "executable": bool(self.api_key),
            "kind": "official-gaming-api",
            "tool_count": len(self.descriptors),
            "platform_routes": sorted(_RIOT_PLATFORMS),
            "regional_routes": sorted(_RIOT_REGIONALS),
        }

    @staticmethod
    def _platform(arguments: dict[str, Any]) -> str:
        platform = str(arguments.get("platform") or "").strip().casefold()
        if platform not in _RIOT_PLATFORMS:
            raise ValueError("invalid Riot platform routing value")
        return platform

    @staticmethod
    def _regional(arguments: dict[str, Any]) -> str:
        regional = str(arguments.get("regional") or "").strip().casefold()
        if regional not in _RIOT_REGIONALS:
            raise ValueError("invalid Riot regional routing value")
        return regional

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
        if not self.api_key:
            raise RuntimeError("RIOT_API_KEY is required for Riot gaming intelligence")

        params: dict[str, Any] = {}
        if tool_id == "account-by-riot-id":
            regional = self._regional(arguments)
            game_name = str(arguments.get("game_name") or "").strip()
            tag_line = str(arguments.get("tag_line") or "").strip()
            if not game_name or not tag_line:
                raise ValueError("game_name and tag_line are required")
            url = (
                f"https://{regional}.api.riotgames.com/riot/account/v1/accounts/"
                f"by-riot-id/{quote(game_name, safe='')}/{quote(tag_line, safe='')}"
            )
        elif tool_id == "account-by-puuid":
            regional = self._regional(arguments)
            puuid = str(arguments.get("puuid") or "").strip()
            if not puuid:
                raise ValueError("puuid is required")
            url = (
                f"https://{regional}.api.riotgames.com/riot/account/v1/accounts/"
                f"by-puuid/{quote(puuid, safe='')}"
            )
        elif tool_id == "lol-summoner-by-puuid":
            platform = self._platform(arguments)
            puuid = str(arguments.get("puuid") or "").strip()
            if not puuid:
                raise ValueError("puuid is required")
            url = (
                f"https://{platform}.api.riotgames.com/lol/summoner/v4/summoners/"
                f"by-puuid/{quote(puuid, safe='')}"
            )
        elif tool_id == "lol-champion-mastery":
            platform = self._platform(arguments)
            puuid = str(arguments.get("puuid") or "").strip()
            if not puuid:
                raise ValueError("puuid is required")
            url = (
                f"https://{platform}.api.riotgames.com/lol/champion-mastery/v4/"
                f"champion-masteries/by-puuid/{quote(puuid, safe='')}"
            )
        elif tool_id == "lol-ranked-entries":
            platform = self._platform(arguments)
            puuid = str(arguments.get("puuid") or "").strip()
            if not puuid:
                raise ValueError("puuid is required")
            url = (
                f"https://{platform}.api.riotgames.com/lol/league/v4/entries/"
                f"by-puuid/{quote(puuid, safe='')}"
            )
        elif tool_id == "lol-match-ids":
            regional = self._regional(arguments)
            puuid = str(arguments.get("puuid") or "").strip()
            if not puuid:
                raise ValueError("puuid is required")
            url = (
                f"https://{regional}.api.riotgames.com/lol/match/v5/matches/"
                f"by-puuid/{quote(puuid, safe='')}/ids"
            )
            for name in ("start", "count", "queue", "type"):
                if arguments.get(name) is not None:
                    params[name] = arguments[name]
            if "count" not in params:
                params["count"] = 20
        elif tool_id == "lol-match":
            regional = self._regional(arguments)
            match_id = str(arguments.get("match_id") or "").strip()
            if not match_id:
                raise ValueError("match_id is required")
            url = (
                f"https://{regional}.api.riotgames.com/lol/match/v5/matches/"
                f"{quote(match_id, safe='')}"
            )
        elif tool_id == "tft-match-ids":
            regional = self._regional(arguments)
            puuid = str(arguments.get("puuid") or "").strip()
            if not puuid:
                raise ValueError("puuid is required")
            url = (
                f"https://{regional}.api.riotgames.com/tft/match/v1/matches/"
                f"by-puuid/{quote(puuid, safe='')}/ids"
            )
            params["start"] = max(0, int(arguments.get("start", 0)))
            params["count"] = max(1, min(int(arguments.get("count", 20)), 100))
        elif tool_id == "tft-match":
            regional = self._regional(arguments)
            match_id = str(arguments.get("match_id") or "").strip()
            if not match_id:
                raise ValueError("match_id is required")
            url = (
                f"https://{regional}.api.riotgames.com/tft/match/v1/matches/"
                f"{quote(match_id, safe='')}"
            )
        else:
            raise ValueError(f"unknown Riot tool: {tool_id}")

        response = await self._request(
            "GET",
            url,
            params=params,
            headers={"Accept": "application/json", "X-Riot-Token": self.api_key},
            timeout=max(1.0, min(float(timeout_seconds), 60.0)),
        )
        return {
            "status": "completed",
            "data": response.json(),
            "metadata": {
                "provider": "riot",
                "http_status": response.status_code,
                "official": True,
            },
        }


def build_extra_gaming_providers() -> list[SteamGamingProvider | RiotGamingProvider]:
    return [SteamGamingProvider(), RiotGamingProvider()]
