"""First-party, keyless game reference and user-supplied match analysis tools."""

from __future__ import annotations

import json
import math
import re
import time
from pathlib import Path
from typing import Any

import httpx

from .tool_mesh import ToolDescriptor

_REFERENCE = Path(__file__).with_name("data") / "mlbb_reference.json"


def _reference() -> dict[str, Any]:
    return json.loads(_REFERENCE.read_text(encoding="utf-8"))


def _number(value: Any, field: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or not 0 <= value <= 999:
        raise ValueError(field + " must be an integer between 0 and 999")
    return value


def _summary(matches: list[dict[str, Any]]) -> dict[str, Any]:
    games = len(matches)
    wins = sum(bool(row["win"]) for row in matches)
    kills = sum(row["kills"] for row in matches)
    deaths = sum(row["deaths"] for row in matches)
    assists = sum(row["assists"] for row in matches)
    rate = wins / games
    z = 1.96
    denominator = 1 + z * z / games
    center = (rate + z * z / (2 * games)) / denominator
    radius = z * math.sqrt(rate * (1 - rate) / games + z * z / (4 * games * games)) / denominator
    return {
        "games": games, "wins": wins, "losses": games - wins,
        "win_rate": round(rate * 100, 1),
        "win_rate_95pct_interval": [round(max(0, center - radius) * 100, 1),
                                   round(min(1, center + radius) * 100, 1)],
        "kills": kills, "deaths": deaths, "assists": assists,
        "kda": round((kills + assists) / max(1, deaths), 2),
    }


def analyze_matches(arguments: dict[str, Any]) -> dict[str, Any]:
    game = str(arguments.get("game") or "").strip()
    if not 2 <= len(game) <= 60:
        raise ValueError("game must contain 2–60 characters")
    entries = arguments.get("matches")
    if not isinstance(entries, list) or not 1 <= len(entries) <= 100:
        raise ValueError("matches must be an array of 1–100 games, oldest first")
    matches: list[dict[str, Any]] = []
    for index, row in enumerate(entries):
        if not isinstance(row, dict) or type(row.get("win")) is not bool:
            raise ValueError("each match requires win as a boolean (match " + str(index + 1) + ")")
        hero = str(row.get("hero") or "").strip()
        if len(hero) > 60:
            raise ValueError("hero name exceeds 60 characters")
        matches.append({
            "win": row["win"], "hero": hero,
            **{field: _number(row.get(field, 0), field) for field in ("kills", "deaths", "assists")},
        })
    by_hero: dict[str, list[dict[str, Any]]] = {}
    for row in matches:
        if row["hero"]:
            by_hero.setdefault(row["hero"].casefold(), []).append(row)
    heroes = [{"hero": rows[0]["hero"], **_summary(rows)} for rows in by_hero.values()]
    heroes.sort(key=lambda row: (-row["games"], row["hero"].casefold()))
    latest = matches[-min(10, len(matches)):]
    previous = matches[-20:-10] if len(matches) > 10 else []
    streak = 0
    for row in reversed(matches):
        if row["win"] != matches[-1]["win"]:
            break
        streak += 1
    return {
        "game": game, "sample": "user-supplied match results, oldest first",
        "overall": _summary(matches), "recent_10": _summary(latest),
        "previous_10": _summary(previous) if previous else None,
        "current_streak": {"outcome": "win" if matches[-1]["win"] else "loss", "games": streak},
        "heroes": heroes[:25],
        "caveat": "The interval measures sampling uncertainty; it does not predict matchmaking, rank, or future results.",
    }


class GameCoreProvider:
    name = "gamecore"

    def __init__(self, client: httpx.AsyncClient | None = None) -> None:
        self.client = client
        self._cdn_cache: dict[str, tuple[float, Any]] = {}

    async def status(self) -> dict[str, Any]:
        return {"configured": True, "searchable": True, "executable": True,
                "kind": "bundled-reference-and-local-analysis", "authentication": "none",
                "tool_availability": {"gamecore:" + tool: _REFERENCE.is_file() if tool.startswith("mlbb-") else True
                                      for tool in self._tools()}}

    def _tools(self) -> dict[str, ToolDescriptor]:
        return {
            "mlbb-heroes": ToolDescriptor(
                ref="gamecore:mlbb-heroes", provider=self.name, tool_id="mlbb-heroes",
                name="MLBB hero reference search", description="Search bundled heroes by name, role, or lane. Data is historical.",
                input_schema={"type": "object", "properties": {"query": {"type": "string", "maxLength": 60},
                              "limit": {"type": "integer", "minimum": 1, "maximum": 25}}},
                tags=["mlbb", "heroes", "reference", "offline"], requires_auth=False, side_effecting=False),
            "mlbb-hero": ToolDescriptor(
                ref="gamecore:mlbb-hero", provider=self.name, tool_id="mlbb-hero",
                name="MLBB hero detail", description="Retrieve bundled hero role, lanes, synergies and counters.",
                input_schema={"type": "object", "required": ["hero"], "properties": {
                    "hero": {"type": "string", "minLength": 1, "maxLength": 60}}},
                tags=["mlbb", "hero", "reference", "offline"], requires_auth=False, side_effecting=False),
            "mlbb-items": ToolDescriptor(
                ref="gamecore:mlbb-items", provider=self.name, tool_id="mlbb-items",
                name="MLBB item reference search", description="Search historical items by name and category.",
                input_schema={"type": "object", "properties": {"query": {"type": "string", "maxLength": 60},
                              "limit": {"type": "integer", "minimum": 1, "maximum": 25}}},
                tags=["mlbb", "items", "reference", "offline"], requires_auth=False, side_effecting=False),
            "match-analysis": ToolDescriptor(
                ref="gamecore:match-analysis", provider=self.name, tool_id="match-analysis",
                name="Analyze supplied match results", description="Calculate win rate, recent form, hero usage and KDA from supplied results for any game.",
                input_schema={"type": "object", "required": ["game", "matches"], "properties": {
                    "game": {"type": "string", "minLength": 2, "maxLength": 60},
                    "matches": {"type": "array", "minItems": 1, "maxItems": 100, "items": {
                        "type": "object", "required": ["win"], "properties": {
                            "win": {"type": "boolean"}, "hero": {"type": "string"},
                            "kills": {"type": "integer", "minimum": 0, "maximum": 999},
                            "deaths": {"type": "integer", "minimum": 0, "maximum": 999},
                            "assists": {"type": "integer", "minimum": 0, "maximum": 999}}}}}},
                tags=["gaming", "matches", "win-rate", "analytics", "offline"],
                requires_auth=False, side_effecting=False),
            "league-champions": ToolDescriptor(
                ref="gamecore:league-champions", provider=self.name, tool_id="league-champions",
                name="League champion reference", description="Search Riot Data Dragon champion names and roles from its published patch data; no Riot API key.",
                input_schema={"type": "object", "properties": {"query": {"type": "string", "maxLength": 60},
                              "limit": {"type": "integer", "minimum": 1, "maximum": 25}}},
                tags=["league", "champions", "riot", "reference"], requires_auth=False, side_effecting=False),
            "league-items": ToolDescriptor(
                ref="gamecore:league-items", provider=self.name, tool_id="league-items",
                name="League item reference", description="Search published Riot Data Dragon items by name; no Riot API key.",
                input_schema={"type": "object", "properties": {"query": {"type": "string", "maxLength": 60},
                              "limit": {"type": "integer", "minimum": 1, "maximum": 25}}},
                tags=["league", "items", "riot", "reference"], requires_auth=False, side_effecting=False),
        }

    async def _cdn_json(self, path: str, *, max_bytes: int) -> Any:
        cached = self._cdn_cache.get(path)
        if cached and cached[0] > time.monotonic():
            return cached[1]
        url = "https://ddragon.leagueoflegends.com" + path
        try:
            if self.client is not None:
                response = await self.client.get(url, timeout=12, follow_redirects=False)
            else:
                async with httpx.AsyncClient(timeout=12, follow_redirects=False) as client:
                    response = await client.get(url)
            response.raise_for_status()
        except httpx.HTTPError as exc:
            raise RuntimeError("Riot Data Dragon is temporarily unavailable") from exc
        if len(response.content) > max_bytes:
            raise RuntimeError("Riot Data Dragon response exceeded the bounded size")
        try:
            data = response.json()
        except ValueError as exc:
            raise RuntimeError("Riot Data Dragon returned invalid JSON") from exc
        self._cdn_cache[path] = (time.monotonic() + 900, data)
        return data

    async def _league_reference(self, tool_id: str, arguments: dict[str, Any]) -> dict[str, Any]:
        query = str(arguments.get("query") or "").strip().casefold()
        if len(query) > 60:
            raise ValueError("query exceeds 60 characters")
        limit = arguments.get("limit", 15)
        if isinstance(limit, bool) or not isinstance(limit, int) or not 1 <= limit <= 25:
            raise ValueError("limit must be an integer from 1 to 25")
        versions = await self._cdn_json("/api/versions.json", max_bytes=100_000)
        if not isinstance(versions, list) or not versions or not isinstance(versions[0], str):
            raise RuntimeError("Riot Data Dragon version index is unavailable")
        version = versions[0]
        if not re.fullmatch(r"[0-9]+(?:\.[0-9]+){1,3}", version):
            raise RuntimeError("Riot Data Dragon returned an invalid version")
        category = "champion" if tool_id == "league-champions" else "item"
        path = "/cdn/" + version + "/data/en_US/" + category + ".json"
        payload = await self._cdn_json(path, max_bytes=3_000_000)
        raw = payload.get("data") if isinstance(payload, dict) else None
        if not isinstance(raw, dict):
            raise TypeError("Riot Data Dragon data format changed")
        results = []
        for key, value in raw.items():
            if not isinstance(value, dict) or not isinstance(value.get("name"), str):
                continue
            if query not in (value["name"] + " " + " ".join(str(tag) for tag in (value.get("tags") or []))).casefold():
                continue
            if category == "champion":
                results.append({"id": key, "name": value["name"], "title": value.get("title"),
                                "roles": value.get("tags") or []})
            else:
                results.append({"id": key, "name": value["name"], "cost": (value.get("gold") or {}).get("total"),
                                "stats": value.get("stats") or {}, "maps": value.get("maps") or {}})
        results.sort(key=lambda item: item["name"].casefold())
        return {"results": results[:limit], "total": len(results),
                "provenance": {"source": "https://developer.riotgames.com/docs/lol", "version": version,
                               "data_url": "https://ddragon.leagueoflegends.com" + path,
                               "kind": "published static reference, not player rank"}}

    async def search(self, query: str, *, limit: int = 10) -> list[ToolDescriptor]:
        phrase = query.casefold().strip()
        return [tool for tool in self._tools().values()
                if not phrase or any(word in (tool.name + " " + tool.description + " " + " ".join(tool.tags)).casefold()
                                     for word in phrase.split())][:limit]

    async def describe(self, tool_id: str) -> ToolDescriptor:
        try:
            return self._tools()[tool_id]
        except KeyError as exc:
            raise ValueError("unknown gamecore tool") from exc

    async def execute(self, tool_id: str, arguments: dict[str, Any], *, account: str | None = None,
                      wait_seconds: int = 30, timeout_seconds: int = 60,
                      options: dict[str, Any] | None = None) -> dict[str, Any]:
        del account, wait_seconds, timeout_seconds, options
        if tool_id == "match-analysis":
            result = analyze_matches(arguments)
            return {"status": "completed", "data": result, "metadata": {"source": "user supplied"}}
        if tool_id in {"league-champions", "league-items"}:
            data = await self._league_reference(tool_id, arguments)
            return {"status": "completed", "data": data, "metadata": data["provenance"]}
        if tool_id not in {"mlbb-heroes", "mlbb-hero", "mlbb-items"}:
            raise ValueError("unknown gamecore tool")
        reference = _reference()
        provenance = {"source": reference["source"], "license": reference["license"],
                      "hero_revision": reference["hero_revision"], "item_revision": reference["item_revision"],
                      "snapshot": True, "current_patch": False}
        if tool_id == "mlbb-hero":
            requested = str(arguments.get("hero") or "").strip().casefold()
            if not requested or len(requested) > 60:
                raise ValueError("hero must contain 1–60 characters")
            hero = next((row for row in reference["heroes"]
                         if requested in {row["name"].casefold(), str(row["id"]).casefold()}), None)
            if not hero:
                raise ValueError("hero is not in this historical snapshot")
            data = {"hero": hero, "provenance": provenance}
        else:
            query = str(arguments.get("query") or "").strip().casefold()
            if len(query) > 60:
                raise ValueError("query exceeds 60 characters")
            limit = arguments.get("limit", 15)
            if isinstance(limit, bool) or not isinstance(limit, int) or not 1 <= limit <= 25:
                raise ValueError("limit must be an integer from 1 to 25")
            key, name = ("heroes", "name") if tool_id == "mlbb-heroes" else ("items", "name")
            rows = [row for row in reference[key] if query in
                    (row[name] + " " + str(row.get("role") or row.get("category") or "") +
                     " " + " ".join(row.get("lanes") or [])).casefold()]
            data = {"results": rows[:limit], "total": len(rows), "provenance": provenance}
        return {"status": "completed", "data": data, "metadata": provenance}
