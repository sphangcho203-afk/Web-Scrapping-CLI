from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse, HTMLResponse

router = APIRouter()
WEB_ROOT = Path(__file__).resolve().parents[2] / "web"


# Keep web assets explicit: the console can evolve without exposing arbitrary files
# from the repository through /assets.
ASSET_MEDIA_TYPES = {
    "app.css": "text/css",
    "product-ui.css": "text/css",
    "product-ui-extended.css": "text/css",
    "editorial-ui.css": "text/css",
    "editorial-fixes.css": "text/css",
    "command-os.css": "text/css",
    "command-os-polish.css": "text/css",
    "brand-logo.css": "text/css",
    "cognitive-foundation.css": "text/css",
    "app.js": "application/javascript",
    "product-ui.js": "application/javascript",
    "product-ui-extended.js": "application/javascript",
    "editorial-ui.js": "application/javascript",
    "legacy-controls.js": "application/javascript",
    "command-os.js": "application/javascript",
    "command-os-polish.js": "application/javascript",
    "brand-logo.js": "application/javascript",
    "cognitive-overview.js": "application/javascript",
    "security.js": "application/javascript",
    "recovery.js": "application/javascript",
    "auth-nav.js": "application/javascript",
    "mark.svg": "image/svg+xml",
    "internet-hands-mark.webp": "image/webp",
    "internet-hands-logo.webp": "image/webp",
}


def _file(name: str, media_type: str | None = None):
    path = WEB_ROOT / name
    if not path.is_file():
        raise HTTPException(status_code=404, detail="asset not found")
    return FileResponse(path, media_type=media_type)


@router.get("/assets/{name}")
def site_asset(name: str):
    media_type = ASSET_MEDIA_TYPES.get(name)
    if media_type is None:
        raise HTTPException(status_code=404, detail="asset not found")
    return _file(name, media_type)


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


@router.get("/verify-email")
def verify_email_page():
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
