from __future__ import annotations

import re
from html.parser import HTMLParser
from urllib.parse import urljoin, urlsplit

from .models import ExtractedDocument, FetchResult

_WS = re.compile(r"\s+")
_SKIP_TAGS = {"script", "style", "noscript", "template", "svg", "canvas"}
_HEADING_TAGS = {"h1", "h2", "h3", "h4", "h5", "h6"}


class _DocumentParser(HTMLParser):
    def __init__(self, base_url: str) -> None:
        super().__init__(convert_charrefs=True)
        self.base_url = base_url
        self.skip_depth = 0
        self.in_title = False
        self.heading_tag: str | None = None
        self.title_parts: list[str] = []
        self.heading_parts: list[str] = []
        self.headings: list[str] = []
        self.text_parts: list[str] = []
        self.links: set[str] = set()
        self.description: str | None = None

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        lowered = tag.lower()
        attr_map = {key.lower(): value for key, value in attrs if value is not None}
        if lowered in _SKIP_TAGS:
            self.skip_depth += 1
            return
        if self.skip_depth:
            return
        if lowered == "title":
            self.in_title = True
        elif lowered in _HEADING_TAGS:
            self.heading_tag = lowered
            self.heading_parts = []
        elif lowered == "meta":
            name = (attr_map.get("name") or attr_map.get("property") or "").lower()
            if name in {"description", "og:description"} and not self.description:
                self.description = _clean(attr_map.get("content") or "") or None
        elif lowered == "a" and attr_map.get("href"):
            absolute = urljoin(self.base_url, attr_map["href"])
            parts = urlsplit(absolute)
            if parts.scheme in {"http", "https"}:
                self.links.add(parts._replace(fragment="").geturl())

    def handle_endtag(self, tag: str) -> None:
        lowered = tag.lower()
        if lowered in _SKIP_TAGS:
            if self.skip_depth:
                self.skip_depth -= 1
            return
        if self.skip_depth:
            return
        if lowered == "title":
            self.in_title = False
        elif self.heading_tag == lowered:
            heading = _clean(" ".join(self.heading_parts))
            if heading:
                self.headings.append(heading)
            self.heading_tag = None
            self.heading_parts = []

    def handle_data(self, data: str) -> None:
        if self.skip_depth:
            return
        cleaned = _clean(data)
        if not cleaned:
            return
        if self.in_title:
            self.title_parts.append(cleaned)
        if self.heading_tag:
            self.heading_parts.append(cleaned)
        self.text_parts.append(cleaned)


def extract_document(result: FetchResult) -> ExtractedDocument:
    body = result.body_text or ""
    content_type = (result.content_type or "").lower()
    if "html" not in content_type and "<html" not in body[:1000].lower():
        text = _clean(body)
        return ExtractedDocument(
            url=result.final_url,
            title=None,
            description=None,
            text=text,
            headings=[],
            links=[],
            captured_at=result.captured_at,
            sha256=result.sha256,
        )

    parser = _DocumentParser(result.final_url)
    parser.feed(body)
    title = _clean(" ".join(parser.title_parts)) or None
    text = _clean(" ".join(parser.text_parts))
    return ExtractedDocument(
        url=result.final_url,
        title=title,
        description=parser.description,
        text=text,
        headings=parser.headings,
        links=sorted(parser.links),
        captured_at=result.captured_at,
        sha256=result.sha256,
    )


def _clean(value: str) -> str:
    return _WS.sub(" ", value).strip()
