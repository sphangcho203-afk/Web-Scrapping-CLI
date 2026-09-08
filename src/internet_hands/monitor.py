from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

from .fetcher import fetch_url
from .models import MonitorResult, MonitorState


async def monitor_once(url: str, state_path: Path) -> MonitorResult:
    result = await fetch_url(url, include_body=False)
    current = MonitorState(
        url=result.final_url,
        sha256=result.sha256,
        checked_at=datetime.now(timezone.utc),
        status_code=result.status_code,
        content_length=result.content_length,
    )

    previous = None
    if state_path.exists():
        previous = MonitorState.model_validate_json(state_path.read_text(encoding="utf-8"))

    state_path.parent.mkdir(parents=True, exist_ok=True)
    state_path.write_text(current.model_dump_json(indent=2), encoding="utf-8")
    changed = previous is None or previous.sha256 != current.sha256
    return MonitorResult(changed=changed, previous=previous, current=current)
