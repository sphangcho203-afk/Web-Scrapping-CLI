from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse, HTMLResponse, Response

router = APIRouter()
WEB_ROOT = Path(__file__).resolve().parents[2] / "web"

NO_STORE_HEADERS = {
    "Cache-Control": "no-store, no-cache, must-revalidate, max-age=0",
    "Pragma": "no-cache",
    "Expires": "0",
}


# Keep web assets explicit: the console can evolve without exposing arbitrary files
# from the repository through /assets.
ASSET_MEDIA_TYPES = {
    "cognitive-foundation.css": "text/css",
    "app.js": "application/javascript",
    "mark.svg": "image/svg+xml",
    "internet-hands-mark.webp": "image/webp",
    "internet-hands-logo.webp": "image/webp",
    "opencrawl-robot.png": "image/png",
    "opencrawl-crab.png": "image/png",
    "glass-orbit.webp": "image/webp",
    "glass-portal.webp": "image/webp",
    "glass-globe.webp": "image/webp",
    "inter-latin-variable.woff2": "font/woff2",
    "inter-latin-ext-variable.woff2": "font/woff2",
    "inter-license.txt": "text/plain",
}


def _file(name: str, media_type: str | None = None, *, no_store: bool = False):
    path = WEB_ROOT / name
    if not path.is_file():
        raise HTTPException(status_code=404, detail="asset not found")
    return FileResponse(
        path,
        media_type=media_type,
        headers=NO_STORE_HEADERS if no_store else None,
    )


def _browser_runtime() -> Response:
    """Ship one runtime while keeping bounded feature source reviewable."""
    legal = WEB_ROOT / "legal-content.js"
    docs = WEB_ROOT / "docs-content.js"
    runtime = WEB_ROOT / "app.js"
    usage = WEB_ROOT / "usage-intelligence.js"
    monitors = WEB_ROOT / "monitor-lifecycle.js"
    datasets = WEB_ROOT / "datasets.js"
    crawl_runs = WEB_ROOT / "crawl-runs.js"
    sources = [legal, docs, runtime, usage, monitors, datasets, crawl_runs]
    sources.append(WEB_ROOT / "runs.js")
    sources.append(WEB_ROOT / "product-tracker.js")
    sources.append(WEB_ROOT / "sandbox-workbench.js")
    sources.append(WEB_ROOT / "depth-effects.js")
    sources.append(WEB_ROOT / "home-experience.js")
    if any(not source.is_file() for source in sources):
        raise HTTPException(status_code=404, detail="asset not found")
    content = "\n\n".join(source.read_text(encoding="utf-8") for source in sources)
    return Response(
        content=content,
        media_type="application/javascript",
        headers=NO_STORE_HEADERS,
    )


@router.get("/assets/{name}")
def site_asset(name: str):
    media_type = ASSET_MEDIA_TYPES.get(name)
    if media_type is None:
        raise HTTPException(status_code=404, detail="asset not found")
    if name == "app.js":
        return _browser_runtime()
    return _file(name, media_type, no_store=name == "cognitive-foundation.css")


def _index():
    path = WEB_ROOT / "index.html"
    if not path.is_file():
        return HTMLResponse("OpenCrawl web console is not packaged", status_code=503)
    return FileResponse(path, media_type="text/html", headers=NO_STORE_HEADERS)


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


@router.get("/legal")
def legal_page():
    return _index()


@router.get("/legal/{path:path}")
def legal_nested(path: str):
    return _index()


@router.get("/terms")
def terms_page():
    return _index()


@router.get("/privacy")
def privacy_page():
    return _index()


@router.get("/acceptable-use")
def acceptable_use_page():
    return _index()


@router.get("/cookies")
def cookies_page():
    return _index()


@router.get("/billing-policy")
def billing_policy_page():
    return _index()


@router.get("/security")
def security_policy_page():
    return _index()


@router.get("/dashboard")
def dashboard_page():
    return _index()


@router.get("/dashboard/{path:path}")
def dashboard_nested(path: str):
    return _index()
