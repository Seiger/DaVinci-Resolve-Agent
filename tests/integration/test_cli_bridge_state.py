"""CLI integration against a filesystem bridge snapshot."""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

import pytest

from agent.cli import main
from agent.paths import runtime_directory
from transports.filesystem import atomic_write_json


def _write_state(local_app_data: Path) -> None:
    environment = {"LOCALAPPDATA": str(local_app_data)}
    path = runtime_directory(environment) / "state" / "bridge.json"
    atomic_write_json(
        path,
        {
            "protocol_version": "1.0",
            "bridge_version": "0.1.0",
            "status": "ready",
            "last_heartbeat": datetime.now(timezone.utc)
            .isoformat()
            .replace("+00:00", "Z"),
            "product_name": "DaVinci Resolve",
            "resolve_version": "21.0.3.7",
            "project_name": "CLI Test Project",
            "current_timeline_name": "Main",
            "capabilities": {"bridge.ping": True},
        },
    )


def test_cached_status_command(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))
    _write_state(tmp_path)

    assert main(["status"]) == 0
    status_output = capsys.readouterr().out
    assert "Bridge: ready" in status_output
    assert "Project: CLI Test Project" in status_output

