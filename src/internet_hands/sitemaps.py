"""Bounded XML sitemap parsing. Fetching and crawl policy stay in the crawler."""
from __future__ import annotations

from xml.etree import ElementTree

MAX_SITEMAP_DOCUMENTS = 8
MAX_SITEMAP_BYTES = 512_000
MAX_SITEMAP_LOCATIONS = 1000
_NAMESPACE = "http://www.sitemaps.org/schemas/sitemap/0.9"


def sitemap_locations(text: str) -> tuple[str, list[str], bool]:
    # Sitemap XML needs no DTD or entities. Reject declarations before parsing,
    # including internal entities that could expand a small input enormously.
    if len(text.encode()) > MAX_SITEMAP_BYTES or "<!DOCTYPE" in text.upper() or "<!ENTITY" in text.upper():
        raise ValueError("Sitemap exceeds its byte limit or contains XML declarations.")
    try:
        root = ElementTree.fromstring(text)
    except ElementTree.ParseError as exc:
        raise ValueError("Sitemap XML is malformed.") from exc
    prefix = "{" + _NAMESPACE + "}" if root.tag.startswith("{") else ""
    kind = root.tag.removeprefix(prefix)
    if kind not in {"urlset", "sitemapindex"}:
        raise ValueError("Expected a sitemap urlset or sitemapindex.")
    entry = "url" if kind == "urlset" else "sitemap"
    locations = []
    for child in root:
        if child.tag != prefix + entry:
            continue
        loc = child.find(prefix + "loc")
        if loc is None or not (loc.text or "").strip():
            continue
        if len(locations) == MAX_SITEMAP_LOCATIONS:
            return kind, locations, True
        locations.append(loc.text.strip())
    return kind, locations, False
