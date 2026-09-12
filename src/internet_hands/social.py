from __future__ import annotations

from typing import Any

from .intel import (
    _record,
    _request_json,
    _required_env,
    youtube_video_id,
)


async def youtube_search(query: str, limit: int = 25) -> dict[str, Any]:
    endpoint = "https://www.googleapis.com/youtube/v3/search"
    data = await _request_json(
        "GET",
        endpoint,
        params={
            "part": "snippet",
            "q": query,
            "type": "video,channel,playlist",
            "maxResults": min(max(limit, 1), 50),
            "key": _required_env("YOUTUBE_API_KEY"),
        },
    )
    return _record("youtube", "search", query, endpoint, data)


async def youtube_comments(video: str, limit: int = 100) -> dict[str, Any]:
    video_id = youtube_video_id(video)
    endpoint = "https://www.googleapis.com/youtube/v3/commentThreads"
    remaining = min(max(limit, 1), 500)
    page_token: str | None = None
    items: list[dict[str, Any]] = []

    while remaining > 0:
        batch = min(remaining, 100)
        params: dict[str, Any] = {
            "part": "snippet,replies",
            "videoId": video_id,
            "maxResults": batch,
            "textFormat": "plainText",
            "order": "relevance",
            "key": _required_env("YOUTUBE_API_KEY"),
        }
        if page_token:
            params["pageToken"] = page_token
        data = await _request_json("GET", endpoint, params=params)
        page_items = data.get("items") or []
        items.extend(page_items)
        remaining -= len(page_items)
        page_token = data.get("nextPageToken")
        if not page_token or not page_items:
            break

    return _record(
        "youtube",
        "comments",
        video_id,
        endpoint,
        {"items": items[:limit], "count": min(len(items), limit)},
    )


async def youtube_channel_videos(channel: str, limit: int = 50) -> dict[str, Any]:
    channel_endpoint = "https://www.googleapis.com/youtube/v3/channels"
    selector = "forHandle" if channel.startswith("@") else "id"
    channel_data = await _request_json(
        "GET",
        channel_endpoint,
        params={
            "part": "contentDetails,snippet",
            selector: channel,
            "key": _required_env("YOUTUBE_API_KEY"),
        },
    )
    channel_item = (channel_data.get("items") or [None])[0]
    if not channel_item:
        return _record(
            "youtube",
            "video",
            channel,
            channel_endpoint,
            {"items": [], "count": 0},
        )

    uploads = (
        channel_item.get("contentDetails", {})
        .get("relatedPlaylists", {})
        .get("uploads")
    )
    if not uploads:
        return _record(
            "youtube",
            "video",
            channel,
            channel_endpoint,
            {"items": [], "count": 0},
        )

    endpoint = "https://www.googleapis.com/youtube/v3/playlistItems"
    remaining = min(max(limit, 1), 500)
    page_token: str | None = None
    items: list[dict[str, Any]] = []
    while remaining > 0:
        batch = min(remaining, 50)
        params: dict[str, Any] = {
            "part": "snippet,contentDetails,status",
            "playlistId": uploads,
            "maxResults": batch,
            "key": _required_env("YOUTUBE_API_KEY"),
        }
        if page_token:
            params["pageToken"] = page_token
        data = await _request_json("GET", endpoint, params=params)
        page_items = data.get("items") or []
        items.extend(page_items)
        remaining -= len(page_items)
        page_token = data.get("nextPageToken")
        if not page_token or not page_items:
            break

    return _record(
        "youtube",
        "video",
        channel_item.get("id") or channel,
        endpoint,
        {
            "channel": channel_item.get("snippet"),
            "uploads_playlist": uploads,
            "items": items[:limit],
            "count": min(len(items), limit),
        },
    )


async def bluesky_search_posts(query: str, limit: int = 50) -> dict[str, Any]:
    endpoint = "https://public.api.bsky.app/xrpc/app.bsky.feed.searchPosts"
    data = await _request_json(
        "GET",
        endpoint,
        params={"q": query, "limit": min(max(limit, 1), 100)},
    )
    return _record("bluesky", "search", query, endpoint, data)


async def mastodon_statuses(
    instance: str,
    account_id: str,
    limit: int = 40,
) -> dict[str, Any]:
    instance = instance.strip().lower().rstrip("/")
    if "://" in instance or "/" in instance or "?" in instance or "#" in instance:
        raise ValueError("Mastodon instance must be a hostname, optionally with a port")
    endpoint = f"https://{instance}/api/v1/accounts/{account_id}/statuses"
    data = await _request_json(
        "GET",
        endpoint,
        params={"limit": min(max(limit, 1), 40), "exclude_replies": "false"},
    )
    return _record("mastodon", "posts", account_id, endpoint, data)


async def twitch_videos(user_id: str, limit: int = 50) -> dict[str, Any]:
    endpoint = "https://api.twitch.tv/helix/videos"
    headers = {
        "Client-Id": _required_env("TWITCH_CLIENT_ID"),
        "Authorization": f"Bearer {_required_env('TWITCH_ACCESS_TOKEN')}",
    }
    data = await _request_json(
        "GET",
        endpoint,
        headers=headers,
        params={
            "user_id": user_id,
            "first": min(max(limit, 1), 100),
            "type": "all",
        },
    )
    return _record("twitch", "video", user_id, endpoint, data)


async def twitch_streams(user_login: str | None = None, limit: int = 20) -> dict[str, Any]:
    endpoint = "https://api.twitch.tv/helix/streams"
    headers = {
        "Client-Id": _required_env("TWITCH_CLIENT_ID"),
        "Authorization": f"Bearer {_required_env('TWITCH_ACCESS_TOKEN')}",
    }
    params: dict[str, Any] = {"first": min(max(limit, 1), 100)}
    if user_login:
        params["user_login"] = user_login
    data = await _request_json("GET", endpoint, headers=headers, params=params)
    return _record("twitch", "live", user_login or "streams", endpoint, data)


async def tiktok_authorized_videos(limit: int = 20) -> dict[str, Any]:
    endpoint = "https://open.tiktokapis.com/v2/video/list/"
    token = _required_env("TIKTOK_ACCESS_TOKEN")
    fields = (
        "id,create_time,cover_image_url,share_url,video_description,duration,"
        "height,width,title,embed_html,embed_link,like_count,comment_count,"
        "share_count,view_count"
    )
    data = await _request_json(
        "POST",
        endpoint,
        params={"fields": fields},
        headers={"Authorization": f"Bearer {token}"},
        json_body={"max_count": min(max(limit, 1), 20)},
    )
    return _record(
        "tiktok",
        "video",
        "authorized-user",
        endpoint,
        data,
        public_data=False,
    )
