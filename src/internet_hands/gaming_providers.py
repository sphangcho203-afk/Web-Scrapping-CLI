from __future__ import annotations

from .catalog_providers import HttpToolSpec, ManifestHttpProvider


def _path(name: str, description: str = "", *, required: bool = True) -> dict[str, object]:
    value: dict[str, object] = {
        "in": "path",
        "required": required,
        "schema": {"type": "string"},
    }
    if description:
        value["description"] = description
    return value


def _query(
    name: str,
    description: str = "",
    *,
    required: bool = False,
    schema: dict[str, object] | None = None,
) -> dict[str, object]:
    value: dict[str, object] = {
        "in": "query",
        "required": required,
        "schema": schema or {"type": "string"},
    }
    if description:
        value["description"] = description
    return value


def build_opendota_provider() -> ManifestHttpProvider:
    base = "https://api.opendota.com/api"
    tools = [
        HttpToolSpec(
            tool_id="player-search",
            name="Dota 2 player search",
            description="Search OpenDota public player records by person name.",
            method="GET",
            base_url=base,
            path="/search",
            parameters={"q": _query("q", "Player/person name", required=True)},
            tags=("gaming", "dota2", "player", "ign", "search"),
            metadata={"source": "OpenDota", "official": False, "read_only": True},
        ),
        HttpToolSpec(
            tool_id="player-profile",
            name="Dota 2 player profile",
            description="Get a public OpenDota player profile and rank/MMR metadata.",
            method="GET",
            base_url=base,
            path="/players/{account_id}",
            parameters={"account_id": _path("account_id", "Steam32/OpenDota account ID")},
            tags=("gaming", "dota2", "player", "profile", "rank", "mmr"),
            metadata={"source": "OpenDota", "official": False, "read_only": True},
        ),
        HttpToolSpec(
            tool_id="player-heroes",
            name="Dota 2 most-used heroes",
            description="Get heroes played by a player with games, wins and usage statistics.",
            method="GET",
            base_url=base,
            path="/players/{account_id}/heroes",
            parameters={"account_id": _path("account_id")},
            tags=("gaming", "dota2", "heroes", "most-used", "mains"),
            metadata={"source": "OpenDota", "official": False, "read_only": True},
        ),
        HttpToolSpec(
            tool_id="player-recent-matches",
            name="Dota 2 recent matches",
            description="Get a player's recent public matches from OpenDota.",
            method="GET",
            base_url=base,
            path="/players/{account_id}/recentMatches",
            parameters={"account_id": _path("account_id")},
            tags=("gaming", "dota2", "matches", "recent"),
            metadata={"source": "OpenDota", "official": False, "read_only": True},
        ),
        HttpToolSpec(
            tool_id="player-win-loss",
            name="Dota 2 win/loss totals",
            description="Get public win/loss totals for an OpenDota player.",
            method="GET",
            base_url=base,
            path="/players/{account_id}/wl",
            parameters={"account_id": _path("account_id")},
            tags=("gaming", "dota2", "wins", "losses", "stats"),
            metadata={"source": "OpenDota", "official": False, "read_only": True},
        ),
        HttpToolSpec(
            tool_id="player-rankings",
            name="Dota 2 hero rankings",
            description="Get a player's public hero ranking rows from OpenDota.",
            method="GET",
            base_url=base,
            path="/players/{account_id}/rankings",
            parameters={"account_id": _path("account_id")},
            tags=("gaming", "dota2", "rankings", "heroes"),
            metadata={"source": "OpenDota", "official": False, "read_only": True},
        ),
        HttpToolSpec(
            tool_id="player-ratings",
            name="Dota 2 rating history",
            description="Get public OpenDota rating/MMR history for a player.",
            method="GET",
            base_url=base,
            path="/players/{account_id}/ratings",
            parameters={"account_id": _path("account_id")},
            tags=("gaming", "dota2", "rating", "mmr", "history"),
            metadata={"source": "OpenDota", "official": False, "read_only": True},
        ),
        HttpToolSpec(
            tool_id="hero-stats",
            name="Dota 2 global hero stats",
            description="Get OpenDota global hero pick/win statistics.",
            method="GET",
            base_url=base,
            path="/heroStats",
            tags=("gaming", "dota2", "heroes", "meta", "stats"),
            metadata={"source": "OpenDota", "official": False, "read_only": True},
        ),
        HttpToolSpec(
            tool_id="hero-item-popularity",
            name="Dota 2 hero item popularity",
            description="Get popular item timings/build choices for a Dota 2 hero.",
            method="GET",
            base_url=base,
            path="/heroes/{hero_id}/itemPopularity",
            parameters={"hero_id": _path("hero_id")},
            tags=("gaming", "dota2", "heroes", "items", "builds", "meta"),
            metadata={"source": "OpenDota", "official": False, "read_only": True},
        ),
    ]
    return ManifestHttpProvider("opendota", tools)


def build_valorant_provider() -> ManifestHttpProvider:
    base = "https://api.henrikdev.xyz"
    auth = {
        "requires_auth": True,
        "auth_env": "HENRIKDEV_API_KEY",
        "auth_header": "Authorization",
    }
    tools = [
        HttpToolSpec(
            tool_id="account",
            name="VALORANT account lookup",
            description="Resolve public VALORANT account data from Riot ID name and tag.",
            method="GET",
            base_url=base,
            path="/valorant/v1/account/{name}/{tag}",
            parameters={
                "name": _path("name", "Riot ID game name"),
                "tag": _path("tag", "Riot ID tag line"),
                "force": _query("force", "Force provider refresh"),
            },
            tags=("gaming", "valorant", "riot-id", "ign", "profile"),
            metadata={"source": "HenrikDev", "official": False, "consent_required": True},
            **auth,
        ),
        HttpToolSpec(
            tool_id="mmr",
            name="VALORANT rank and MMR",
            description="Get public/community rank and MMR information for a VALORANT Riot ID.",
            method="GET",
            base_url=base,
            path="/valorant/{version}/mmr/{region}/{name}/{tag}",
            parameters={
                "version": _path("version", "Henrik API MMR version, e.g. v2"),
                "region": _path("region", "VALORANT region such as na, eu, ap, kr"),
                "name": _path("name"),
                "tag": _path("tag"),
                "filter": _query("filter"),
            },
            tags=("gaming", "valorant", "rank", "mmr", "rating"),
            metadata={"source": "HenrikDev", "official": False, "consent_required": True},
            **auth,
        ),
        HttpToolSpec(
            tool_id="mmr-history",
            name="VALORANT MMR history",
            description="Get recent VALORANT MMR/rank history for a Riot ID.",
            method="GET",
            base_url=base,
            path="/valorant/v1/mmr-history/{region}/{name}/{tag}",
            parameters={
                "region": _path("region"),
                "name": _path("name"),
                "tag": _path("tag"),
            },
            tags=("gaming", "valorant", "rank", "mmr", "history"),
            metadata={"source": "HenrikDev", "official": False, "consent_required": True},
            **auth,
        ),
        HttpToolSpec(
            tool_id="lifetime-mmr-history",
            name="VALORANT lifetime MMR history",
            description="Get paged lifetime community MMR history for a VALORANT Riot ID.",
            method="GET",
            base_url=base,
            path="/valorant/v1/lifetime/mmr-history/{region}/{name}/{tag}",
            parameters={
                "region": _path("region"),
                "name": _path("name"),
                "tag": _path("tag"),
                "page": _query("page", schema={"type": "integer", "minimum": 1}),
                "size": _query("size", schema={"type": "integer", "minimum": 1, "maximum": 100}),
            },
            tags=("gaming", "valorant", "rank", "mmr", "lifetime", "history"),
            metadata={"source": "HenrikDev", "official": False, "consent_required": True},
            **auth,
        ),
        HttpToolSpec(
            tool_id="matches",
            name="VALORANT match history",
            description="Get recent VALORANT matches for a Riot ID with optional map/mode filters.",
            method="GET",
            base_url=base,
            path="/valorant/v3/matches/{region}/{name}/{tag}",
            parameters={
                "region": _path("region"),
                "name": _path("name"),
                "tag": _path("tag"),
                "filter": _query("filter", "Queue/mode filter"),
                "map": _query("map", "Map filter"),
                "size": _query("size", schema={"type": "integer", "minimum": 1, "maximum": 100}),
            },
            tags=("gaming", "valorant", "matches", "history", "agents"),
            metadata={"source": "HenrikDev", "official": False, "consent_required": True},
            **auth,
        ),
        HttpToolSpec(
            tool_id="leaderboard",
            name="VALORANT ranked leaderboard",
            description="Get a regional VALORANT leaderboard with optional Riot ID/season filtering.",
            method="GET",
            base_url=base,
            path="/valorant/{version}/leaderboard/{region}",
            parameters={
                "version": _path("version", "Henrik leaderboard API version"),
                "region": _path("region"),
                "start": _query("start", schema={"type": "integer", "minimum": 0}),
                "end": _query("end", schema={"type": "integer", "minimum": 1}),
                "name": _query("name"),
                "tag": _query("tag"),
                "puuid": _query("puuid"),
                "season": _query("season"),
            },
            tags=("gaming", "valorant", "leaderboard", "rank", "radiant"),
            metadata={"source": "HenrikDev", "official": False, "consent_required": True},
            **auth,
        ),
    ]
    return ManifestHttpProvider("valorant", tools)


def build_enka_provider() -> ManifestHttpProvider:
    base = "https://enka.network/api"
    tools = [
        HttpToolSpec(
            tool_id="genshin-showcase",
            name="Genshin Impact public showcase",
            description="Get public Genshin profile and showcased character/build information by UID.",
            method="GET",
            base_url=base,
            path="/uid/{uid}/",
            parameters={"uid": _path("uid", "Genshin UID")},
            tags=("gaming", "genshin", "profile", "characters", "showcase", "builds"),
            metadata={"source": "Enka.Network", "official": False, "public_showcase_only": True},
        ),
        HttpToolSpec(
            tool_id="hsr-showcase",
            name="Honkai Star Rail public showcase",
            description="Get public Honkai: Star Rail profile/showcase information by UID.",
            method="GET",
            base_url=base,
            path="/hsr/uid/{uid}/",
            parameters={"uid": _path("uid", "Honkai: Star Rail UID")},
            tags=("gaming", "hsr", "honkai-star-rail", "profile", "characters", "showcase"),
            metadata={"source": "Enka.Network", "official": False, "public_showcase_only": True},
        ),
        HttpToolSpec(
            tool_id="zzz-showcase",
            name="Zenless Zone Zero public showcase",
            description="Get public Zenless Zone Zero profile, medals/titles and showcased agents by UID.",
            method="GET",
            base_url=base,
            path="/zzz/uid/{uid}/",
            parameters={"uid": _path("uid", "Zenless Zone Zero UID")},
            tags=("gaming", "zzz", "zenless-zone-zero", "profile", "agents", "titles", "badges"),
            metadata={"source": "Enka.Network", "official": False, "public_showcase_only": True},
        ),
    ]
    return ManifestHttpProvider("enka", tools)


def build_mojang_provider() -> ManifestHttpProvider:
    tools = [
        HttpToolSpec(
            tool_id="username-to-uuid",
            name="Minecraft IGN to UUID",
            description="Resolve a current Minecraft Java username to its public UUID.",
            method="GET",
            base_url="https://api.mojang.com",
            path="/users/profiles/minecraft/{username}",
            parameters={"username": _path("username", "Minecraft Java username")},
            tags=("gaming", "minecraft", "ign", "username", "uuid", "lookup"),
            metadata={"source": "Mojang public API", "official": True, "read_only": True},
        ),
        HttpToolSpec(
            tool_id="uuid-to-username",
            name="Minecraft UUID to IGN",
            description="Resolve a Minecraft Java UUID to the current public username.",
            method="GET",
            base_url="https://api.mojang.com",
            path="/user/profile/{uuid}",
            parameters={"uuid": _path("uuid", "Minecraft UUID, with or without dashes")},
            tags=("gaming", "minecraft", "uuid", "ign", "username", "lookup"),
            metadata={"source": "Mojang public API", "official": True, "read_only": True},
        ),
    ]
    return ManifestHttpProvider("mojang", tools)


def build_hypixel_provider() -> ManifestHttpProvider:
    base = "https://api.hypixel.net"
    auth = {
        "requires_auth": True,
        "auth_env": "HYPIXEL_API_KEY",
        "auth_header": "API-Key",
    }
    tools = [
        HttpToolSpec(
            tool_id="player",
            name="Hypixel player profile and stats",
            description="Get a Hypixel player's public network profile and per-game stats by UUID.",
            method="GET",
            base_url=base,
            path="/v2/player",
            parameters={"uuid": _query("uuid", "Minecraft UUID", required=True)},
            tags=("gaming", "minecraft", "hypixel", "player", "profile", "stats", "titles"),
            metadata={"source": "Hypixel Public API", "official": True},
            **auth,
        ),
        HttpToolSpec(
            tool_id="recent-games",
            name="Hypixel recent games",
            description="Get recently played Hypixel games for a player UUID.",
            method="GET",
            base_url=base,
            path="/v2/recentgames",
            parameters={"uuid": _query("uuid", "Minecraft UUID", required=True)},
            tags=("gaming", "minecraft", "hypixel", "recent", "matches", "games"),
            metadata={"source": "Hypixel Public API", "official": True},
            **auth,
        ),
        HttpToolSpec(
            tool_id="leaderboards",
            name="Hypixel leaderboards",
            description="Get Hypixel public network leaderboards.",
            method="GET",
            base_url=base,
            path="/v2/leaderboards",
            tags=("gaming", "minecraft", "hypixel", "leaderboards", "rankings"),
            metadata={"source": "Hypixel Public API", "official": True},
            **auth,
        ),
        HttpToolSpec(
            tool_id="skyblock-profiles",
            name="Hypixel SkyBlock profiles",
            description="Get public SkyBlock profiles for a Minecraft UUID.",
            method="GET",
            base_url=base,
            path="/v2/skyblock/profiles",
            parameters={"uuid": _query("uuid", "Minecraft UUID", required=True)},
            tags=("gaming", "minecraft", "hypixel", "skyblock", "profile", "stats"),
            metadata={"source": "Hypixel Public API", "official": True},
            **auth,
        ),
    ]
    return ManifestHttpProvider("hypixel", tools)


def build_roblox_provider() -> ManifestHttpProvider:
    tools = [
        HttpToolSpec(
            tool_id="user-search",
            name="Roblox public user search",
            description="Search public Roblox users by username/display-name keyword.",
            method="GET",
            base_url="https://users.roblox.com",
            path="/v1/users/search",
            parameters={
                "keyword": _query("keyword", "Username or display-name keyword", required=True),
                "limit": _query(
                    "limit",
                    schema={"type": "integer", "enum": [10, 25, 50, 100]},
                ),
                "cursor": _query("cursor"),
            },
            tags=("gaming", "roblox", "player", "username", "ign", "search"),
            metadata={"source": "Roblox public API", "official": True, "read_only": True},
        ),
        HttpToolSpec(
            tool_id="user-profile",
            name="Roblox public user profile",
            description="Get public Roblox account/profile information by numeric user ID.",
            method="GET",
            base_url="https://users.roblox.com",
            path="/v1/users/{user_id}",
            parameters={"user_id": _path("user_id", "Roblox numeric user ID")},
            tags=("gaming", "roblox", "player", "profile", "account"),
            metadata={"source": "Roblox public API", "official": True, "read_only": True},
        ),
    ]
    return ManifestHttpProvider("roblox", tools)


def build_osu_provider() -> ManifestHttpProvider:
    base = "https://osu.ppy.sh/api/v2"
    auth = {
        "requires_auth": True,
        "auth_env": "OSU_AUTHORIZATION",
        "auth_header": "Authorization",
    }
    tools = [
        HttpToolSpec(
            tool_id="user-profile",
            name="osu! player profile",
            description="Get an osu! player's public profile/statistics by id or @username.",
            method="GET",
            base_url=base,
            path="/users/{user}",
            parameters={
                "user": _path("user", "User ID or @username"),
                "key": _query("key", "Lookup key hint, e.g. username or id"),
            },
            tags=("gaming", "osu", "player", "profile", "rank", "performance-points"),
            metadata={"source": "osu!api v2", "official": True},
            **auth,
        ),
        HttpToolSpec(
            tool_id="user-scores",
            name="osu! player scores",
            description="Get best, first-place, or recent public scores for an osu! player.",
            method="GET",
            base_url=base,
            path="/users/{user}/scores/{type}",
            parameters={
                "user": _path("user", "User ID"),
                "type": {
                    "in": "path",
                    "required": True,
                    "schema": {"type": "string", "enum": ["best", "firsts", "recent"]},
                },
                "mode": _query("mode", "osu, taiko, fruits, or mania"),
                "limit": _query(
                    "limit",
                    schema={"type": "integer", "minimum": 1, "maximum": 100},
                ),
                "offset": _query("offset", schema={"type": "integer", "minimum": 0}),
                "include_fails": _query("include_fails"),
            },
            tags=("gaming", "osu", "scores", "best", "recent", "rank"),
            metadata={"source": "osu!api v2", "official": True},
            **auth,
        ),
        HttpToolSpec(
            tool_id="recent-activity",
            name="osu! recent activity",
            description="Get recent public activity/events for an osu! player.",
            method="GET",
            base_url=base,
            path="/users/{user}/recent_activity",
            parameters={
                "user": _path("user", "User ID"),
                "limit": _query(
                    "limit",
                    schema={"type": "integer", "minimum": 1, "maximum": 50},
                ),
                "offset": _query("offset", schema={"type": "integer", "minimum": 0}),
            },
            tags=("gaming", "osu", "activity", "recent", "achievements"),
            metadata={"source": "osu!api v2", "official": True},
            **auth,
        ),
    ]
    return ManifestHttpProvider("osu", tools)


def _supercell_auth(env_name: str) -> dict[str, object]:
    return {
        "requires_auth": True,
        "auth_env": env_name,
        "auth_header": "Authorization",
    }


def build_brawlstars_provider() -> ManifestHttpProvider:
    base = "https://api.brawlstars.com/v1"
    auth = _supercell_auth("BRAWL_STARS_AUTHORIZATION")
    tools = [
        HttpToolSpec(
            tool_id="player",
            name="Brawl Stars player profile",
            description="Get a Brawl Stars player's public profile, trophies and brawler progression by tag.",
            method="GET",
            base_url=base,
            path="/players/{player_tag}",
            parameters={"player_tag": _path("player_tag", "Player tag including #")},
            tags=("gaming", "brawl-stars", "player", "profile", "trophies", "brawlers"),
            metadata={"source": "Brawl Stars API", "official": True},
            **auth,
        ),
        HttpToolSpec(
            tool_id="battlelog",
            name="Brawl Stars battle log",
            description="Get recent public Brawl Stars battle results for a player tag.",
            method="GET",
            base_url=base,
            path="/players/{player_tag}/battlelog",
            parameters={"player_tag": _path("player_tag", "Player tag including #")},
            tags=("gaming", "brawl-stars", "matches", "battlelog", "recent"),
            metadata={"source": "Brawl Stars API", "official": True},
            **auth,
        ),
        HttpToolSpec(
            tool_id="brawlers",
            name="Brawl Stars brawler reference",
            description="Get the official Brawl Stars brawler reference catalog.",
            method="GET",
            base_url=base,
            path="/brawlers",
            parameters={"limit": _query("limit"), "after": _query("after"), "before": _query("before")},
            tags=("gaming", "brawl-stars", "brawlers", "heroes", "reference"),
            metadata={"source": "Brawl Stars API", "official": True},
            **auth,
        ),
    ]
    return ManifestHttpProvider("brawlstars", tools)


def build_clashofclans_provider() -> ManifestHttpProvider:
    base = "https://api.clashofclans.com/v1"
    auth = _supercell_auth("CLASH_OF_CLANS_AUTHORIZATION")
    tools = [
        HttpToolSpec(
            tool_id="player",
            name="Clash of Clans player profile",
            description="Get a Clash of Clans player's public profile, league, heroes, troops and achievements.",
            method="GET",
            base_url=base,
            path="/players/{player_tag}",
            parameters={"player_tag": _path("player_tag", "Player tag including #")},
            tags=("gaming", "clash-of-clans", "player", "profile", "league", "heroes", "achievements"),
            metadata={"source": "Clash of Clans API", "official": True},
            **auth,
        ),
        HttpToolSpec(
            tool_id="league-history",
            name="Clash of Clans league history",
            description="Get a player's public league/ranked history where available in the official API.",
            method="GET",
            base_url=base,
            path="/players/{player_tag}/leaguehistory",
            parameters={"player_tag": _path("player_tag", "Player tag including #")},
            tags=("gaming", "clash-of-clans", "player", "league", "rank", "history"),
            metadata={"source": "Clash of Clans API", "official": True},
            **auth,
        ),
    ]
    return ManifestHttpProvider("clashofclans", tools)


def build_clashroyale_provider() -> ManifestHttpProvider:
    base = "https://api.clashroyale.com/v1"
    auth = _supercell_auth("CLASH_ROYALE_AUTHORIZATION")
    tools = [
        HttpToolSpec(
            tool_id="player",
            name="Clash Royale player profile",
            description="Get a Clash Royale player's public profile, trophies, arena, cards and achievements.",
            method="GET",
            base_url=base,
            path="/players/{player_tag}",
            parameters={"player_tag": _path("player_tag", "Player tag including #")},
            tags=("gaming", "clash-royale", "player", "profile", "trophies", "cards"),
            metadata={"source": "Clash Royale API", "official": True},
            **auth,
        ),
        HttpToolSpec(
            tool_id="battlelog",
            name="Clash Royale battle log",
            description="Get a Clash Royale player's recent public battles.",
            method="GET",
            base_url=base,
            path="/players/{player_tag}/battlelog",
            parameters={"player_tag": _path("player_tag", "Player tag including #")},
            tags=("gaming", "clash-royale", "matches", "battlelog", "recent"),
            metadata={"source": "Clash Royale API", "official": True},
            **auth,
        ),
        HttpToolSpec(
            tool_id="upcoming-chests",
            name="Clash Royale upcoming chests",
            description="Get the public upcoming chest cycle for a Clash Royale player.",
            method="GET",
            base_url=base,
            path="/players/{player_tag}/upcomingchests",
            parameters={"player_tag": _path("player_tag", "Player tag including #")},
            tags=("gaming", "clash-royale", "player", "chests", "progression"),
            metadata={"source": "Clash Royale API", "official": True},
            **auth,
        ),
    ]
    return ManifestHttpProvider("clashroyale", tools)


def build_gaming_providers() -> list[ManifestHttpProvider]:
    return [
        build_opendota_provider(),
        build_valorant_provider(),
        build_enka_provider(),
        build_mojang_provider(),
        build_hypixel_provider(),
        build_roblox_provider(),
        build_osu_provider(),
        build_brawlstars_provider(),
        build_clashofclans_provider(),
        build_clashroyale_provider(),
    ]
