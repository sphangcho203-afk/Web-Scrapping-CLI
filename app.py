from __future__ import annotations

import sys
from pathlib import Path

SRC = Path(__file__).resolve().parent / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from internet_hands.api import app as core_api
from internet_hands.connectors_api import router as connectors_router
from internet_hands.fleet_api import app

# Enable CORS for browser access and local development
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Mount Vercel & Neon custom connectors API router
app.include_router(connectors_router)

# Unify core intelligence/scraping routes into fleet control plane
existing_paths = {route.path for route in app.routes}
for route in core_api.routes:
    if route.path not in existing_paths:
        app.routes.append(route)

# Mount Web Studio UI
web_dir = SRC / "internet_hands" / "web"
if web_dir.is_dir():
    app.mount("/", StaticFiles(directory=str(web_dir), html=True), name="web")
