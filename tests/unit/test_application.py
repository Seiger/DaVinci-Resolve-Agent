"""Application-service boundary tests."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

import pytest

from agent.application import AgentApplication


class StubResolveReader:
    def __init__(self) -> None:
        self.timeouts: list[float] = []

    def current_project(self, timeout_seconds: float = 30) -> dict[str, Any]:
        self.timeouts.append(timeout_seconds)
        return {"name": "Test Project"}

    def timelines(self, timeout_seconds: float = 30) -> list[dict[str, Any]]:
        self.timeouts.append(timeout_seconds)
        return [{"index": 1, "name": "Main"}]

    def current_timeline(self, timeout_seconds: float = 30) -> dict[str, Any]:
        self.timeouts.append(timeout_seconds)
        return {"name": "Main"}

    def import_media(
        self,
        paths: list[str],
        *,
        timeout_seconds: float = 30,
        idempotency_key: str | None = None,
    ) -> dict[str, Any]:
        self.timeouts.append(timeout_seconds)
        return {"items": [{"asset_id": "asset-1", "name": paths[0]}]}

    def create_timeline(
        self,
        name: str,
        *,
        timeout_seconds: float = 30,
        idempotency_key: str | None = None,
    ) -> dict[str, Any]:
        self.timeouts.append(timeout_seconds)
        return {"timeline": {"timeline_id": "timeline-1", "name": name}}

    def append_clip(
        self,
        timeline_id: str,
        asset_id: str,
        *,
        timeout_seconds: float = 30,
        idempotency_key: str | None = None,
    ) -> dict[str, Any]:
        self.timeouts.append(timeout_seconds)
        return {"timeline_id": timeline_id, "asset_id": asset_id}

    def add_marker(
        self,
        timeline_id: str,
        frame: int,
        color: str,
        name: str,
        note: str,
        duration: int,
        *,
        timeout_seconds: float = 30,
        idempotency_key: str | None = None,
    ) -> dict[str, Any]:
        self.timeouts.append(timeout_seconds)
        return {"timeline_id": timeline_id, "frame": frame, "color": color}


class StubMediaPolicy:
    def __init__(self) -> None:
        self.paths: list[str] = []

    def prepare_import(self, paths: list[str]) -> list[str]:
        self.paths = paths
        return [f"normalized:{path}" for path in paths]


def _fresh_state() -> dict[str, Any]:
    return {
        "bridge_version": "0.1.0",
        "protocol_version": "1.0",
        "status": "ready",
        "last_heartbeat": datetime.now(timezone.utc).isoformat(),
        "capabilities": {"bridge.ping": True},
    }


def test_application_exposes_status_and_read_only_provider_methods() -> None:
    resolve = StubResolveReader()
    application = AgentApplication(resolve=resolve, state_loader=_fresh_state)

    status = application.status()

    assert status["healthy"] is True
    assert status["bridge"]["status"] == "ready"
    assert application.resolve_get_project(10) == {"name": "Test Project"}
    assert application.resolve_list_timelines(20) == [
        {"index": 1, "name": "Main"}
    ]
    assert application.resolve_get_timeline(30) == {"name": "Main"}
    assert resolve.timeouts == [10, 20, 30]


def test_application_exposes_validated_write_methods() -> None:
    resolve = StubResolveReader()
    media_policy = StubMediaPolicy()
    application = AgentApplication(
        resolve=resolve,
        media_policy=media_policy,
    )

    imported = application.resolve_import_media(
        ["sample.wav"],
        timeout_seconds=10,
    )
    created = application.resolve_create_timeline(
        "M4 Timeline",
        timeout_seconds=20,
    )
    appended = application.resolve_append_clip(
        "timeline-1",
        "asset-1",
        timeout_seconds=30,
    )
    marker = application.resolve_add_marker(
        "timeline-1",
        0,
        "Green",
        timeout_seconds=40,
    )

    assert media_policy.paths == ["sample.wav"]
    assert imported["items"][0]["name"] == "normalized:sample.wav"
    assert created["timeline"]["name"] == "M4 Timeline"
    assert appended["asset_id"] == "asset-1"
    assert marker["color"] == "Green"
    assert resolve.timeouts == [10, 20, 30, 40]


@pytest.mark.parametrize("timeout_seconds", [0, -1, 301])
def test_application_rejects_unsafe_timeout(timeout_seconds: float) -> None:
    application = AgentApplication(resolve=StubResolveReader())

    with pytest.raises(ValueError, match="timeout_seconds"):
        application.resolve_get_project(timeout_seconds)
