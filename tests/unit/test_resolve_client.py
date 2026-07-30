"""Typed Resolve provider-client tests."""

from __future__ import annotations

from typing import Any

from providers.resolve.client import ResolveProviderClient


class StubCommandClient:
    def __init__(self, results: dict[str, Any]) -> None:
        self._results = results
        self.actions: list[str] = []

    def request(
        self,
        *,
        provider: str,
        action: str,
        arguments: dict[str, Any] | None = None,
        timeout_seconds: float = 30,
    ) -> Any:
        assert provider == "resolve"
        assert arguments is None
        assert timeout_seconds > 0
        self.actions.append(action)
        return self._results[action]


def test_resolve_client_exposes_typed_read_only_methods() -> None:
    command_client = StubCommandClient(
        {
            "ping": {"message": "pong"},
            "get_capabilities": {
                "bridge.ping": True,
                "timeline.create": "unknown",
            },
            "get_current_project": {"name": "Test Project"},
            "list_timelines": [{"index": 1, "name": "Main"}],
            "get_current_timeline": {"name": "Main"},
        }
    )
    client = ResolveProviderClient(command_client)

    assert client.ping() == "pong"
    assert client.capabilities()["bridge.ping"] is True
    assert client.current_project() == {"name": "Test Project"}
    assert client.timelines() == [{"index": 1, "name": "Main"}]
    assert client.current_timeline() == {"name": "Main"}
    assert command_client.actions == [
        "ping",
        "get_capabilities",
        "get_current_project",
        "list_timelines",
        "get_current_timeline",
    ]

