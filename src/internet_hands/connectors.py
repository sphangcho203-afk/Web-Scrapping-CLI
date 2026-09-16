"""Custom connectors for Vercel and Neon using REST API access tokens.

Provides async client classes for:
- NeonConnector: Manage serverless Postgres projects, branches, compute endpoints, and connection strings.
- VercelConnector: Manage Vercel projects, deployments, and project environment variables.
- VercelNeonBridge: Seamlessly inject and synchronize Neon database credentials directly into Vercel projects.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Any
from urllib.parse import quote

import httpx


class ConnectorError(RuntimeError):
    """Base exception for connector errors."""


class NeonConnectorError(ConnectorError):
    """Exception raised by Neon connector."""


class VercelConnectorError(ConnectorError):
    """Exception raised by Vercel connector."""



@dataclass
class NeonProjectInfo:
    id: str
    name: str
    region_id: str
    pg_version: int
    created_at: str


@dataclass
class VercelProjectInfo:
    id: str
    name: str
    framework: str | None
    updated_at: int | None


class NeonConnector:
    """Async client for the Neon Serverless Postgres API (v2)."""

    def __init__(
        self,
        api_key: str | None = None,
        base_url: str = "https://console.neon.tech/api/v2",
        client: httpx.AsyncClient | None = None,
    ) -> None:
        self.api_key = api_key or os.getenv("NEON_API_KEY") or os.getenv("NEON_API_TOKEN")
        self.base_url = base_url.rstrip("/")
        self._client = client

    def _headers(self) -> dict[str, str]:
        if not self.api_key:
            raise NeonConnectorError("Neon API key is not configured. Set NEON_API_KEY or provide api_key.")
        return {
            "Authorization": f"Bearer {self.api_key}",
            "Accept": "application/json",
            "Content-Type": "application/json",
        }

    async def _request(self, method: str, path: str, **kwargs: Any) -> Any:
        headers = self._headers()
        headers.update(kwargs.pop("headers", {}))
        client = self._client or httpx.AsyncClient(timeout=30)
        try:
            res = await client.request(method, f"{self.base_url}{path}", headers=headers, **kwargs)
            if res.is_error:
                detail = res.text[:1000]
                raise NeonConnectorError(f"Neon API error {res.status_code}: {detail}")
            return res.json()
        except httpx.RequestError as exc:
            raise NeonConnectorError(f"Failed to communicate with Neon API: {exc}") from exc
        finally:
            if self._client is None:
                await client.aclose()

    async def verify_token(self) -> dict[str, Any]:
        """Verify API key by querying user/projects."""
        res = await self._request("GET", "/projects?limit=1")
        return {"status": "valid", "project_count": len(res.get("projects", []))}

    async def list_projects(self) -> list[dict[str, Any]]:
        """List all serverless Postgres projects."""
        res = await self._request("GET", "/projects")
        return res.get("projects", [])

    async def get_project(self, project_id: str) -> dict[str, Any]:
        """Retrieve details of a specific project."""
        res = await self._request("GET", f"/projects/{quote(project_id)}")
        return res.get("project", res)

    async def list_branches(self, project_id: str) -> list[dict[str, Any]]:
        """List branches for a project."""
        res = await self._request("GET", f"/projects/{quote(project_id)}/branches")
        return res.get("branches", [])

    async def list_endpoints(self, project_id: str) -> list[dict[str, Any]]:
        """List compute endpoints for a project."""
        res = await self._request("GET", f"/projects/{quote(project_id)}/endpoints")
        return res.get("endpoints", [])

    async def get_connection_uri(
        self,
        project_id: str,
        database_name: str = "neondb",
        role_name: str = "neondb_owner",
        pooled: bool = True,
    ) -> str:
        """Fetch connection URI for a project, branch, and role with connection pooler support."""
        res = await self._request(
            "GET",
            f"/projects/{quote(project_id)}/connection_uri",
            params={
                "database_name": database_name,
                "role_name": role_name,
                "pooled": str(pooled).lower(),
            },
        )
        return res.get("uri", "")


class VercelConnector:
    """Async client for the Vercel REST API (v2/v9/v10)."""

    def __init__(
        self,
        token: str | None = None,
        team_id: str | None = None,
        base_url: str = "https://api.vercel.com",
        client: httpx.AsyncClient | None = None,
    ) -> None:
        self.token = (
            token
            or os.getenv("VERCEL_TOKEN")
            or os.getenv("INTERNET_HANDS_VERCEL_TOKEN")
            or os.getenv("VERCEL_OIDC_TOKEN")
        )
        self.team_id = team_id or os.getenv("VERCEL_TEAM_ID")
        self.base_url = base_url.rstrip("/")
        self._client = client

    def _headers(self) -> dict[str, str]:
        if not self.token:
            raise VercelConnectorError("Vercel token is not configured. Set VERCEL_TOKEN or provide token.")
        return {
            "Authorization": f"Bearer {self.token}",
            "Accept": "application/json",
            "Content-Type": "application/json",
        }

    def _params(self, extra: dict[str, Any] | None = None) -> dict[str, Any]:
        params = dict(extra or {})
        if self.team_id:
            params["teamId"] = self.team_id
        return params

    async def _request(self, method: str, path: str, **kwargs: Any) -> Any:
        headers = self._headers()
        headers.update(kwargs.pop("headers", {}))
        params = self._params(kwargs.pop("params", None))
        client = self._client or httpx.AsyncClient(timeout=30)
        try:
            res = await client.request(
                method,
                f"{self.base_url}{path}",
                headers=headers,
                params=params,
                **kwargs,
            )
            if res.is_error:
                detail = res.text[:1000]
                raise VercelConnectorError(f"Vercel API error {res.status_code}: {detail}")
            return res.json()
        except httpx.RequestError as exc:
            raise VercelConnectorError(f"Failed to communicate with Vercel API: {exc}") from exc
        finally:
            if self._client is None:
                await client.aclose()

    async def verify_token(self) -> dict[str, Any]:
        """Verify Vercel token and return user profile information."""
        res = await self._request("GET", "/v2/user")
        return res.get("user", res)

    async def list_projects(self, limit: int = 50) -> list[dict[str, Any]]:
        """List Vercel projects."""
        res = await self._request("GET", "/v9/projects", params={"limit": limit})
        return res.get("projects", [])

    async def get_project(self, project_id_or_name: str) -> dict[str, Any]:
        """Retrieve details of a specific Vercel project."""
        return await self._request("GET", f"/v9/projects/{quote(project_id_or_name)}")

    async def list_env_vars(self, project_id_or_name: str) -> list[dict[str, Any]]:
        """List all environment variables configured for a project."""
        res = await self._request("GET", f"/v10/projects/{quote(project_id_or_name)}/env")
        return res.get("envs", [])

    async def upsert_env_vars(
        self,
        project_id_or_name: str,
        env_map: dict[str, str],
        targets: list[str] | None = None,
    ) -> dict[str, Any]:
        """Create or update multiple environment variables in a Vercel project.
        
        Targets default to ['production', 'preview', 'development'].
        """
        if targets is None:
            targets = ["production", "preview", "development"]

        existing_envs = await self.list_env_vars(project_id_or_name)
        existing_keys = {env["key"]: env["id"] for env in existing_envs if "key" in env and "id" in env}

        results = {}
        for key, value in env_map.items():
            payload = {
                "key": key,
                "value": value,
                "type": "encrypted",
                "target": targets,
            }
            if key in existing_keys:
                # Update existing environment variable
                env_id = existing_keys[key]
                res = await self._request(
                    "PATCH",
                    f"/v10/projects/{quote(project_id_or_name)}/env/{env_id}",
                    json={"value": value, "target": targets},
                )
                results[key] = {"action": "updated", "id": env_id}
            else:
                # Create new environment variable
                res = await self._request(
                    "POST",
                    f"/v10/projects/{quote(project_id_or_name)}/env",
                    json=payload,
                )
                results[key] = {"action": "created", "id": res.get("id")}

        return results


class VercelNeonBridge:
    """Bridge orchestrator connecting Neon Serverless Postgres with Vercel deployment."""

    def __init__(
        self,
        neon: NeonConnector | None = None,
        vercel: VercelConnector | None = None,
    ) -> None:
        self.neon = neon or NeonConnector()
        self.vercel = vercel or VercelConnector()

    async def check_status(self) -> dict[str, Any]:
        """Test status and identity for both connectors."""
        neon_status = {"configured": bool(self.neon.api_key), "valid": False}
        if self.neon.api_key:
            try:
                info = await self.neon.verify_token()
                neon_status.update({"valid": True, "info": info})
            except Exception as exc:
                neon_status["error"] = str(exc)

        vercel_status = {"configured": bool(self.vercel.token), "valid": False}
        if self.vercel.token:
            try:
                user = await self.vercel.verify_token()
                vercel_status.update({"valid": True, "user": user.get("username") or user.get("email")})
            except Exception as exc:
                vercel_status["error"] = str(exc)

        return {
            "neon": neon_status,
            "vercel": vercel_status,
            "bridge_ready": neon_status.get("valid", False) and vercel_status.get("valid", False),
        }

    async def sync_neon_to_vercel(
        self,
        neon_project_id: str,
        vercel_project_id_or_name: str,
        database_name: str = "neondb",
        role_name: str = "neondb_owner",
        targets: list[str] | None = None,
    ) -> dict[str, Any]:
        """Generate Neon connection URIs and inject them directly into the Vercel project environment."""
        # 1. Fetch pooled URI (optimal for serverless functions / fleet workers)
        pooled_uri = await self.neon.get_connection_uri(
            neon_project_id,
            database_name=database_name,
            role_name=role_name,
            pooled=True,
        )

        # 2. Fetch direct unpooled URI (for migrations)
        direct_uri = await self.neon.get_connection_uri(
            neon_project_id,
            database_name=database_name,
            role_name=role_name,
            pooled=False,
        )

        # Map environment variables standard across Vercel and Internet Hands
        env_map = {
            "DATABASE_URL": pooled_uri,
            "POSTGRES_URL": pooled_uri,
            "POSTGRES_PRISMA_URL": pooled_uri,
            "POSTGRES_URL_NON_POOLING": direct_uri,
            "INTERNET_HANDS_POSTGRES_DSN": pooled_uri,
            "INTERNET_HANDS_CONTENT_POSTGRES_DSN": pooled_uri,
        }

        # 3. Synchronize to Vercel
        sync_results = await self.vercel.upsert_env_vars(
            vercel_project_id_or_name,
            env_map,
            targets=targets,
        )

        return {
            "success": True,
            "neon_project_id": neon_project_id,
            "vercel_project": vercel_project_id_or_name,
            "synced_keys": list(env_map.keys()),
            "details": sync_results,
        }
