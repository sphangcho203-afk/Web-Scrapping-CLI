"""Bounded discovery of public GitHub repositories and documented API surfaces."""

from __future__ import annotations

import base64
import json
import re
from typing import Any
from urllib.parse import quote, urlsplit

import httpx
import yaml

from .tool_mesh import ToolDescriptor

_REPO_PART = re.compile(r"^[A-Za-z0-9_.-]{1,100}$")
_SPEC = re.compile(r"(?:^|/)(?:openapi|swagger|api[-_]schema)(?:\.[^.]+)?\.(?:json|ya?ml)$|\.postman_collection\.json$", re.IGNORECASE)
_API_PATH = re.compile(r"(?:^|/)(?:routes?|api|graphql|schemas?|proto)(?:/|$)|\.(?:proto|graphql)$", re.IGNORECASE)
_MAX_RESPONSE = 1_500_000


class PublicRepositoryError(ValueError):
    def __init__(self, message: str, status_code: int = 400) -> None:
        super().__init__(message)
        self.status_code = status_code


def repository_parts(value: str) -> tuple[str, str]:
    value = value.strip()
    if value.startswith("https://"):
        url = urlsplit(value)
        if url.hostname != "github.com" or url.query or url.fragment:
            raise PublicRepositoryError("Use a public github.com repository URL.")
        value = url.path.strip("/")
    value = value.removesuffix(".git")
    parts = value.split("/")
    if len(parts) != 2 or not all(_REPO_PART.fullmatch(part) and part not in {".", ".."} for part in parts):
        raise PublicRepositoryError("Enter a repository as owner/name or its github.com URL.")
    return parts[0], parts[1]


def _spec_summary(content: bytes) -> dict[str, Any]:
    try:
        document = json.loads(content) if content.lstrip().startswith(b"{") else yaml.safe_load(content)
    except (ValueError, yaml.YAMLError, UnicodeDecodeError):
        return {"parsed": False, "endpoints": [], "operations": [], "oauth_scopes": []}
    if not isinstance(document, dict) or not ("openapi" in document or "swagger" in document):
        return {"parsed": False, "endpoints": [], "operations": [], "oauth_scopes": []}
    paths = document.get("paths") or {}
    methods = {"get", "post", "put", "patch", "delete", "head", "options"}
    endpoints = [
        {"method": method.upper(), "path": str(path)[:240]}
        for path, operations in (paths.items() if isinstance(paths, dict) else [])
        if isinstance(path, str) and isinstance(operations, dict)
        for method in operations
        if isinstance(method, str) and method.lower() in methods
    ][:40]
    operations: list[dict[str, Any]] = []
    for path, path_item in (paths.items() if isinstance(paths, dict) else []):
        if not isinstance(path, str) or not isinstance(path_item, dict):
            continue
        for method in ("get", "head"):
            operation = path_item.get(method)
            if not isinstance(operation, dict):
                continue
            path_parameters = path_item.get("parameters")
            operation_parameters = operation.get("parameters")
            parameters = (path_parameters if isinstance(path_parameters, list) else []) + (
                operation_parameters if isinstance(operation_parameters, list) else [])
            inputs = sorted({str(item["name"])[:80] for item in parameters
                             if isinstance(item, dict) and isinstance(item.get("name"), str)
                             and item.get("in") in {"path", "query"}})[:8]
            security = operation.get("security", document.get("security", []))
            operations.append({
                "method": method.upper(), "path": path[:240],
                "name": str(operation.get("summary") or operation.get("operationId") or f"Read {path}")[:120],
                "inputs": inputs, "requires_auth": bool(security),
            })
            if len(operations) >= 20:
                break
        if len(operations) >= 20:
            break
    schemes = ((document.get("components") or {}).get("securitySchemes") or {}) if isinstance(document.get("components"), dict) else {}
    if not schemes and isinstance(document.get("securityDefinitions"), dict):
        schemes = document["securityDefinitions"]
    scopes: set[str] = set()
    for scheme in schemes.values() if isinstance(schemes, dict) else []:
        if not isinstance(scheme, dict):
            continue
        for flow in (scheme.get("flows") or {}).values() if isinstance(scheme.get("flows"), dict) else []:
            if isinstance(flow, dict) and isinstance(flow.get("scopes"), dict):
                scopes.update(str(name)[:100] for name in flow["scopes"])
        if isinstance(scheme.get("scopes"), dict):
            scopes.update(str(name)[:100] for name in scheme["scopes"])
    return {"parsed": True, "endpoints": endpoints, "operations": operations,
            "oauth_scopes": sorted(scopes)[:40]}


class GitHubPublicProvider:
    name = "githubpublic"

    async def status(self) -> dict[str, Any]:
        return {"configured": True, "searchable": True, "executable": True,
                "scope": "public repositories only", "authentication": "none"}

    def _descriptors(self) -> dict[str, ToolDescriptor]:
        return {
            "search": ToolDescriptor(
                ref="githubpublic:search", provider=self.name, tool_id="search",
                name="Search public GitHub repositories",
                description="Find public repositories by topic, game, tool, language or API; return licensing and source links.",
                input_schema={"type": "object", "required": ["query"], "properties": {
                    "query": {"type": "string", "minLength": 2, "maxLength": 160},
                    "limit": {"type": "integer", "minimum": 1, "maximum": 10},
                }}, tags=["repository", "github", "search", "public"], requires_auth=False,
                side_effecting=False,
            ),
            "inspect": ToolDescriptor(
                ref="githubpublic:inspect", provider=self.name, tool_id="inspect",
                name="Inspect public repository and API specifications",
                description="Inspect one public repository's metadata, license, tree and up to three small OpenAPI specifications without cloning or executing code.",
                input_schema={"type": "object", "required": ["repository"], "properties": {
                    "repository": {"type": "string", "maxLength": 240},
                }}, tags=["repository", "github", "openapi", "oauth", "public"],
                requires_auth=False, side_effecting=False,
            ),
        }

    async def search(self, query: str, *, limit: int = 10) -> list[ToolDescriptor]:
        words = query.casefold().split()
        return [tool for tool in self._descriptors().values()
                if not words or any(word in (tool.name + " " + tool.description).casefold() for word in words)][:limit]

    async def describe(self, tool_id: str) -> ToolDescriptor:
        try:
            return self._descriptors()[tool_id]
        except KeyError as exc:
            raise PublicRepositoryError("Unknown repository tool.") from exc

    async def _get(self, path: str, *, params: dict[str, Any] | None, calls: list[str]) -> dict[str, Any]:
        calls.append(path.split("?")[0])
        try:
            async with (
                httpx.AsyncClient(timeout=12, follow_redirects=False) as client,
                client.stream(
                    "GET",
                    "https://api.github.com" + path,
                    params=params,
                    headers={
                        "Accept": "application/vnd.github+json",
                        "User-Agent": "InternetHands-PublicRepoResearch",
                    },
                ) as response,
            ):
                if response.status_code == 404:
                    raise PublicRepositoryError("Public GitHub resource not found.", 404)
                if response.status_code in {403, 429}:
                    raise PublicRepositoryError("GitHub request limit reached; try again later.", 429)
                if response.status_code >= 400:
                    raise PublicRepositoryError("GitHub could not complete this request.", 502)
                raw = bytearray()
                async for chunk in response.aiter_bytes():
                    raw.extend(chunk)
                    if len(raw) > _MAX_RESPONSE:
                        raise PublicRepositoryError("Repository listing is too large to inspect safely.", 413)
        except httpx.RequestError as exc:
            raise PublicRepositoryError("GitHub is temporarily unreachable.", 503) from exc
        try:
            result = json.loads(raw)
        except (ValueError, UnicodeDecodeError) as exc:
            raise PublicRepositoryError("GitHub returned an unreadable response.", 502) from exc
        if not isinstance(result, dict):
            raise PublicRepositoryError("GitHub returned an unexpected response.", 502)
        return result

    async def execute(self, tool_id: str, arguments: dict[str, Any], *, account: str | None = None,
                      wait_seconds: int = 30, timeout_seconds: int = 60,
                      options: dict[str, Any] | None = None) -> dict[str, Any]:
        del account, wait_seconds, timeout_seconds, options
        calls: list[str] = arguments.get("_usage_calls") if isinstance(arguments.get("_usage_calls"), list) else []
        if tool_id == "search":
            query = str(arguments.get("query") or "").strip()
            if len(query) < 2 or len(query) > 160:
                raise PublicRepositoryError("Search query must contain 2–160 characters.")
            try:
                limit = max(1, min(int(arguments.get("limit") or 8), 10))
            except (TypeError, ValueError) as exc:
                raise PublicRepositoryError("limit must be an integer from 1 to 10.") from exc
            data = await self._get("/search/repositories", params={"q": query + " is:public", "per_page": limit, "page": 1}, calls=calls)
            items = [{"name": item.get("full_name"), "description": item.get("description"),
                      "url": item.get("html_url"), "stars": item.get("stargazers_count"),
                      "language": item.get("language"), "updated_at": item.get("pushed_at"),
                      "license": (item.get("license") or {}).get("spdx_id")}
                     for item in (data.get("items") or []) if isinstance(item, dict)]
            return {"status": "completed", "data": {
                "query": query, "repositories": items, "total_count": data.get("total_count"),
                "incomplete_results": bool(data.get("incomplete_results")), "api_requests": len(calls)},
                "metadata": {"source": "GitHub REST API", "visibility": "public"}}

        if tool_id != "inspect":
            raise PublicRepositoryError("Unknown repository tool.")
        owner, repo = repository_parts(str(arguments.get("repository") or ""))
        root = f"/repos/{quote(owner)}/{quote(repo)}"
        metadata = await self._get(root, params=None, calls=calls)
        if metadata.get("private") or metadata.get("visibility") != "public":
            raise PublicRepositoryError("Only public repositories can be inspected.", 403)
        branch = str(metadata.get("default_branch") or "main")
        tree = await self._get(root + "/git/trees/" + quote(branch, safe=""),
                               params={"recursive": "1"}, calls=calls)
        blobs = [item for item in (tree.get("tree") or []) if isinstance(item, dict)
                 and item.get("type") == "blob" and isinstance(item.get("path"), str)][:5000]
        files = [{"path": item["path"], "size": item.get("size"),
                  "url": f"https://github.com/{quote(owner)}/{quote(repo)}/blob/{quote(branch, safe='')}/{quote(item['path'])}"}
                 for item in blobs if _SPEC.search(item["path"]) or _API_PATH.search(item["path"])][:60]
        specs = []
        for item in (item for item in blobs if _SPEC.search(item["path"]) and 0 < int(item.get("size") or 0) <= 96000):
            if len(specs) >= 3 or len(calls) >= 5:
                break
            path = item["path"]
            encoded = quote(path, safe="/")
            try:
                data = await self._get(root + "/contents/" + encoded, params={"ref": branch}, calls=calls)
            except PublicRepositoryError:
                # A moving repository may remove a candidate file between tree
                # and contents calls. The remaining findings are still useful.
                continue
            try:
                contents = base64.b64decode(str(data.get("content") or ""), validate=False)
            except ValueError:
                continue
            if len(contents) > 96000:
                continue
            specs.append({"path": path,
                          "url": f"https://github.com/{quote(owner)}/{quote(repo)}/blob/{quote(branch, safe='')}/{quote(path)}",
                          **_spec_summary(contents)})
        return {"status": "completed", "data": {"repository": metadata.get("full_name"), "url": metadata.get("html_url"),
                "description": metadata.get("description"), "license": (metadata.get("license") or {}).get("spdx_id"),
                "stars": metadata.get("stargazers_count"), "language": metadata.get("language"),
                "default_branch": branch, "pushed_at": metadata.get("pushed_at"),
                "tree_truncated": bool(tree.get("truncated")) or len(blobs) >= 5000,
                "candidate_files": files, "api_specs": specs, "api_requests": len(calls)},
                "metadata": {"source": "GitHub REST API", "visibility": "public"}}
