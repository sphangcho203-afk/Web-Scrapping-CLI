from __future__ import annotations

from .capability_packs import Capability, CapabilityCandidate


def _candidate(
    provider: str,
    ref: str,
    *,
    priority: int = 10,
    argument_map: dict[str, str] | None = None,
    defaults: dict[str, object] | None = None,
    note: str = "",
) -> CapabilityCandidate:
    return CapabilityCandidate(
        provider=provider,
        ref=ref,
        priority=priority,
        argument_map=argument_map or {},
        defaults=defaults or {},
        note=note,
    )


def _mlbb_capabilities() -> list[Capability]:
    return [
        Capability(
            id="mlbb.reference.heroes", name="MLBB hero reference search",
            description="Search a bundled historical hero snapshot by name, role or lane. No upstream API key needed.",
            pack="mlbb", tags=("gaming", "mlbb", "heroes", "offline", "reference"),
            candidates=(_candidate("gamecore", "gamecore:mlbb-heroes"),),
            input_schema={"type": "object", "properties": {"query": {"type": "string"}, "limit": {"type": "integer"}}},
        ),
        Capability(
            id="mlbb.reference.hero", name="MLBB hero detail",
            description="Find a historical hero's role, lanes, synergies and counters in bundled data.",
            pack="mlbb", tags=("gaming", "mlbb", "hero", "offline", "reference"),
            candidates=(_candidate("gamecore", "gamecore:mlbb-hero"),),
            input_schema={"type": "object", "required": ["hero"], "properties": {"hero": {"type": "string"}}},
        ),
        Capability(
            id="mlbb.reference.items", name="MLBB item reference search",
            description="Search historical item names, categories, cost and modifiers in bundled data.",
            pack="mlbb", tags=("gaming", "mlbb", "items", "offline", "reference"),
            candidates=(_candidate("gamecore", "gamecore:mlbb-items"),),
            input_schema={"type": "object", "properties": {"query": {"type": "string"}, "limit": {"type": "integer"}}},
        ),
        Capability(
            id="mlbb.rank.current",
            name="MLBB current rank intelligence",
            description="Retrieve the detailed community MLBB profile payload containing current rank/MMR-style rank fields where the provider exposes them.",
            pack="mlbb",
            tags=("gaming", "mlbb", "rank", "profile", "mmr"),
            candidates=(
                _candidate(
                    "rapidapi",
                    "rapidapi:mlbb-player-lookup",
                    note="Uses the configured RapidAPI MLBB lookup and returns its full public/community player payload.",
                ),
            ),
        ),
        Capability(
            id="mlbb.rank.highest",
            name="MLBB highest rank intelligence",
            description="Retrieve the MLBB profile payload used to inspect current/highest rank information.",
            pack="mlbb",
            tags=("gaming", "mlbb", "highest-rank", "rank", "profile"),
            candidates=(_candidate("rapidapi", "rapidapi:mlbb-player-lookup"),),
        ),
        Capability(
            id="mlbb.hero.history",
            name="MLBB hero history",
            description="Retrieve MLBB public/community profile data including hero-history fields exposed by the configured lookup provider.",
            pack="mlbb",
            tags=("gaming", "mlbb", "heroes", "most-used", "mains", "history"),
            candidates=(_candidate("rapidapi", "rapidapi:mlbb-player-lookup"),),
        ),
        Capability(
            id="mlbb.collector.profile",
            name="MLBB collector and skin profile",
            description="Retrieve MLBB profile data containing collector level/points, skin counts and related public account metadata where available.",
            pack="mlbb",
            tags=("gaming", "mlbb", "collector", "skins", "profile"),
            candidates=(_candidate("rapidapi", "rapidapi:mlbb-player-lookup"),),
        ),
        Capability(
            id="mlbb.squad.profile",
            name="MLBB squad profile",
            description="Retrieve the MLBB player payload containing squad information where exposed by the configured community provider.",
            pack="mlbb",
            tags=("gaming", "mlbb", "squad", "team", "profile"),
            candidates=(_candidate("rapidapi", "rapidapi:mlbb-player-lookup"),),
        ),
    ]


def _valorant_capabilities() -> list[Capability]:
    return [
        Capability(
            id="valorant.account.lookup",
            name="VALORANT Riot ID lookup",
            description="Resolve a public VALORANT account/profile from Riot ID name and tag.",
            pack="valorant",
            tags=("gaming", "valorant", "riot-id", "ign", "profile"),
            candidates=(_candidate("valorant", "valorant:account"),),
        ),
        Capability(
            id="valorant.rank.mmr",
            name="VALORANT rank and MMR",
            description="Retrieve current community rank/MMR information for a VALORANT player.",
            pack="valorant",
            tags=("gaming", "valorant", "rank", "mmr", "rating"),
            candidates=(
                _candidate(
                    "valorant",
                    "valorant:mmr",
                    defaults={"version": "v2"},
                    note="HenrikDev requires player consent for user-data use; public store checking is intentionally not included.",
                ),
            ),
        ),
        Capability(
            id="valorant.rank.history",
            name="VALORANT rank history",
            description="Retrieve recent community VALORANT MMR/rank changes.",
            pack="valorant",
            tags=("gaming", "valorant", "rank", "mmr", "history"),
            candidates=(_candidate("valorant", "valorant:mmr-history"),),
        ),
        Capability(
            id="valorant.rank.lifetime",
            name="VALORANT lifetime rank history",
            description="Retrieve paginated lifetime community rank/MMR history for a VALORANT Riot ID.",
            pack="valorant",
            tags=("gaming", "valorant", "rank", "mmr", "lifetime", "history"),
            candidates=(_candidate("valorant", "valorant:lifetime-mmr-history"),),
        ),
        Capability(
            id="valorant.matches.recent",
            name="VALORANT recent matches",
            description="Retrieve recent VALORANT matches for a Riot ID; match payloads can be used to infer agents used and recent performance.",
            pack="valorant",
            tags=("gaming", "valorant", "matches", "agents", "most-used", "performance"),
            candidates=(_candidate("valorant", "valorant:matches"),),
        ),
        Capability(
            id="valorant.leaderboard",
            name="VALORANT regional leaderboard",
            description="Retrieve a VALORANT regional ranked leaderboard with optional player/season filtering.",
            pack="valorant",
            tags=("gaming", "valorant", "leaderboard", "rank", "radiant"),
            candidates=(
                _candidate(
                    "valorant",
                    "valorant:leaderboard",
                    defaults={"version": "v2"},
                ),
            ),
        ),
    ]


def _dota_capabilities() -> list[Capability]:
    return [
        Capability(
            id="dota2.player.search",
            name="Dota 2 player/IGN search",
            description="Search OpenDota public player records by person name and obtain an account ID.",
            pack="dota2",
            tags=("gaming", "dota2", "player", "ign", "search"),
            candidates=(_candidate("opendota", "opendota:player-search"),),
        ),
        Capability(
            id="dota2.player.profile",
            name="Dota 2 player profile",
            description="Retrieve public OpenDota profile and rank/MMR metadata for an account ID.",
            pack="dota2",
            tags=("gaming", "dota2", "profile", "rank", "mmr"),
            candidates=(_candidate("opendota", "opendota:player-profile"),),
        ),
        Capability(
            id="dota2.hero.most_used",
            name="Dota 2 most-used heroes",
            description="Return hero usage and win statistics for a Dota 2 player, suitable for identifying mains/most-used heroes.",
            pack="dota2",
            tags=("gaming", "dota2", "heroes", "mains", "most-used"),
            candidates=(_candidate("opendota", "opendota:player-heroes"),),
        ),
        Capability(
            id="dota2.matches.recent",
            name="Dota 2 recent matches",
            description="Retrieve recent public Dota 2 matches for a player.",
            pack="dota2",
            tags=("gaming", "dota2", "matches", "recent", "performance"),
            candidates=(_candidate("opendota", "opendota:player-recent-matches"),),
        ),
        Capability(
            id="dota2.stats.winloss",
            name="Dota 2 win/loss totals",
            description="Retrieve public win/loss totals for a Dota 2 player.",
            pack="dota2",
            tags=("gaming", "dota2", "wins", "losses", "stats"),
            candidates=(_candidate("opendota", "opendota:player-win-loss"),),
        ),
        Capability(
            id="dota2.rankings.heroes",
            name="Dota 2 hero rankings",
            description="Retrieve a player's public OpenDota hero ranking rows.",
            pack="dota2",
            tags=("gaming", "dota2", "heroes", "rankings"),
            candidates=(_candidate("opendota", "opendota:player-rankings"),),
        ),
        Capability(
            id="dota2.mmr.history",
            name="Dota 2 rating/MMR history",
            description="Retrieve public rating history for a Dota 2 player.",
            pack="dota2",
            tags=("gaming", "dota2", "rating", "mmr", "history"),
            candidates=(_candidate("opendota", "opendota:player-ratings"),),
        ),
        Capability(
            id="dota2.meta.heroes",
            name="Dota 2 global hero meta",
            description="Retrieve global hero pick/win statistics from OpenDota.",
            pack="dota2",
            tags=("gaming", "dota2", "heroes", "meta", "stats"),
            candidates=(_candidate("opendota", "opendota:hero-stats"),),
        ),
        Capability(
            id="dota2.meta.items",
            name="Dota 2 hero item popularity",
            description="Retrieve popular item/build data for a specific Dota 2 hero.",
            pack="dota2",
            tags=("gaming", "dota2", "items", "builds", "hero", "meta"),
            candidates=(_candidate("opendota", "opendota:hero-item-popularity"),),
        ),
    ]


def _minecraft_capabilities() -> list[Capability]:
    return [
        Capability(
            id="minecraft.ign.resolve",
            name="Minecraft IGN lookup",
            description="Resolve a Minecraft Java username to the current public UUID.",
            pack="minecraft",
            tags=("gaming", "minecraft", "ign", "username", "uuid"),
            candidates=(_candidate("mojang", "mojang:username-to-uuid"),),
        ),
        Capability(
            id="minecraft.uuid.resolve",
            name="Minecraft UUID lookup",
            description="Resolve a Minecraft Java UUID to the current public username.",
            pack="minecraft",
            tags=("gaming", "minecraft", "uuid", "ign", "username"),
            candidates=(_candidate("mojang", "mojang:uuid-to-username"),),
        ),
        Capability(
            id="hypixel.player.profile",
            name="Hypixel player intelligence",
            description="Retrieve public Hypixel network/player stats including game-specific stats, rank/title fields and account activity where exposed.",
            pack="hypixel",
            tags=("gaming", "minecraft", "hypixel", "profile", "stats", "titles"),
            candidates=(_candidate("hypixel", "hypixel:player"),),
        ),
        Capability(
            id="hypixel.matches.recent",
            name="Hypixel recent games",
            description="Retrieve the recently played Hypixel games for a Minecraft UUID.",
            pack="hypixel",
            tags=("gaming", "minecraft", "hypixel", "recent", "games"),
            candidates=(_candidate("hypixel", "hypixel:recent-games"),),
        ),
        Capability(
            id="hypixel.leaderboards",
            name="Hypixel leaderboards",
            description="Retrieve public Hypixel leaderboards and rankings.",
            pack="hypixel",
            tags=("gaming", "minecraft", "hypixel", "leaderboards", "rankings"),
            candidates=(_candidate("hypixel", "hypixel:leaderboards"),),
        ),
        Capability(
            id="hypixel.skyblock.profile",
            name="Hypixel SkyBlock player profiles",
            description="Retrieve public SkyBlock profile data for a Minecraft UUID.",
            pack="hypixel",
            tags=("gaming", "minecraft", "hypixel", "skyblock", "profile", "stats"),
            candidates=(_candidate("hypixel", "hypixel:skyblock-profiles"),),
        ),
    ]


def _hoyo_capabilities() -> list[Capability]:
    return [
        Capability(
            id="genshin.player.showcase",
            name="Genshin public profile/showcase",
            description="Retrieve public Genshin player info and showcased characters/builds by UID.",
            pack="genshin",
            tags=("gaming", "genshin", "profile", "characters", "builds", "showcase"),
            candidates=(_candidate("enka", "enka:genshin-showcase"),),
        ),
        Capability(
            id="hsr.player.showcase",
            name="Honkai Star Rail public profile/showcase",
            description="Retrieve public Honkai: Star Rail player/showcase information by UID.",
            pack="hsr",
            tags=("gaming", "hsr", "honkai-star-rail", "profile", "characters", "showcase"),
            candidates=(_candidate("enka", "enka:hsr-showcase"),),
        ),
        Capability(
            id="zzz.player.showcase",
            name="Zenless Zone Zero public profile/showcase",
            description="Retrieve public ZZZ profile, title/medal and showcased-agent data by UID.",
            pack="zzz",
            tags=("gaming", "zzz", "zenless-zone-zero", "profile", "agents", "titles", "badges"),
            candidates=(_candidate("enka", "enka:zzz-showcase"),),
        ),
    ]


def _roblox_capabilities() -> list[Capability]:
    return [
        Capability(
            id="roblox.player.search",
            name="Roblox player search",
            description="Search public Roblox user records by username/display-name keyword.",
            pack="roblox",
            tags=("gaming", "roblox", "player", "ign", "username", "search"),
            candidates=(_candidate("roblox", "roblox:user-search"),),
        ),
        Capability(
            id="roblox.player.profile",
            name="Roblox public player profile",
            description="Retrieve public Roblox account/profile information by numeric user ID.",
            pack="roblox",
            tags=("gaming", "roblox", "player", "profile", "account"),
            candidates=(_candidate("roblox", "roblox:user-profile"),),
        ),
    ]


def _osu_capabilities() -> list[Capability]:
    return [
        Capability(
            id="osu.player.profile",
            name="osu! player profile",
            description="Retrieve public osu! profile/statistics including global/country ranks and performance data.",
            pack="osu",
            tags=("gaming", "osu", "profile", "rank", "pp"),
            candidates=(_candidate("osu", "osu:user-profile"),),
        ),
        Capability(
            id="osu.scores.best",
            name="osu! best scores",
            description="Retrieve a player's public best scores.",
            pack="osu",
            tags=("gaming", "osu", "scores", "best", "performance"),
            candidates=(
                _candidate("osu", "osu:user-scores", defaults={"type": "best"}),
            ),
        ),
        Capability(
            id="osu.scores.recent",
            name="osu! recent scores",
            description="Retrieve a player's public recent scores.",
            pack="osu",
            tags=("gaming", "osu", "scores", "recent", "performance"),
            candidates=(
                _candidate("osu", "osu:user-scores", defaults={"type": "recent"}),
            ),
        ),
        Capability(
            id="osu.player.activity",
            name="osu! recent player activity",
            description="Retrieve recent public profile activity/achievement-style events.",
            pack="osu",
            tags=("gaming", "osu", "activity", "recent", "achievements"),
            candidates=(_candidate("osu", "osu:recent-activity"),),
        ),
    ]


def _supercell_capabilities() -> list[Capability]:
    return [
        Capability(
            id="brawlstars.player.profile",
            name="Brawl Stars player profile",
            description="Retrieve public Brawl Stars player data, trophies and brawler progression by player tag.",
            pack="brawlstars",
            tags=("gaming", "brawl-stars", "profile", "trophies", "brawlers"),
            candidates=(_candidate("brawlstars", "brawlstars:player"),),
        ),
        Capability(
            id="brawlstars.matches.recent",
            name="Brawl Stars recent battles",
            description="Retrieve recent public Brawl Stars battle results for a player tag.",
            pack="brawlstars",
            tags=("gaming", "brawl-stars", "battlelog", "matches", "recent"),
            candidates=(_candidate("brawlstars", "brawlstars:battlelog"),),
        ),
        Capability(
            id="brawlstars.brawlers.reference",
            name="Brawl Stars brawler catalog",
            description="Retrieve the official brawler reference catalog.",
            pack="brawlstars",
            tags=("gaming", "brawl-stars", "brawlers", "heroes", "reference"),
            candidates=(_candidate("brawlstars", "brawlstars:brawlers"),),
        ),
        Capability(
            id="clashofclans.player.profile",
            name="Clash of Clans player profile",
            description="Retrieve public CoC player profile data including league, heroes, troops and achievements.",
            pack="clashofclans",
            tags=("gaming", "clash-of-clans", "profile", "league", "heroes", "achievements"),
            candidates=(_candidate("clashofclans", "clashofclans:player"),),
        ),
        Capability(
            id="clashofclans.rank.history",
            name="Clash of Clans league history",
            description="Retrieve public player league/rank history where available in the official API.",
            pack="clashofclans",
            tags=("gaming", "clash-of-clans", "league", "rank", "history"),
            candidates=(_candidate("clashofclans", "clashofclans:league-history"),),
        ),
        Capability(
            id="clashroyale.player.profile",
            name="Clash Royale player profile",
            description="Retrieve public Clash Royale profile, trophies, arena and cards by player tag.",
            pack="clashroyale",
            tags=("gaming", "clash-royale", "profile", "trophies", "cards"),
            candidates=(_candidate("clashroyale", "clashroyale:player"),),
        ),
        Capability(
            id="clashroyale.matches.recent",
            name="Clash Royale recent battles",
            description="Retrieve recent public Clash Royale battles for a player tag.",
            pack="clashroyale",
            tags=("gaming", "clash-royale", "battlelog", "matches", "recent"),
            candidates=(_candidate("clashroyale", "clashroyale:battlelog"),),
        ),
        Capability(
            id="clashroyale.progression.chests",
            name="Clash Royale upcoming chests",
            description="Retrieve the public upcoming chest cycle for a player.",
            pack="clashroyale",
            tags=("gaming", "clash-royale", "progression", "chests"),
            candidates=(_candidate("clashroyale", "clashroyale:upcoming-chests"),),
        ),
    ]


def build_gaming_capabilities() -> list[Capability]:
    return [
        Capability(
            id="game.matches.analyze", name="Analyze your match results",
            description="Calculate win rate, streak, recent form, hero usage and KDA from supplied games. Works for every game without a provider API.",
            pack="gaming-common", tags=("gaming", "matches", "analytics", "offline"),
            candidates=(_candidate("gamecore", "gamecore:match-analysis"),),
            input_schema={"type": "object", "required": ["game", "matches"], "properties": {
                "game": {"type": "string"}, "matches": {"type": "array", "items": {"type": "object"}}}},
        ),
        *_mlbb_capabilities(),
        *_valorant_capabilities(),
        *_dota_capabilities(),
        *_minecraft_capabilities(),
        *_hoyo_capabilities(),
        *_roblox_capabilities(),
        *_osu_capabilities(),
        *_supercell_capabilities(),
        Capability(
            id="league.reference.champions", name="League champion reference",
            description="Search Riot's published Data Dragon champions and roles. No Riot API key needed.",
            pack="league", tags=("gaming", "league", "champions", "riot", "reference"),
            candidates=(_candidate("gamecore", "gamecore:league-champions"),),
            input_schema={"type": "object", "properties": {"query": {"type": "string"}}},
        ),
        Capability(
            id="league.reference.items", name="League item reference",
            description="Search Riot's published Data Dragon item names, prices and stats. No Riot API key needed.",
            pack="league", tags=("gaming", "league", "items", "riot", "reference"),
            candidates=(_candidate("gamecore", "gamecore:league-items"),),
            input_schema={"type": "object", "properties": {"query": {"type": "string"}}},
        ),
    ]
