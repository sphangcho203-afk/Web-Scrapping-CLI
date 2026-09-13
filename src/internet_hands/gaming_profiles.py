from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True, slots=True)
class GamingProfilePlan:
    game: str
    identity: dict[str, Any]
    requests: list[dict[str, Any]]
    note: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "game": self.game,
            "identity": self.identity,
            "requests": self.requests,
            "note": self.note,
        }


def _require(identity: dict[str, Any], *names: str) -> None:
    missing = [name for name in names if identity.get(name) in (None, "")]
    if missing:
        raise ValueError(f"missing identity fields: {', '.join(missing)}")


def _calls(capabilities: list[str], arguments: dict[str, Any]) -> list[dict[str, Any]]:
    return [
        {"capability": capability, "arguments": dict(arguments)}
        for capability in capabilities
    ]


def build_gaming_profile_plan(
    game: str,
    identity: dict[str, Any],
    *,
    include_recent: bool = True,
    include_history: bool = True,
) -> GamingProfilePlan:
    game = game.strip().casefold().replace("_", "-")
    identity = {key: value for key, value in identity.items() if value is not None}

    if game in {"mlbb", "mobile-legends", "mobile-legends-bang-bang"}:
        _require(identity, "id", "zone")
        return GamingProfilePlan(
            game="mlbb",
            identity=identity,
            requests=_calls(["mlbb.player.lookup"], identity),
            note=(
                "The rich MLBB lookup payload is intentionally fetched once; current/highest rank, "
                "hero history, collector/skin and squad fields can be extracted from that evidence."
            ),
        )

    if game in {"valorant", "val"}:
        _require(identity, "name", "tag", "region")
        capabilities = ["valorant.account.lookup", "valorant.rank.mmr"]
        if include_recent:
            capabilities.append("valorant.matches.recent")
        if include_history:
            capabilities.append("valorant.rank.history")
        return GamingProfilePlan("valorant", identity, _calls(capabilities, identity))

    if game in {"league", "league-of-legends", "lol"}:
        if identity.get("puuid"):
            _require(identity, "platform", "regional")
            capabilities = [
                "league.player.profile",
                "league.rank.current",
                "league.champion.mastery",
            ]
            if include_recent:
                capabilities.append("league.matches.recent")
            return GamingProfilePlan(
                "league",
                identity,
                _calls(capabilities, identity),
                note=(
                    "Champion mastery is used as the official mains/mastery signal. Match IDs are "
                    "returned first; match detail can be fetched for selected IDs afterward."
                ),
            )
        _require(identity, "game_name", "tag_line", "regional")
        return GamingProfilePlan(
            "league",
            identity,
            _calls(["riot.account.lookup"], identity),
            note=(
                "Resolve Riot ID to PUUID first. Re-run the League profile preset with PUUID, "
                "platform and regional routing values for profile/rank/mastery/matches."
            ),
        )

    if game in {"tft", "teamfight-tactics"}:
        if identity.get("puuid"):
            _require(identity, "regional")
            capabilities = ["riot.account.reverse"]
            if include_recent:
                capabilities.append("tft.matches.recent")
            return GamingProfilePlan(
                "tft",
                identity,
                _calls(capabilities, identity),
                note="Match IDs can be expanded with tft.match.detail for selected games.",
            )
        _require(identity, "game_name", "tag_line", "regional")
        return GamingProfilePlan(
            "tft",
            identity,
            _calls(["riot.account.lookup"], identity),
            note="Resolve Riot ID to PUUID first, then fetch TFT match intelligence.",
        )

    if game == "steam":
        if identity.get("steamid"):
            arguments = dict(identity)
            arguments["steamids"] = str(identity["steamid"])
            capabilities = ["steam.player.profile"]
            if include_recent:
                capabilities.append("steam.games.recent")
            if include_history:
                capabilities.append("steam.games.owned")
            return GamingProfilePlan("steam", identity, _calls(capabilities, arguments))
        _require(identity, "vanityurl")
        return GamingProfilePlan(
            "steam",
            identity,
            _calls(["steam.player.resolve"], identity),
            note=(
                "Resolve the vanity name to SteamID64 first; re-run with steamid to fetch public "
                "profile, recent games and visible library/playtime data."
            ),
        )

    if game in {"dota", "dota2", "dota-2"}:
        _require(identity, "account_id")
        capabilities = [
            "dota2.player.profile",
            "dota2.hero.most_used",
            "dota2.stats.winloss",
        ]
        if include_recent:
            capabilities.append("dota2.matches.recent")
        if include_history:
            capabilities.append("dota2.mmr.history")
        return GamingProfilePlan("dota2", identity, _calls(capabilities, identity))

    if game in {"minecraft", "mc"}:
        if identity.get("username"):
            return GamingProfilePlan(
                "minecraft",
                identity,
                _calls(["minecraft.ign.resolve"], identity),
                note="Resolve the UUID first; use the Hypixel preset with that UUID for network stats.",
            )
        _require(identity, "uuid")
        return GamingProfilePlan(
            "minecraft",
            identity,
            _calls(["minecraft.uuid.resolve"], identity),
        )

    if game in {"hypixel", "minecraft-hypixel"}:
        _require(identity, "uuid")
        capabilities = ["hypixel.player.profile"]
        if include_recent:
            capabilities.append("hypixel.matches.recent")
        return GamingProfilePlan("hypixel", identity, _calls(capabilities, identity))

    if game in {"genshin", "genshin-impact"}:
        _require(identity, "uid")
        return GamingProfilePlan(
            "genshin",
            identity,
            _calls(["genshin.player.showcase"], identity),
        )

    if game in {"hsr", "honkai-star-rail", "star-rail"}:
        _require(identity, "uid")
        return GamingProfilePlan(
            "hsr",
            identity,
            _calls(["hsr.player.showcase"], identity),
        )

    if game in {"zzz", "zenless-zone-zero"}:
        _require(identity, "uid")
        return GamingProfilePlan(
            "zzz",
            identity,
            _calls(["zzz.player.showcase"], identity),
        )

    if game == "roblox":
        if identity.get("user_id"):
            return GamingProfilePlan(
                "roblox",
                identity,
                _calls(["roblox.player.profile"], identity),
            )
        _require(identity, "keyword")
        return GamingProfilePlan(
            "roblox",
            identity,
            _calls(["roblox.player.search"], identity),
            note=(
                "Search returns candidate user IDs; profile lookup can follow once the intended "
                "user is resolved."
            ),
        )

    if game in {"osu", "osu!"}:
        _require(identity, "user")
        capabilities = ["osu.player.profile", "osu.scores.best"]
        if include_recent:
            capabilities.extend(["osu.scores.recent", "osu.player.activity"])
        return GamingProfilePlan("osu", identity, _calls(capabilities, identity))

    if game in {"brawlstars", "brawl-stars"}:
        _require(identity, "player_tag")
        capabilities = ["brawlstars.player.profile"]
        if include_recent:
            capabilities.append("brawlstars.matches.recent")
        return GamingProfilePlan("brawlstars", identity, _calls(capabilities, identity))

    if game in {"clashofclans", "clash-of-clans", "coc"}:
        _require(identity, "player_tag")
        capabilities = ["clashofclans.player.profile"]
        if include_history:
            capabilities.append("clashofclans.rank.history")
        return GamingProfilePlan("clashofclans", identity, _calls(capabilities, identity))

    if game in {"clashroyale", "clash-royale", "cr"}:
        _require(identity, "player_tag")
        capabilities = ["clashroyale.player.profile", "clashroyale.progression.chests"]
        if include_recent:
            capabilities.append("clashroyale.matches.recent")
        return GamingProfilePlan("clashroyale", identity, _calls(capabilities, identity))

    raise ValueError(f"unsupported gaming profile preset: {game}")
