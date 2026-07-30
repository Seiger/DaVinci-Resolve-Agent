"""Bridge state validation and freshness tests."""

from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from agent.bridge_state import (
    BridgeStateError,
    bridge_is_healthy,
    heartbeat_age_seconds,
    load_bridge_state,
)
from transports.filesystem import FilesystemLayout, atomic_write_json


def _state(heartbeat: datetime) -> dict[str, object]:
    return {
        "bridge_version": "0.1.0",
        "protocol_version": "1.0",
        "status": "ready",
        "last_heartbeat": heartbeat.isoformat().replace("+00:00", "Z"),
        "capabilities": {"bridge.ping": True},
    }


def test_bridge_state_loads_and_reports_freshness(tmp_path: Path) -> None:
    now = datetime(2026, 7, 30, 12, 0, tzinfo=timezone.utc)
    layout = FilesystemLayout(tmp_path)
    layout.ensure_directories()
    atomic_write_json(layout.state / "bridge.json", _state(now - timedelta(seconds=5)))

    loaded = load_bridge_state(tmp_path)

    assert heartbeat_age_seconds(loaded, now) == 5
    assert bridge_is_healthy(loaded, max_age_seconds=10, now=now)
    assert not bridge_is_healthy(loaded, max_age_seconds=4, now=now)


def test_missing_bridge_state_has_actionable_error(tmp_path: Path) -> None:
    with pytest.raises(BridgeStateError, match="Workspace > Scripts > Edit"):
        load_bridge_state(tmp_path)

