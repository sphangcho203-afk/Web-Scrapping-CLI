"""FastAPI routes for the Vercel and Neon custom connectors."""

from __future__ import annotations

from typing import Annotated, Any

from fastapi import APIRouter, Header, HTTPException, Query
from pydantic import BaseModel, Field

from .connectors import (
    NeonConnector,
    NeonConnectorError,
    VercelConnector,
    VercelConnectorError,
    VercelNeonBridge,
)

router = APIRouter(prefix="/v1/connectors", tags=["connectors"])


class SyncRequest(BaseModel):
    neon_project_id: str = Field(..., description="ID of the source Neon project")
    vercel_project_id_or_name: str = Field(..., description="Target Vercel project ID or name")
    database_name: str = Field(default="neondb", description="Postgres database name")
    role_name: str = Field(default="neondb_owner", description="Postgres role name")
    targets: list[str] = Field(
        default=["production", "preview", "development"],
        description="Vercel deployment targets",
    )


def _get_bridge(
    x_vercel_token: str | None = None,
    x_neon_key: str | None = None,
) -> VercelNeonBridge:
    neon = NeonConnector(api_key=x_neon_key)
    vercel = VercelConnector(token=x_vercel_token)
    return VercelNeonBridge(neon=neon, vercel=vercel)


@router.get("/status")
async def get_connector_status(
    x_vercel_token: Annotated[str | None, Header(alias="X-Vercel-Token")] = None,
    x_neon_key: Annotated[str | None, Header(alias="X-Neon-Key")] = None,
) -> dict[str, Any]:
    """Check connectivity and credentials for Vercel and Neon."""
    bridge = _get_bridge(x_vercel_token=x_vercel_token, x_neon_key=x_neon_key)
    return await bridge.check_status()


@router.get("/neon/projects")
async def list_neon_projects(
    x_neon_key: Annotated[str | None, Header(alias="X-Neon-Key")] = None,
) -> list[dict[str, Any]]:
    """List serverless Postgres projects from Neon."""
    connector = NeonConnector(api_key=x_neon_key)
    try:
        return await connector.list_projects()
    except NeonConnectorError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get("/neon/branches")
async def list_neon_branches(
    project_id: Annotated[str, Query(description="Neon project ID")],
    x_neon_key: Annotated[str | None, Header(alias="X-Neon-Key")] = None,
) -> list[dict[str, Any]]:
    """List branches for a Neon project."""
    connector = NeonConnector(api_key=x_neon_key)
    try:
        return await connector.list_branches(project_id)
    except NeonConnectorError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get("/neon/connection-uri")
async def get_neon_connection_uri(
    project_id: Annotated[str, Query(description="Neon project ID")],
    database_name: Annotated[str, Query()] = "neondb",
    role_name: Annotated[str, Query()] = "neondb_owner",
    pooled: Annotated[bool, Query()] = True,
    x_neon_key: Annotated[str | None, Header(alias="X-Neon-Key")] = None,
) -> dict[str, str]:
    """Generate a connection string from Neon with optional pooling."""
    connector = NeonConnector(api_key=x_neon_key)
    try:
        uri = await connector.get_connection_uri(
            project_id=project_id,
            database_name=database_name,
            role_name=role_name,
            pooled=pooled,
        )
        return {"project_id": project_id, "uri": uri, "pooled": str(pooled)}
    except NeonConnectorError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get("/vercel/projects")
async def list_vercel_projects(
    x_vercel_token: Annotated[str | None, Header(alias="X-Vercel-Token")] = None,
    limit: Annotated[int, Query(ge=1, le=100)] = 50,
) -> list[dict[str, Any]]:
    """List Vercel projects."""
    connector = VercelConnector(token=x_vercel_token)
    try:
        return await connector.list_projects(limit=limit)
    except VercelConnectorError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/sync")
async def sync_neon_to_vercel(
    req: SyncRequest,
    x_vercel_token: Annotated[str | None, Header(alias="X-Vercel-Token")] = None,
    x_neon_key: Annotated[str | None, Header(alias="X-Neon-Key")] = None,
) -> dict[str, Any]:
    """Synchronize Neon Postgres connection strings into Vercel project environment variables."""
    bridge = _get_bridge(x_vercel_token=x_vercel_token, x_neon_key=x_neon_key)
    try:
        return await bridge.sync_neon_to_vercel(
            neon_project_id=req.neon_project_id,
            vercel_project_id_or_name=req.vercel_project_id_or_name,
            database_name=req.database_name,
            role_name=req.role_name,
            targets=req.targets,
        )
    except (NeonConnectorError, VercelConnectorError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
