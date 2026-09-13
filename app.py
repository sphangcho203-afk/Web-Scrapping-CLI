from __future__ import annotations

import sys
from pathlib import Path

# Dedicated Vercel preview entrypoint for the no-auth read-only MCP connector test.
SRC = Path(__file__).resolve().parent / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from internet_hands.public_test_app import app  # noqa: E402,F401
