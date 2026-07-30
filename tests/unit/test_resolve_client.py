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
            "set_current_timeline",
            "append_clip",
            "insert_clip",
            "set_clip_enabled",
            "add_marker",
            "prepare_render_job",
            "start_render_job",
        }:
            assert arguments is not None
            assert create_backup is True
            assert idempotency_key == "stable-key"
        elif action == "get_render_job_status":
            assert arguments == {"job_id": "job-1"}
            assert create_backup is False
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
            "get_render_environment": {
                "formats": [],
                "current": {"format": "mp4", "codec": "H264"},
                "presets": [],
                "jobs": [],
                "mp4_h264_resolutions": [
                    {"width": 1920, "height": 1080}
                ],
            },
            "import_media": {
                "items": [{"asset_id": "asset-1", "name": "sample.wav"}]
            },
            "create_timeline": {
                "timeline": {
                    "timeline_id": "timeline-1",
                    "name": "M4 Timeline",
                }
            },
            "set_current_timeline": {
                "timeline": {
                    "timeline_id": "timeline-1",
                    "name": "M4 Timeline",
                },
                "previous_timeline": None,
            },
            "append_clip": {
                "timeline_id": "timeline-1",
                "asset_id": "asset-1",
            },
            "insert_clip": {
                "timeline_id": "timeline-1",
                "asset_id": "asset-1",
                "item": {"source_start_frame": 0, "source_end_frame": 240},
            },
            "set_clip_enabled": {
                "timeline_id": "timeline-1",
                "timeline_item_id": "item-1",
                "previous_enabled": True,
                "enabled": False,
            },
            "add_marker": {
                "timeline_id": "timeline-1",
                "frame": 0,
                "color": "Green",
            },
            "prepare_render_job": {
                "job_id": "job-1",
                "preset": "youtube-2160p-h264-v1",
                "started": False,
            },
            "get_render_job_status": {
                "job_id": "job-1",
                "status": {"JobStatus": "Ready"},
            },
            "start_render_job": {
                "job_id": "job-1",
                "started": True,
            },
        }
    )
    client = ResolveProviderClient(command_client)

    assert client.ping() == "pong"
    assert client.capabilities()["bridge.ping"] is True
    assert client.current_project() == {"name": "Test Project"}
    assert client.timelines() == [{"index": 1, "name": "Main"}]
    assert client.current_timeline() == {"name": "Main"}
    assert client.render_environment()["current"]["format"] == "mp4"
    assert client.import_media(
        ["sample.wav"],
        idempotency_key="stable-key",
    )["items"][0]["asset_id"] == "asset-1"
    assert client.create_timeline(
        "M4 Timeline",
        idempotency_key="stable-key",
    )["timeline"]["timeline_id"] == "timeline-1"
    assert client.set_current_timeline(
        "timeline-1",
        idempotency_key="stable-key",
    )["timeline"]["name"] == "M4 Timeline"
    assert client.append_clip(
        "timeline-1",
        "asset-1",
        idempotency_key="stable-key",
    )["asset_id"] == "asset-1"
    assert client.insert_clip(
        "timeline-1",
        "asset-1",
        0,
        240,
        0,
        "video",
        1,
        idempotency_key="stable-key",
    )["item"]["source_end_frame"] == 240
    assert client.set_clip_enabled(
        "timeline-1",
        "item-1",
        False,
        idempotency_key="stable-key",
    )["enabled"] is False
    assert client.add_marker(
        "timeline-1",
        0,
        "Green",
        "",
        "",
        1,
        idempotency_key="stable-key",
    )["frame"] == 0
    assert client.prepare_render_job(
        "M7 Test",
        profile="youtube-2160p-h264-v1",
        idempotency_key="stable-key",
    )["started"] is False
    assert client.render_job_status("job-1")["status"]["JobStatus"] == "Ready"
    assert client.start_render_job(
        "job-1",
        idempotency_key="stable-key",
    )["started"] is True
    assert command_client.actions == [
        "ping",
        "get_capabilities",
        "get_current_project",
        "list_timelines",
        "get_current_timeline",
        "get_render_environment",
        "import_media",
        "create_timeline",
        "set_current_timeline",
        "append_clip",
        "insert_clip",
        "set_clip_enabled",
        "add_marker",
        "prepare_render_job",
        "get_render_job_status",
        "start_render_job",
    ]
