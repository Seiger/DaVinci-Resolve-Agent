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


@pytest.mark.parametrize("timeout_seconds", [0, -1, 301])
def test_application_rejects_unsafe_timeout(timeout_seconds: float) -> None:
    application = AgentApplication(resolve=StubResolveReader())

    with pytest.raises(ValueError, match="timeout_seconds"):
        application.resolve_get_project(timeout_seconds)
