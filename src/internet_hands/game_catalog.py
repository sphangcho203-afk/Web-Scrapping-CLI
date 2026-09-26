"""Game adapters over the existing semantic capability registry.

Only registered capabilities appear. Provider readiness is checked at request
time so a configured game is never confused with a callable game API.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from .public_game_manifest import PUBLIC_GAMES, game_pack

GAME_PACKS: dict[str, tuple[str, tuple[str, ...]]] = {
    "mlbb": ("Mobile Legends: Bang Bang", ("mlbb",)),
    "valorant": ("VALORANT", ("valorant",)),
    "league": ("League of Legends", ("league",)),
    "dota2": ("Dota 2", ("dota2",)),
    "minecraft": ("Minecraft", ("minecraft", "hypixel")),
    "genshin": ("Genshin Impact", ("genshin",)),
    "hsr": ("Honkai: Star Rail", ("hsr",)),
    "zzz": ("Zenless Zone Zero", ("zzz",)),
    "roblox": ("Roblox", ("roblox",)),
    "osu": ("osu!", ("osu",)),
    "brawlstars": ("Brawl Stars", ("brawlstars",)),
    "clashofclans": ("Clash of Clans", ("clashofclans",)),
    "clashroyale": ("Clash Royale", ("clashroyale",)),
    "tft": ("Teamfight Tactics", ("tft",)),
    "steam": ("Steam", ("steam",)),
    "riot": ("Riot Games", ("riot",)),
}


GAME_PACKS.update({game_pack(app_id): (name, (game_pack(app_id),))
                   for app_id, name in PUBLIC_GAMES.items() if game_pack(app_id) not in GAME_PACKS})


@dataclass(frozen=True, slots=True)
class GameAdapter:
    game_id: str
    name: str
    packs: tuple[str, ...]
    capabilities: tuple[Any, ...]

    def to_dict(self, statuses: dict[str, dict[str, Any]], *, details: bool = False) -> dict[str, Any]:
        rows = []
        for capability in self.capabilities:
            providers = sorted({candidate.provider for candidate in capability.candidates})
            provider_ready = any(
                bool(getattr(candidate, "ref", None))
                and bool(statuses.get(candidate.provider, {}).get("executable"))
                and statuses.get(candidate.provider, {}).get("tool_availability", {}).get(getattr(candidate, "ref", None), True)
                for candidate in capability.candidates
            )
            needs_key = not provider_ready and any(
                statuses.get(candidate.provider, {}).get("tool_availability", {}).get(getattr(candidate, "ref", None)) is False
                for candidate in capability.candidates
            )
            discovery_only = not provider_ready and not needs_key and any(
                not getattr(candidate, "ref", None)
                and bool(statuses.get(candidate.provider, {}).get("searchable"))
                for candidate in capability.candidates
            )
            rows.append({
                "id": capability.id,
                "name": capability.name,
                "description": capability.description,
                "provider_ready": provider_ready,
                "availability": ("ready" if provider_ready else "key_required" if needs_key
                                 else "discovery_required" if discovery_only else "unavailable"),
                "providers": providers,
                "input_schema": capability.input_schema,
            })
        data: dict[str, Any] = {
            "game_id": self.game_id,
            "name": self.name,
            "capability_count": len(rows),
            "provider_ready_count": sum(1 for row in rows if row["provider_ready"]),
        }
        if details:
            data["capabilities"] = rows
        return data


def build_game_adapters(capabilities: dict[str, Any]) -> dict[str, GameAdapter]:
    adapters = {}
    for game_id, (name, packs) in GAME_PACKS.items():
        matches = tuple(sorted(
            (cap for cap in capabilities.values() if cap.pack in packs or cap.pack == "gaming-common"), key=lambda cap: cap.id,
        ))
        if matches:
            adapters[game_id] = GameAdapter(game_id, name, packs, matches)
    return adapters
