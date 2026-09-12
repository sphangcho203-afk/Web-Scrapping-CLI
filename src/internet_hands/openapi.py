from __future__ import annotations

import json
from typing import Any
from urllib.parse import urljoin

import yaml

from .fetcher import fetch_url


class OpenApiError(RuntimeError):
    pass


def _load_document(text: str) -> dict[str, Any]:
    try:
        value = json.loads(text)
    except json.JSONDecodeError:
        try:
            value = yaml.safe_load(text)
        except yaml.YAMLError as exc:
            raise OpenApiError("OpenAPI document is neither valid JSON nor YAML") from exc
    if not isinstance(value, dict):
        raise OpenApiError("OpenAPI document root must be an object")
    return value


def _servers(spec: dict[str, Any], spec_url: str) -> list[str]:
    if isinstance(spec.get("servers"), list):
        values = [
            item.get("url")
            for item in spec["servers"]
            if isinstance(item, dict) and isinstance(item.get("url"), str)
        ]
        if values:
            return values

    host = spec.get("host")
    if isinstance(host, str):
        schemes = spec.get("schemes") or ["https"]
        scheme = schemes[0] if isinstance(schemes, list) and schemes else "https"
        base_path = spec.get("basePath") or ""
        return [f"{scheme}://{host}{base_path}"]

    return [urljoin(spec_url, "/")]


def _parameter_summary(
    operation: dict[str, Any],
    path_item: dict[str, Any],
) -> list[dict[str, Any]]:
    merged: list[Any] = []
    if isinstance(path_item.get("parameters"), list):
        merged.extend(path_item["parameters"])
    if isinstance(operation.get("parameters"), list):
        merged.extend(operation["parameters"])

    result: list[dict[str, Any]] = []
    seen: set[tuple[str, str]] = set()
    for item in merged:
        if not isinstance(item, dict):
            continue
        name = item.get("name")
        location = item.get("in")
        if not isinstance(name, str) or not isinstance(location, str):
            continue
        key = (name, location)
        if key in seen:
            continue
        seen.add(key)
        result.append(
            {
                "name": name,
                "in": location,
                "required": bool(item.get("required")),
                "description": item.get("description"),
            }
        )
    return result


def _guess_capability(path: str, tags: list[str]) -> str:
    haystack = " ".join([path, *tags]).lower()
    for needle, capability in (
        ("video", "video"),
        ("channel", "channel"),
        ("user", "profile"),
        ("account", "profile"),
        ("profile", "profile"),
        ("search", "search"),
        ("comment", "comments"),
        ("stream", "live"),
        ("analytics", "analytics"),
        ("revenue", "revenue"),
        ("repo", "repositories"),
        ("post", "posts"),
        ("feed", "posts"),
        ("package", "package"),
        ("paper", "research"),
        ("work", "research"),
    ):
        if needle in haystack:
            return capability
    return "read"


async def discover_openapi(
    spec_url: str,
    *,
    max_bytes: int = 10_000_000,
) -> dict[str, Any]:
    capture = await fetch_url(
        spec_url,
        include_body=True,
        max_bytes=max_bytes,
    )
    if not capture.body_text:
        raise OpenApiError("OpenAPI document did not contain textual data")
    spec = _load_document(capture.body_text)

    version = spec.get("openapi") or spec.get("swagger")
    info = spec.get("info") if isinstance(spec.get("info"), dict) else {}
    paths = spec.get("paths")
    if not isinstance(paths, dict):
        raise OpenApiError("OpenAPI document has no paths object")

    servers = _servers(spec, capture.final_url)
    operations: list[dict[str, Any]] = []
    for path, raw_path_item in paths.items():
        if not isinstance(path, str) or not isinstance(raw_path_item, dict):
            continue
        for method in ("get", "head"):
            operation = raw_path_item.get(method)
            if not isinstance(operation, dict):
                continue
            tags = [tag for tag in operation.get("tags", []) if isinstance(tag, str)]
            operations.append(
                {
                    "method": method.upper(),
                    "path": path,
                    "operation_id": operation.get("operationId"),
                    "summary": operation.get("summary"),
                    "description": operation.get("description"),
                    "tags": tags,
                    "capability": _guess_capability(path, tags),
                    "parameters": _parameter_summary(operation, raw_path_item),
                }
            )

    return {
        "source": {
            "url": capture.final_url,
            "sha256": capture.sha256,
            "captured_at": capture.captured_at.isoformat(),
        },
        "api": {
            "title": info.get("title"),
            "version": info.get("version"),
            "spec_version": version,
            "servers": servers,
        },
        "policy": {
            "imported_methods": ["GET", "HEAD"],
            "note": (
                "Discovery imports read-only operations only. Authentication and "
                "provider terms still apply before execution."
            ),
        },
        "operations": operations,
        "operation_count": len(operations),
    }
