from __future__ import annotations

import asyncio
import os
from datetime import UTC, date, datetime
from typing import Any
from urllib.parse import parse_qs, urljoin, urlsplit

import httpx

from .policy import validate_public_http_url

REDIRECT_CODES = {301, 302, 303, 307, 308}
SECRET_ENV_NAMES = (
    "YOUTUBE_API_KEY",
    "YOUTUBE_ANALYTICS_ACCESS_TOKEN",
    "GITHUB_TOKEN",
    "TWITCH_CLIENT_ID",
    "TWITCH_ACCESS_TOKEN",
    "TIKTOK_ACCESS_TOKEN",
    "REDDIT_ACCESS_TOKEN",
)


class IntelError(RuntimeError):
    pass


def _now() -> str:
    return datetime.now(UTC).isoformat()


def _record(
    provider: str,
    capability: str,
    subject: str,
    endpoint: str,
    data: Any,
    *,
    public_data: bool = True,
) -> dict[str, Any]:
    return {
        "provider": provider,
        "capability": capability,
        "subject": subject,
        "data": data,
        "provenance": {
            "endpoint": endpoint,
            "collected_at": _now(),
            "public_data": public_data,
        },
    }


def _safe_url(value: str) -> str:
    parts = urlsplit(value)
    return parts._replace(query="", fragment="").geturl()


def _redact_known_secrets(value: str) -> str:
    redacted = value
    for name in SECRET_ENV_NAMES:
        secret = os.getenv(name)
        if secret and len(secret) >= 6:
            redacted = redacted.replace(secret, "[redacted]")
    return redacted


async def _request_json(
    method: str,
    url: str,
    *,
    params: dict[str, Any] | None = None,
    headers: dict[str, str] | None = None,
    json_body: Any | None = None,
    timeout: float = 20.0,
    max_redirects: int = 5,
) -> Any:
    validate_public_http_url(url)
    current = url
    request_headers = {
        "Accept": "application/json",
        "User-Agent": "InternetHands/0.3",
    }
    if headers:
        request_headers.update(headers)

    async with httpx.AsyncClient(timeout=timeout, follow_redirects=False) as client:
        for _ in range(max_redirects + 1):
            validate_public_http_url(current)
            response = await client.request(
                method,
                current,
                params=params,
                headers=request_headers,
                json=json_body,
            )
            if response.status_code in REDIRECT_CODES and response.headers.get("location"):
                current = urljoin(str(response.url), response.headers["location"])
                params = None
                validate_public_http_url(current)
                continue
            safe_response_url = _safe_url(str(response.url))
            try:
                response.raise_for_status()
            except httpx.HTTPStatusError as exc:
                body = _redact_known_secrets(response.text[:800])
                raise IntelError(
                    f"{response.status_code} from {safe_response_url}: {body}"
                ) from exc
            try:
                return response.json()
            except ValueError as exc:
                raise IntelError(f"Expected JSON from {safe_response_url}") from exc

    raise IntelError(f"Exceeded max_redirects={max_redirects}")


def _required_env(name: str) -> str:
    value = os.getenv(name)
    if not value:
        raise IntelError(f"Missing required environment variable: {name}")
    return value


def youtube_video_id(value: str) -> str:
    if "://" not in value:
        return value
    parts = urlsplit(value)
    host = (parts.hostname or "").lower()
    if host in {"youtu.be", "www.youtu.be"}:
        return parts.path.strip("/").split("/", 1)[0]
    if host.endswith("youtube.com"):
        if parts.path == "/watch":
            return parse_qs(parts.query).get("v", [""])[0]
        path = parts.path.strip("/").split("/")
        if len(path) >= 2 and path[0] in {"shorts", "live", "embed"}:
            return path[1]
    raise IntelError("Could not determine a YouTube video ID")


async def youtube_video(value: str) -> dict[str, Any]:
    video_id = youtube_video_id(value)
    if not video_id:
        raise IntelError("YouTube video ID is empty")
    endpoint = "https://www.googleapis.com/youtube/v3/videos"
    data = await _request_json(
        "GET",
        endpoint,
        params={
            "part": "snippet,statistics,contentDetails,status",
            "id": video_id,
            "key": _required_env("YOUTUBE_API_KEY"),
        },
    )
    item = (data.get("items") or [None])[0]
    if not item:
        raise IntelError(f"YouTube video not found: {video_id}")
    stats = item.get("statistics") or {}
    views = _int_or_none(stats.get("viewCount"))
    likes = _int_or_none(stats.get("likeCount"))
    comments = _int_or_none(stats.get("commentCount"))
    derived = _engagement_metrics(views, likes, comments)
    return _record(
        "youtube",
        "video",
        video_id,
        endpoint,
        {"video": item, "derived": derived},
    )


async def youtube_channel(value: str) -> dict[str, Any]:
    endpoint = "https://www.googleapis.com/youtube/v3/channels"
    value = value.strip()
    selector = "forHandle" if value.startswith("@") else "id"
    data = await _request_json(
        "GET",
        endpoint,
        params={
            "part": "snippet,statistics,contentDetails,brandingSettings,status",
            selector: value,
            "key": _required_env("YOUTUBE_API_KEY"),
        },
    )
    item = (data.get("items") or [None])[0]
    if not item:
        raise IntelError(f"YouTube channel not found: {value}")
    return _record("youtube", "channel", value, endpoint, item)


async def youtube_owner_analytics(
    start_date: date,
    end_date: date,
    *,
    video_id: str | None = None,
    currency: str = "USD",
) -> dict[str, Any]:
    endpoint = "https://youtubeanalytics.googleapis.com/v2/reports"
    params: dict[str, Any] = {
        "ids": "channel==MINE",
        "startDate": start_date.isoformat(),
        "endDate": end_date.isoformat(),
        "metrics": (
            "views,estimatedMinutesWatched,likes,comments,shares,"
            "estimatedRevenue,estimatedAdRevenue,monetizedPlaybacks,"
            "playbackBasedCpm,adImpressions"
        ),
        "currency": currency,
    }
    if video_id:
        params["filters"] = f"video=={youtube_video_id(video_id)}"
    token = _required_env("YOUTUBE_ANALYTICS_ACCESS_TOKEN")
    data = await _request_json(
        "GET",
        endpoint,
        params=params,
        headers={"Authorization": f"Bearer {token}"},
    )
    return _record(
        "youtube",
        "revenue",
        video_id or "channel==MINE",
        endpoint,
        data,
        public_data=False,
    )


def youtube_revenue_scenario(
    views: int,
    *,
    rpm_low: float,
    rpm_high: float,
    currency: str = "USD",
) -> dict[str, Any]:
    if views < 0:
        raise ValueError("views must be non-negative")
    if rpm_low < 0 or rpm_high < 0 or rpm_high < rpm_low:
        raise ValueError("RPM range must satisfy 0 <= low <= high")
    units = views / 1000
    return {
        "kind": "scenario_estimate",
        "views": views,
        "rpm_low": rpm_low,
        "rpm_high": rpm_high,
        "currency": currency,
        "estimated_low": round(units * rpm_low, 2),
        "estimated_high": round(units * rpm_high, 2),
        "warning": (
            "Not reported creator earnings. This is only a scenario based on "
            "the RPM assumptions supplied by the caller."
        ),
    }


async def github_user(username: str) -> dict[str, Any]:
    username = username.strip().lstrip("@")
    endpoint = f"https://api.github.com/users/{username}"
    headers = {
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2026-03-10",
    }
    token = os.getenv("GITHUB_TOKEN")
    if token:
        headers["Authorization"] = f"Bearer {token}"
    data = await _request_json("GET", endpoint, headers=headers)
    return _record("github", "profile", username, endpoint, data)


async def github_repositories(username: str, limit: int = 100) -> dict[str, Any]:
    username = username.strip().lstrip("@")
    endpoint = f"https://api.github.com/users/{username}/repos"
    headers = {
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2026-03-10",
    }
    token = os.getenv("GITHUB_TOKEN")
    if token:
        headers["Authorization"] = f"Bearer {token}"
    data = await _request_json(
        "GET",
        endpoint,
        headers=headers,
        params={"per_page": min(max(limit, 1), 100), "sort": "updated"},
    )
    return _record("github", "repositories", username, endpoint, data)


async def bluesky_profile(actor: str) -> dict[str, Any]:
    actor = actor.strip().lstrip("@")
    endpoint = "https://public.api.bsky.app/xrpc/app.bsky.actor.getProfile"
    data = await _request_json("GET", endpoint, params={"actor": actor})
    return _record("bluesky", "profile", actor, endpoint, data)


async def bluesky_feed(actor: str, limit: int = 50) -> dict[str, Any]:
    actor = actor.strip().lstrip("@")
    endpoint = "https://public.api.bsky.app/xrpc/app.bsky.feed.getAuthorFeed"
    data = await _request_json(
        "GET",
        endpoint,
        params={"actor": actor, "limit": min(max(limit, 1), 100)},
    )
    return _record("bluesky", "posts", actor, endpoint, data)


async def hackernews_item(item_id: int) -> dict[str, Any]:
    endpoint = f"https://hacker-news.firebaseio.com/v0/item/{item_id}.json"
    data = await _request_json("GET", endpoint)
    if data is None:
        raise IntelError(f"Hacker News item not found: {item_id}")
    return _record("hackernews", "item", str(item_id), endpoint, data)


async def hackernews_user(username: str) -> dict[str, Any]:
    username = username.strip()
    endpoint = f"https://hacker-news.firebaseio.com/v0/user/{username}.json"
    data = await _request_json("GET", endpoint)
    if data is None:
        raise IntelError(f"Hacker News user not found: {username}")
    return _record("hackernews", "profile", username, endpoint, data)


async def mastodon_profile(instance: str, account: str) -> dict[str, Any]:
    instance = instance.strip().lower().rstrip("/")
    account = account.strip().lstrip("@")
    if "://" in instance or "/" in instance or "?" in instance or "#" in instance:
        raise IntelError("Mastodon instance must be a hostname, optionally with a port")
    endpoint = f"https://{instance}/api/v1/accounts/lookup"
    validate_public_http_url(endpoint)
    data = await _request_json("GET", endpoint, params={"acct": account})
    return _record("mastodon", "profile", f"{account}@{instance}", endpoint, data)


async def twitch_user(login: str) -> dict[str, Any]:
    login = login.strip().lstrip("@")
    endpoint = "https://api.twitch.tv/helix/users"
    headers = {
        "Client-Id": _required_env("TWITCH_CLIENT_ID"),
        "Authorization": f"Bearer {_required_env('TWITCH_ACCESS_TOKEN')}",
    }
    data = await _request_json("GET", endpoint, headers=headers, params={"login": login})
    return _record("twitch", "profile", login, endpoint, data)


async def tiktok_authorized_profile() -> dict[str, Any]:
    endpoint = "https://open.tiktokapis.com/v2/user/info/"
    token = _required_env("TIKTOK_ACCESS_TOKEN")
    fields = (
        "open_id,union_id,avatar_url,display_name,bio_description,"
        "profile_deep_link,is_verified,username,follower_count,"
        "following_count,likes_count,video_count"
    )
    data = await _request_json(
        "GET",
        endpoint,
        params={"fields": fields},
        headers={"Authorization": f"Bearer {token}"},
    )
    return _record(
        "tiktok",
        "profile",
        "authorized-user",
        endpoint,
        data,
        public_data=False,
    )


async def public_username_scan(username: str) -> dict[str, Any]:
    username = username.strip().lstrip("@")
    jobs = {
        "github": github_user(username),
        "bluesky": bluesky_profile(username),
        "hackernews": hackernews_user(username),
    }
    names = list(jobs)
    results = await asyncio.gather(*jobs.values(), return_exceptions=True)
    providers: dict[str, Any] = {}
    for name, result in zip(names, results, strict=True):
        if isinstance(result, Exception):
            providers[name] = {
                "found": False,
                "error": f"{type(result).__name__}: {result}",
            }
        else:
            providers[name] = {"found": True, "record": result}
    return {
        "username": username,
        "scope": "exact public handle checks only",
        "providers": providers,
        "collected_at": _now(),
    }


def _int_or_none(value: Any) -> int | None:
    if value is None:
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _engagement_metrics(
    views: int | None,
    likes: int | None,
    comments: int | None,
) -> dict[str, float | int | None]:
    actions = (likes or 0) + (comments or 0)
    if not views:
        return {
            "views": views,
            "likes": likes,
            "comments": comments,
            "engagement_actions": actions,
            "engagement_rate_percent": None,
            "like_rate_percent": None,
            "comment_rate_percent": None,
        }
    return {
        "views": views,
        "likes": likes,
        "comments": comments,
        "engagement_actions": actions,
        "engagement_rate_percent": round(actions / views * 100, 4),
        "like_rate_percent": round((likes or 0) / views * 100, 4),
        "comment_rate_percent": round((comments or 0) / views * 100, 4),
    }
