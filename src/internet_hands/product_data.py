"""Bounded, source-only product offers from published JSON-LD. No price guessing."""
from __future__ import annotations

import hashlib
import json
import re
from decimal import Decimal, InvalidOperation
from html.parser import HTMLParser
from urllib.parse import urljoin, urlsplit

MAX_PRODUCTS = 32
MAX_JSON_BYTES = 128_000
TRACK_FIELDS = {"price", "availability"}


class _JSONLD(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.active = False
        self.parts = []
        self.documents = []
        self.size = 0
        self.overflow = False

    def handle_starttag(self, tag, attrs):
        if tag == "script":
            self.active = dict(attrs).get("type", "").lower().split(";")[0] == "application/ld+json"
            self.parts = []

    def handle_data(self, data):
        if self.active:
            self.size += len(data.encode())
            if self.size > MAX_JSON_BYTES:
                self.overflow = True
            elif not self.overflow:
                self.parts.append(data)

    def handle_endtag(self, tag):
        if tag == "script" and self.active:
            if not self.overflow:
                self.documents.append("".join(self.parts))
            self.active = False
            self.parts = []


def _text(value, limit=300):
    return " ".join(value.split())[:limit] if isinstance(value, str) else ""


def _kind(node, kind):
    types = node.get("@type", [])
    return any(str(item).rstrip("/").split("/")[-1] == kind
               for item in (types if isinstance(types, list) else [types]))


def _price(value):
    if isinstance(value, bool) or not isinstance(value, (str, int, float, Decimal)):
        return None
    raw = str(value).strip()
    if len(raw) > 40 or not re.fullmatch(r"\d{1,18}(?:\.\d{1,8})?", raw):
        return None
    try:
        number = Decimal(raw)
        if not number.is_finite() or number < 0:
            return None
        return format(number.normalize(), "f")
    except InvalidOperation:
        return None


def extract_products(body: str, source_url: str) -> tuple[list[dict], str | None]:
    parser = _JSONLD()
    parser.feed(body)
    if parser.overflow:
        return [], "product_data_limit"
    products, nodes = [], 0
    index = {}
    roots = []
    try:
        for document in parser.documents:
            roots.append(json.loads(document, parse_float=Decimal))
    except (ValueError, RecursionError):
        return [], "invalid_product_data"

    def walk(value, depth=0):
        nonlocal nodes
        nodes += 1
        if nodes > 1500 or depth > 16:
            raise ValueError("product_data_limit")
        if isinstance(value, dict):
            identifier = value.get("@id")
            if isinstance(identifier, str) and len(value) > 1:
                index[identifier] = value
            if _kind(value, "Product"):
                products.append(value)
            for child in value.values():
                walk(child, depth + 1)
        elif isinstance(value, list):
            for child in value:
                walk(child, depth + 1)

    try:
        for root in roots:
            walk(root)
    except ValueError:
        return [], "product_data_limit"
    rows = {}
    for product in products:
        name = _text(product.get("name"))
        sku = _text(product.get("sku"), 120) or None
        offers = product.get("offers") or []
        for offer in (offers if isinstance(offers, list) else [offers]):
            if not isinstance(offer, dict):
                continue
            offer = index.get(offer.get("@id"), offer) if isinstance(offer.get("@id"), str) else offer
            # AggregateOffer ranges are not a single purchasable price.
            if _kind(offer, "AggregateOffer"):
                continue
            price = _price(offer.get("price"))
            currency = _text(offer.get("priceCurrency"), 10).upper()
            if not name or price is None or not re.fullmatch(r"[A-Z]{3}", currency):
                continue
            availability = _text(offer.get("availability"), 120).rstrip("/").split("/")[-1] or None
            offer_url = urljoin(source_url, _text(offer.get("url"), 2000) or source_url)
            parsed = urlsplit(offer_url)
            if parsed.scheme not in {"https", "http"} or not parsed.netloc or parsed.username or parsed.password:
                offer_url = source_url
            identifier = _text(product.get("@id"), 500) or sku or name
            offer_identifier = _text(offer.get("@id"), 500) or offer_url
            key = hashlib.sha256(json.dumps([identifier, offer_identifier, currency]).encode()).hexdigest()[:24]
            row = {"product_id": key, "name": name, "sku": sku, "price": price,
                   "currency": currency, "availability": availability, "url": offer_url,
                   "source_url": source_url, "extraction_source": "published_json_ld"}
            if key in rows and rows[key] != row:
                return [], "ambiguous_product_offers"
            rows[key] = row
            if len(rows) > MAX_PRODUCTS:
                return [], "product_data_limit"
    return sorted(rows.values(), key=lambda row: row["product_id"]), None if rows else "product_price_unavailable"


def tracked_values(rows: list[dict], fields: list[str]) -> list[dict]:
    keys = set(fields) | {"product_id"}
    if "price" in keys:
        keys.add("currency")
    return sorted(({key: row.get(key) for key in sorted(keys)} for row in rows),
                  key=lambda row: row["product_id"])


def product_fingerprint(rows: list[dict], fields: list[str]) -> str:
    return hashlib.sha256(json.dumps(tracked_values(rows, fields), sort_keys=True).encode()).hexdigest()


def product_changes(previous: list[dict], current: list[dict], fields: list[str]) -> list[dict]:
    before = {row["product_id"]: row for row in tracked_values(previous, fields)}
    after = {row["product_id"]: row for row in tracked_values(current, fields)}
    return [{"product_id": key, "before": before.get(key), "after": after.get(key)}
            for key in sorted(before.keys() | after.keys()) if before.get(key) != after.get(key)]
