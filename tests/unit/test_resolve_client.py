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
        idempotency_key: str | None = None,
        create_backup: bool = False,
    ) -> Any:
        assert provider == "resolve"
        assert timeout_seconds > 0
        if action in {
            "import_media",
            "create_timeline",
            "append_clip",
            "add_marker",
        }:
            assert arguments is not None
            assert create_backup is True
            assert idempotency_key == "stable-key"
        else:
            assert arguments is None
            assert create_backup is False
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
            "import_media": {
                "items": [{"asset_id": "asset-1", "name": "sample.wav"}]
            },
            "create_timeline": {
                "timeline": {
                    "timeline_id": "timeline-1",
                    "name": "M4 Timeline",
                }
            },
            "append_clip": {
                "timeline_id": "timeline-1",
                "asset_id": "asset-1",
            },
            "add_marker": {
                "timeline_id": "timeline-1",
                "frame": 0,
                "color": "Green",
            },
        }
    )
    client = ResolveProviderClient(command_client)

    assert client.ping() == "pong"
    assert client.capabilities()["bridge.ping"] is True
    assert client.current_project() == {"name": "Test Project"}
    assert client.timelines() == [{"index": 1, "name": "Main"}]
    assert client.current_timeline() == {"name": "Main"}
    assert client.import_media(
        ["sample.wav"],
        idempotency_key="stable-key",
    )["items"][0]["asset_id"] == "asset-1"
    assert client.create_timeline(
        "M4 Timeline",
        idempotency_key="stable-key",
    )["timeline"]["timeline_id"] == "timeline-1"
    assert client.append_clip(
        "timeline-1",
        "asset-1",
        idempotency_key="stable-key",
    )["asset_id"] == "asset-1"
    assert client.add_marker(
        "timeline-1",
        0,
        "Green",
        "",
        "",
        1,
        idempotency_key="stable-key",
    )["frame"] == 0
    assert command_client.actions == [
        "ping",
        "get_capabilities",
        "get_current_project",
        "list_timelines",
        "get_current_timeline",
        "import_media",
        "create_timeline",
        "append_clip",
        "add_marker",
    ]
