from __future__ import annotations

from .capability_packs import Capability, CapabilityCandidate


def _candidate(
    provider: str,
    ref: str,
    *,
    priority: int = 10,
    defaults: dict[str, object] | None = None,
    note: str = "",
) -> CapabilityCandidate:
    return CapabilityCandidate(
        provider=provider,
        ref=ref,
        priority=priority,
        defaults=defaults or {},
        note=note,
    )


def build_extra_gaming_capabilities() -> list[Capability]:
    return [
        Capability(
            id="steam.player.resolve",
            name="Steam vanity/IGN lookup",
            description="Resolve a public Steam vanity profile name to SteamID64.",
            pack="steam",
            tags=("gaming", "steam", "ign", "vanity", "steamid", "lookup"),
            candidates=(_candidate("steam", "steam:resolve-vanity"),),
        ),
        Capability(
            id="steam.player.profile",
            name="Steam public player profile",
            description="Retrieve public Steam persona/profile summaries for SteamID64 values.",
            pack="steam",
            tags=("gaming", "steam", "player", "profile", "persona"),
            candidates=(_candidate("steam", "steam:player-summaries"),),
        ),
        Capability(
            id="steam.games.recent",
            name="Steam recently played games",
            description="Retrieve recent public game/playtime information for a Steam profile.",
            pack="steam",
            tags=("gaming", "steam", "games", "recent", "playtime"),
            candidates=(_candidate("steam", "steam:recent-games"),),
        ),
        Capability(
            id="steam.games.owned",
            name="Steam public game library",
            description="Retrieve public owned-game/playtime data when the player's game details are visible.",
            pack="steam",
            tags=("gaming", "steam", "games", "library", "playtime"),
            candidates=(_candidate("steam", "steam:owned-games"),),
        ),
        Capability(
            id="riot.account.lookup",
            name="Riot ID lookup",
            description="Resolve a Riot ID to PUUID using Riot's official ACCOUNT-V1 API.",
            pack="riot",
            tags=("gaming", "riot", "riot-id", "ign", "puuid", "lookup"),
            candidates=(_candidate("riot", "riot:account-by-riot-id"),),
        ),
        Capability(
            id="riot.account.reverse",
            name="Riot PUUID to Riot ID",
            description="Resolve a PUUID to current Riot ID account information.",
            pack="riot",
            tags=("gaming", "riot", "puuid", "riot-id", "lookup"),
            candidates=(_candidate("riot", "riot:account-by-puuid"),),
        ),
        Capability(
            id="league.player.profile",
            name="League player profile",
            description="Retrieve League summoner/profile metadata by PUUID from Riot's official API.",
            pack="league",
            tags=("gaming", "league", "lol", "player", "profile"),
            candidates=(_candidate("riot", "riot:lol-summoner-by-puuid"),),
        ),
        Capability(
            id="league.rank.current",
            name="League current ranked entries",
            description="Retrieve current League ranked queues, tiers, divisions and LP by PUUID.",
            pack="league",
            tags=("gaming", "league", "lol", "rank", "tier", "lp"),
            candidates=(_candidate("riot", "riot:lol-ranked-entries"),),
        ),
        Capability(
            id="league.champion.mastery",
            name="League champion mastery and mains",
            description="Retrieve champion mastery rows for a PUUID to identify mains/top mastered champions.",
            pack="league",
            tags=("gaming", "league", "lol", "champions", "mastery", "mains", "most-used"),
            candidates=(_candidate("riot", "riot:lol-champion-mastery"),),
        ),
        Capability(
            id="league.matches.recent",
            name="League recent match IDs",
            description="Retrieve recent League Match-V5 IDs for a PUUID.",
            pack="league",
            tags=("gaming", "league", "lol", "matches", "recent", "history"),
            candidates=(_candidate("riot", "riot:lol-match-ids", defaults={"count": 20}),),
        ),
        Capability(
            id="league.match.detail",
            name="League match detail",
            description="Retrieve one official League Match-V5 match payload by match ID.",
            pack="league",
            tags=("gaming", "league", "lol", "match", "stats"),
            candidates=(_candidate("riot", "riot:lol-match"),),
        ),
        Capability(
            id="tft.matches.recent",
            name="TFT recent match IDs",
            description="Retrieve recent Teamfight Tactics match IDs for a PUUID from Riot's official API.",
            pack="tft",
            tags=("gaming", "tft", "teamfight-tactics", "matches", "recent"),
            candidates=(_candidate("riot", "riot:tft-match-ids", defaults={"count": 20}),),
        ),
        Capability(
            id="tft.match.detail",
            name="TFT match detail",
            description="Retrieve one official Teamfight Tactics match payload by match ID.",
            pack="tft",
            tags=("gaming", "tft", "teamfight-tactics", "match", "placement", "units"),
            candidates=(_candidate("riot", "riot:tft-match"),),
        ),
    ]
