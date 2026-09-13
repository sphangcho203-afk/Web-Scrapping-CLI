from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse, HTMLResponse

router = APIRouter()
WEB_ROOT = Path(__file__).resolve().parents[2] / "web"


def _file(name: str, media_type: str | None = None):
    path = WEB_ROOT / name
    if not path.is_file():
        raise HTTPException(status_code=404, detail="asset not found")
    return FileResponse(path, media_type=media_type)


@router.get("/assets/app.css")
def site_css():
    return _file("app.css", "text/css")


@router.get("/assets/app.js")
def site_js():
    return _file("app.js", "application/javascript")


@router.get("/assets/mark.svg")
def site_mark():
    return _file("mark.svg", "image/svg+xml")


def _index():
    path = WEB_ROOT / "index.html"
    if not path.is_file():
        return HTMLResponse("Internet Hands web console is not packaged", status_code=503)
    return FileResponse(path, media_type="text/html")


@router.get("/")
def home():
    return _index()


@router.get("/pricing")
def pricing():
    return _index()


@router.get("/status")
def status_page():
    return _index()


@router.get("/login")
def login_page():
    return _index()


@router.get("/signup")
def signup_page():
    return _index()


@router.get("/forgot-password")
def forgot_password_page():
    return _index()


@router.get("/reset-password")
def reset_password_page():
    return _index()


@router.get("/docs")
def docs_page():
    return _index()


@router.get("/docs/{path:path}")
def docs_nested(path: str):
    return _index()


@router.get("/dashboard")
def dashboard_page():
    return _index()


@router.get("/dashboard/{path:path}")
def dashboard_nested(path: str):
    return _index()
