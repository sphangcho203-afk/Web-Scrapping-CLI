from __future__ import annotations

import sys
from pathlib import Path

# Temporary v0.5 preview entrypoint for ChatGPT MCP connector testing.
SRC = Path(__file__).resolve().parent / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from internet_hands.public_test_app import app  # noqa: E402,F401
