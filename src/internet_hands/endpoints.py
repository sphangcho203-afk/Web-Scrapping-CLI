from __future__ import annotations

import os
from dataclasses import dataclass
from enum import StrEnum


class AuthMode(StrEnum):
    NONE = "none"
    API_KEY = "api_key"
    BEARER = "bearer"
    OAUTH = "oauth"
    APP_TOKEN = "app_token"


class Capability(StrEnum):
    PROFILE = "profile"
    POSTS = "posts"
    VIDEO = "video"
    CHANNEL = "channel"
    SEARCH = "search"
    COMMENTS = "comments"
    LIVE = "live"
    REPOSITORIES = "repositories"
    ITEM = "item"
    PACKAGE = "package"
    RESEARCH = "research"
    ANALYTICS = "analytics"
    REVENUE = "revenue"


@dataclass(frozen=True, slots=True)
class EndpointSpec:
    provider: str
    name: str
    capability: Capability
    method: str
    url: str
    auth: AuthMode = AuthMode.NONE
    env: tuple[str, ...] = ()
    public_data: bool = True
    notes: str = ""

    @property
    def ready(self) -> bool:
        return not self.env or all(os.getenv(name) for name in self.env)


CATALOG: tuple[EndpointSpec, ...] = (
    EndpointSpec(
        "youtube",
        "videos.list",
        Capability.VIDEO,
        "GET",
        "https://www.googleapis.com/youtube/v3/videos",
        AuthMode.API_KEY,
        ("YOUTUBE_API_KEY",),
        notes="Public video metadata and statistics.",
    ),
    EndpointSpec(
        "youtube",
        "channels.list",
        Capability.CHANNEL,
        "GET",
        "https://www.googleapis.com/youtube/v3/channels",
        AuthMode.API_KEY,
        ("YOUTUBE_API_KEY",),
        notes="Public channel metadata and statistics.",
    ),
    EndpointSpec(
        "youtube",
        "search.list",
        Capability.SEARCH,
        "GET",
        "https://www.googleapis.com/youtube/v3/search",
        AuthMode.API_KEY,
        ("YOUTUBE_API_KEY",),
        notes="YouTube search; quota cost is provider-controlled.",
    ),
    EndpointSpec(
        "youtube",
        "commentThreads.list",
        Capability.COMMENTS,
        "GET",
        "https://www.googleapis.com/youtube/v3/commentThreads",
        AuthMode.API_KEY,
        ("YOUTUBE_API_KEY",),
        notes="Public comment threads where comments are available.",
    ),
    EndpointSpec(
        "youtube",
        "analytics.reports",
        Capability.ANALYTICS,
        "GET",
        "https://youtubeanalytics.googleapis.com/v2/reports",
        AuthMode.OAUTH,
        ("YOUTUBE_ANALYTICS_ACCESS_TOKEN",),
        public_data=False,
        notes="Owner-authorized channel analytics.",
    ),
    EndpointSpec(
        "youtube",
        "analytics.revenue",
        Capability.REVENUE,
        "GET",
        "https://youtubeanalytics.googleapis.com/v2/reports",
        AuthMode.OAUTH,
        ("YOUTUBE_ANALYTICS_ACCESS_TOKEN",),
        public_data=False,
        notes="Owner-authorized estimatedRevenue and ad metrics.",
    ),
    EndpointSpec(
        "github",
        "user",
        Capability.PROFILE,
        "GET",
        "https://api.github.com/users/{username}",
        notes="Public GitHub profile. Token optional for higher rate limits.",
    ),
    EndpointSpec(
        "github",
        "user-repositories",
        Capability.REPOSITORIES,
        "GET",
        "https://api.github.com/users/{username}/repos",
        notes="Public repositories for a user.",
    ),
    EndpointSpec(
        "github",
        "search-users",
        Capability.SEARCH,
        "GET",
        "https://api.github.com/search/users",
        notes="Public GitHub user search. Token recommended.",
    ),
    EndpointSpec(
        "bluesky",
        "profile",
        Capability.PROFILE,
        "GET",
        "https://public.api.bsky.app/xrpc/app.bsky.actor.getProfile",
        notes="Public AppView profile lookup.",
    ),
    EndpointSpec(
        "bluesky",
        "author-feed",
        Capability.POSTS,
        "GET",
        "https://public.api.bsky.app/xrpc/app.bsky.feed.getAuthorFeed",
        notes="Public posts for an actor.",
    ),
    EndpointSpec(
        "bluesky",
        "search-posts",
        Capability.SEARCH,
        "GET",
        "https://public.api.bsky.app/xrpc/app.bsky.feed.searchPosts",
        notes="Public Bluesky post search.",
    ),
    EndpointSpec(
        "hackernews",
        "item",
        Capability.ITEM,
        "GET",
        "https://hacker-news.firebaseio.com/v0/item/{item_id}.json",
        notes="Official public Hacker News item API.",
    ),
    EndpointSpec(
        "hackernews",
        "user",
        Capability.PROFILE,
        "GET",
        "https://hacker-news.firebaseio.com/v0/user/{username}.json",
        notes="Official public Hacker News user API.",
    ),
    EndpointSpec(
        "hackernews",
        "top-stories",
        Capability.POSTS,
        "GET",
        "https://hacker-news.firebaseio.com/v0/topstories.json",
        notes="Official public Hacker News feed.",
    ),
    EndpointSpec(
        "mastodon",
        "account-lookup",
        Capability.PROFILE,
        "GET",
        "https://{instance}/api/v1/accounts/lookup",
        notes="Public lookup on a user-selected Mastodon instance.",
    ),
    EndpointSpec(
        "mastodon",
        "account-statuses",
        Capability.POSTS,
        "GET",
        "https://{instance}/api/v1/accounts/{account_id}/statuses",
        notes="Public statuses on a user-selected Mastodon instance.",
    ),
    EndpointSpec(
        "twitch",
        "users",
        Capability.PROFILE,
        "GET",
        "https://api.twitch.tv/helix/users",
        AuthMode.APP_TOKEN,
        ("TWITCH_CLIENT_ID", "TWITCH_ACCESS_TOKEN"),
        notes="Twitch Helix user lookup.",
    ),
    EndpointSpec(
        "twitch",
        "videos",
        Capability.VIDEO,
        "GET",
        "https://api.twitch.tv/helix/videos",
        AuthMode.APP_TOKEN,
        ("TWITCH_CLIENT_ID", "TWITCH_ACCESS_TOKEN"),
        notes="Twitch Helix video metadata.",
    ),
    EndpointSpec(
        "twitch",
        "streams",
        Capability.LIVE,
        "GET",
        "https://api.twitch.tv/helix/streams",
        AuthMode.APP_TOKEN,
        ("TWITCH_CLIENT_ID", "TWITCH_ACCESS_TOKEN"),
        notes="Twitch live stream metadata.",
    ),
    EndpointSpec(
        "tiktok",
        "user-info",
        Capability.PROFILE,
        "GET",
        "https://open.tiktokapis.com/v2/user/info/",
        AuthMode.OAUTH,
        ("TIKTOK_ACCESS_TOKEN",),
        public_data=False,
        notes="Requires user authorization and approved scopes.",
    ),
    EndpointSpec(
        "tiktok",
        "video-list",
        Capability.VIDEO,
        "POST",
        "https://open.tiktokapis.com/v2/video/list/",
        AuthMode.OAUTH,
        ("TIKTOK_ACCESS_TOKEN",),
        public_data=False,
        notes="Authorized user's public videos via TikTok Display API.",
    ),
    EndpointSpec(
        "reddit",
        "oauth-api",
        Capability.POSTS,
        "GET",
        "https://oauth.reddit.com/",
        AuthMode.OAUTH,
        ("REDDIT_ACCESS_TOKEN",),
        notes="OAuth-backed Reddit Data API root.",
    ),
    EndpointSpec(
        "gitlab",
        "users",
        Capability.PROFILE,
        "GET",
        "https://gitlab.com/api/v4/users",
        notes="Public GitLab user lookup.",
    ),
    EndpointSpec(
        "wikipedia",
        "mediawiki",
        Capability.SEARCH,
        "GET",
        "https://en.wikipedia.org/w/api.php",
        notes="MediaWiki API for encyclopedia search and page data.",
    ),
    EndpointSpec(
        "wikidata",
        "sparql",
        Capability.RESEARCH,
        "GET",
        "https://query.wikidata.org/sparql",
        notes="Public Wikidata SPARQL endpoint.",
    ),
    EndpointSpec(
        "openalex",
        "works",
        Capability.RESEARCH,
        "GET",
        "https://api.openalex.org/works",
        notes="Open research graph for works, authors, and institutions.",
    ),
    EndpointSpec(
        "crossref",
        "works",
        Capability.RESEARCH,
        "GET",
        "https://api.crossref.org/works",
        notes="Public scholarly metadata.",
    ),
    EndpointSpec(
        "npm",
        "package",
        Capability.PACKAGE,
        "GET",
        "https://registry.npmjs.org/{package}",
        notes="npm registry package metadata.",
    ),
    EndpointSpec(
        "pypi",
        "package",
        Capability.PACKAGE,
        "GET",
        "https://pypi.org/pypi/{package}/json",
        notes="PyPI package metadata.",
    ),
    EndpointSpec(
        "crates",
        "crate",
        Capability.PACKAGE,
        "GET",
        "https://crates.io/api/v1/crates/{package}",
        notes="crates.io package metadata.",
    ),
)


def endpoint_catalog(
    *,
    provider: str | None = None,
    capability: Capability | None = None,
    ready_only: bool = False,
) -> list[EndpointSpec]:
    items = list(CATALOG)
    if provider:
        items = [item for item in items if item.provider == provider]
    if capability:
        items = [item for item in items if item.capability == capability]
    if ready_only:
        items = [item for item in items if item.ready]
    return items


def providers() -> list[str]:
    return sorted({item.provider for item in CATALOG})
