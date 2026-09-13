# Gaming Intelligence

Internet Hands v0.5 includes a public/read-only gaming intelligence plane on the same MCP endpoint as the Tool Mesh.

The goal is to let an agent resolve a player identity, fetch public profile/rank data, inspect mains or most-used characters, recent matches, leaderboards, titles/badges/achievements, game libraries/playtime, and game-specific progression without exposing provider credentials or stuffing every provider schema into model context.

## MCP surface

### `gaming_profile`

The normal high-level path. Give Internet Hands a game plus that game's public identity fields and it builds the appropriate evidence bundle automatically.

```json
{
  "game": "dota2",
  "identity": {"account_id": "123456"}
}
```

The Dota preset requests profile, most-used heroes, win/loss totals, recent matches, and rating history. Other games use different evidence presets.

### `gaming_profile_plan`

Returns the planned evidence bundle without contacting providers. Use this when an agent wants to inspect the plan first or when one identity lookup must happen before enrichment.

### `gaming_capabilities`

Lists semantic gaming abilities, optionally scoped to one game/pack.

### `gaming_intel`

Executes up to 20 independent gaming capabilities concurrently. Example:

```json
{
  "requests": [
    {"capability": "dota2.hero.most_used", "arguments": {"account_id": "123456"}},
    {"capability": "dota2.mmr.history", "arguments": {"account_id": "123456"}}
  ]
}
```

`gaming_intel` only accepts gaming capabilities and every bundled capability is read-only.

The lower-level Tool Mesh remains available when an agent needs provider-specific control:

```text
mesh_route -> mesh_capability_resolve -> mesh_capability_execute
mesh_search -> mesh_describe -> mesh_execute
```

## Supported game packs

### Mobile Legends: Bang Bang

Existing MLBB player lookup is reused as a rich intelligence source. Semantic views include:

- `mlbb.rank.current`
- `mlbb.rank.highest`
- `mlbb.hero.history`
- `mlbb.collector.profile`
- `mlbb.squad.profile`

The configured RapidAPI/community lookup can expose nickname, current/highest rank, collector/skin fields, squad data and hero history. The one-call MLBB profile preset intentionally fetches the rich player payload once instead of duplicating identical provider calls. Existing MLBB hero/reference OpenAPI capabilities remain available as well.

### VALORANT

Provider: HenrikDev community API, with server-side `HENRIKDEV_API_KEY`.

Capabilities:

- `valorant.account.lookup`
- `valorant.rank.mmr`
- `valorant.rank.history`
- `valorant.rank.lifetime`
- `valorant.matches.recent`
- `valorant.leaderboard`

The implementation intentionally does not expose credential-based store checking, authenticated Riot client sessions, hidden-name bypasses, or other private-account functionality. The community provider's consent expectations remain part of the provider metadata.

### League of Legends + Riot identity

Provider: official Riot Games API, with server-side `RIOT_API_KEY` injected as `X-Riot-Token`.

Capabilities:

- `riot.account.lookup` - Riot ID to PUUID
- `riot.account.reverse` - PUUID to current Riot ID
- `league.player.profile`
- `league.rank.current`
- `league.champion.mastery`
- `league.matches.recent`
- `league.match.detail`

The profile flow follows Riot's current Riot-ID/PUUID model rather than deprecated summoner-name lookup. Riot platform and regional routing values are allowlisted by Internet Hands; agent input cannot turn the route into an arbitrary host.

Champion mastery is the official mains/mastery signal. Recent match discovery returns Match-V5 IDs first, after which selected matches can be expanded with `league.match.detail`.

### Teamfight Tactics

Provider: official Riot Games API through the same server-side Riot key.

Capabilities:

- `riot.account.lookup`
- `riot.account.reverse`
- `tft.matches.recent`
- `tft.match.detail`

The profile preset is dependency-aware: Riot ID is resolved to PUUID first, then public match intelligence can be requested. Consumers remain responsible for Riot's game-specific API policies.

### Steam

Provider: official Steamworks Web API, with `STEAM_WEB_API_KEY` injected server-side as the API query key.

Capabilities:

- `steam.player.resolve` - vanity profile name to SteamID64
- `steam.player.profile` - public persona/profile summary
- `steam.games.recent` - recently played games and playtime
- `steam.games.owned` - visible owned-game/playtime data

The Steam key never appears in the agent schema, capability descriptor, or normal result metadata. Owned/recent game data naturally depends on the player's Steam privacy settings.

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
riot:account-by-riot-id
riot:lol-champion-mastery
steam:resolve-vanity
steam:recent-games
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

A player intelligence card is evidence-first:

```text
identity resolution
    -> public profile
    -> rank / rating / MMR
    -> mains / mastery / most-used characters
    -> recent form / matches
    -> titles / badges / achievements / progression
    -> game-specific extras
```

Not every game exposes every field. Internet Hands therefore returns the evidence bundle and selected provider refs instead of inventing missing statistics. Community and unofficial APIs are treated as fallible sources; official APIs are preferred where they expose the requested data.

## Safety and data boundary

Gaming Intelligence is deliberately public/read-only:

- no username/password collection
- no session-cookie or entitlement-token acquisition
- no anti-cheat bypass
- no private inventory/store checking
- no hidden identity bypass
- no account-sale checker workflows
- no write actions against game accounts

Public/community endpoints and reverse-engineered **public** interfaces may be added as provider fallbacks, but endpoints that depend on private account credentials, local client secrets, bypass techniques, or unsupported private-session access do not enter this plane.
