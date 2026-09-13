# Gaming Intelligence

Internet Hands v0.5 includes a read-only gaming intelligence plane on the same MCP endpoint as the Tool Mesh.

The goal is to let an agent resolve a player identity, fetch public profile/rank data, inspect mains or most-used characters, recent matches, leaderboards, titles/badges/achievements, and game-specific progression without exposing provider credentials or stuffing every provider schema into model context.

## MCP surface

Use `gaming_capabilities(game=...)` to inspect semantic abilities for one game/pack.

Use `gaming_intel(requests=[...])` to execute up to 20 independent gaming capabilities concurrently. Each request contains:

```json
{
  "capability": "dota2.hero.most_used",
  "arguments": {"account_id": "123456"}
}
```

`gaming_intel` only accepts capabilities tagged as gaming (plus the legacy MLBB pack), and every bundled capability is read-only.

The lower-level Tool Mesh remains available when an agent needs provider-specific control:

```text
mesh_route -> mesh_capability_resolve -> mesh_capability_execute
mesh_search -> mesh_describe -> mesh_execute
```

## Supported game packs

### Mobile Legends: Bang Bang

Existing MLBB player lookup is reused as a rich intelligence source. Added semantic views include:

- `mlbb.rank.current`
- `mlbb.rank.highest`
- `mlbb.hero.history`
- `mlbb.collector.profile`
- `mlbb.squad.profile`

The configured RapidAPI/community lookup can expose nickname, current/highest rank, collector/skin fields, squad data and hero history. Existing MLBB hero/reference OpenAPI capabilities remain available as well.

### VALORANT

Provider: HenrikDev community API, with server-side `HENRIKDEV_API_KEY`.

Capabilities:

- `valorant.account.lookup`
- `valorant.rank.mmr`
- `valorant.rank.history`
- `valorant.rank.lifetime`
- `valorant.matches.recent`
- `valorant.leaderboard`

The implementation intentionally does **not** expose credential-based store checking, authenticated Riot client sessions, hidden-name bypasses, or other private-account functionality. HenrikDev's own project asks applications to obtain player consent for player-data usage.

### Dota 2

Provider: OpenDota public API.

Capabilities include:

- player/IGN search and profile
- most-used heroes / mains
- recent matches
- win/loss totals
- hero rankings
- rating/MMR history
- global hero meta
- hero item popularity/build data

### Minecraft + Hypixel

Providers: Mojang public player endpoints and the Hypixel Public API.

Capabilities include:

- Minecraft IGN -> UUID
- UUID -> current IGN
- Hypixel player/network statistics
- recent Hypixel games
- Hypixel leaderboards
- SkyBlock profiles

Minecraft identity resolution itself does not require a key. Hypixel enrichment uses `HYPIXEL_API_KEY` server-side.

### HoYoverse public showcases

Provider: Enka.Network.

Capabilities:

- `genshin.player.showcase`
- `hsr.player.showcase`
- `zzz.player.showcase`

Only data intentionally exposed through the player's public in-game showcase/profile is consumed. ZZZ payloads can include profile title/medal and showcased-agent data when available.

### Roblox

Provider: Roblox public user endpoints.

Capabilities:

- public user search
- public user profile by numeric user ID

Cookie-gated economy/private account endpoints are intentionally outside this plane.

### osu!

Provider: official osu!api v2.

Capabilities:

- player profile/rank/performance data
- best scores
- recent scores
- recent public activity

Set `OSU_AUTHORIZATION` to a server-side public OAuth header value such as `Bearer <token>`. Consumers should cache responses and respect osu!'s polling guidance.

### Brawl Stars

Provider: official Brawl Stars API.

Capabilities:

- player profile / trophies / brawler progression
- recent battle log
- brawler reference catalog

Set `BRAWL_STARS_AUTHORIZATION` to `Bearer <developer-token>`.

### Clash of Clans

Provider: official Clash of Clans API.

Capabilities:

- player profile, league, heroes/troops/achievements
- league/rank history where the endpoint is available

Set `CLASH_OF_CLANS_AUTHORIZATION` to `Bearer <developer-token>`.

### Clash Royale

Provider: official Clash Royale API.

Capabilities:

- player profile / trophies / arena / cards
- recent battle log
- upcoming chest cycle

Set `CLASH_ROYALE_AUTHORIZATION` to `Bearer <developer-token>`.

## Provider refs

Gaming providers join the same normalized `provider:tool_id` mesh:

```text
opendota:player-heroes
valorant:mmr
mojang:username-to-uuid
hypixel:player
enka:genshin-showcase
roblox:user-profile
osu:user-scores
brawlstars:battlelog
clashofclans:player
clashroyale:battlelog
```

Provider keys never appear in descriptors, semantic capabilities, or normal execution receipts.

## Intelligence pattern

For a Dota 2 account, an agent can request a bundle like:

```json
[
  {"capability":"dota2.player.profile","arguments":{"account_id":"123456"}},
  {"capability":"dota2.hero.most_used","arguments":{"account_id":"123456"}},
  {"capability":"dota2.mmr.history","arguments":{"account_id":"123456"}},
  {"capability":"dota2.matches.recent","arguments":{"account_id":"123456"}}
]
```

The result is an evidence bundle grouped by capability. The model can then synthesize a player card: identity, rank/MMR, top heroes, recent form, and supporting provider evidence without relying on a single fragile endpoint.

## Safety and data boundary

Gaming Intelligence is deliberately public/read-only:

- no username/password collection
- no session-cookie or entitlement-token acquisition
- no anti-cheat bypass
- no private inventory/store checking
- no hidden identity bypass
- no account-sale checker workflows
- no write actions against game accounts

Community and unofficial APIs are treated as fallible providers rather than authoritative identity systems. Official APIs are preferred where they expose the requested data; community sources are used for public fields official APIs do not expose.
