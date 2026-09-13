from __future__ import annotations

import re
from typing import Any
from urllib.parse import quote

from .intel import _record, _request_json

LANGUAGE_RE = re.compile(r"^[a-z][a-z0-9-]{0,11}$")
PACKAGE_RE = re.compile(r"^[A-Za-z0-9@._+\-/]{1,214}$")


def _language(value: str) -> str:
    value = value.strip().lower()
    if not LANGUAGE_RE.fullmatch(value):
        raise ValueError("language must be a short language/project code")
    return value


def _package(value: str) -> str:
    value = value.strip()
    if not PACKAGE_RE.fullmatch(value) or ".." in value:
        raise ValueError("invalid package name")
    return value


async def wikipedia_search(
    query: str,
    *,
    language: str = "en",
    limit: int = 10,
) -> dict[str, Any]:
    language = _language(language)
    endpoint = f"https://{language}.wikipedia.org/w/api.php"
    data = await _request_json(
        "GET",
        endpoint,
        params={
            "action": "query",
            "list": "search",
            "srsearch": query,
            "srlimit": min(max(limit, 1), 50),
            "format": "json",
            "formatversion": 2,
            "utf8": 1,
        },
    )
    return _record("wikipedia", "search", query, endpoint, data)


async def wikipedia_page(
    title: str,
    *,
    language: str = "en",
) -> dict[str, Any]:
    language = _language(language)
    endpoint = f"https://{language}.wikipedia.org/w/api.php"
    data = await _request_json(
        "GET",
        endpoint,
        params={
            "action": "query",
            "prop": "extracts|info|pageimages",
            "titles": title,
            "explaintext": 1,
            "inprop": "url",
            "piprop": "thumbnail|original",
            "pithumbsize": 800,
            "format": "json",
            "formatversion": 2,
        },
    )
    return _record("wikipedia", "research", title, endpoint, data)


async def wikidata_search(
    query: str,
    *,
    language: str = "en",
    limit: int = 10,
) -> dict[str, Any]:
    language = _language(language)
    endpoint = "https://www.wikidata.org/w/api.php"
    data = await _request_json(
        "GET",
        endpoint,
        params={
            "action": "wbsearchentities",
            "search": query,
            "language": language,
            "uselang": language,
            "limit": min(max(limit, 1), 50),
            "format": "json",
        },
    )
    return _record("wikidata", "research", query, endpoint, data)


async def openalex_search(query: str, *, limit: int = 25) -> dict[str, Any]:
    endpoint = "https://api.openalex.org/works"
    data = await _request_json(
        "GET",
        endpoint,
        params={
            "search": query,
            "per-page": min(max(limit, 1), 100),
        },
    )
    return _record("openalex", "research", query, endpoint, data)


async def crossref_search(query: str, *, limit: int = 25) -> dict[str, Any]:
    endpoint = "https://api.crossref.org/works"
    data = await _request_json(
        "GET",
        endpoint,
        params={
            "query.bibliographic": query,
            "rows": min(max(limit, 1), 100),
            "select": "DOI,title,author,published,type,URL,publisher,is-referenced-by-count",
        },
    )
    return _record("crossref", "research", query, endpoint, data)


async def gitlab_user(username: str) -> dict[str, Any]:
    username = username.strip().lstrip("@")
    endpoint = "https://gitlab.com/api/v4/users"
    data = await _request_json("GET", endpoint, params={"username": username})
    exact = [
        item
        for item in data
        if isinstance(item, dict) and item.get("username", "").lower() == username.lower()
    ]
    return _record("gitlab", "profile", username, endpoint, exact)


async def pypi_package(name: str) -> dict[str, Any]:
    name = _package(name)
    endpoint = f"https://pypi.org/pypi/{quote(name, safe='')}/json"
    data = await _request_json("GET", endpoint)
    return _record("pypi", "package", name, endpoint, data)


async def npm_package(name: str) -> dict[str, Any]:
    name = _package(name)
    endpoint = f"https://registry.npmjs.org/{quote(name, safe='@')}"
    data = await _request_json("GET", endpoint)
    return _record("npm", "package", name, endpoint, data)


async def crates_package(name: str) -> dict[str, Any]:
    name = _package(name)
    endpoint = f"https://crates.io/api/v1/crates/{quote(name, safe='')}"
    data = await _request_json("GET", endpoint)
    return _record("crates", "package", name, endpoint, data)
