"""Typed Resolve provider-client tests."""

from __future__ import annotations

from typing import Any

from agent.client import BridgeCommandError
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
        allow_destructive: bool = False,
    ) -> Any:
        assert provider == "resolve"
        assert timeout_seconds > 0
        if action in {
            "import_media",
            "create_timeline",
            "ensure_timeline_tracks",
            "duplicate_timeline",
            "set_current_timeline",
            "append_clip",
            "insert_title",
            "insert_animation_template",
            "append_subtitle_file",
            "insert_clip",
            "insert_clips",
            "set_clip_enabled",
            "set_clips_linked",
            "set_clip_link_groups",
            "set_clip_transform",
            "set_clip_transforms",
            "apply_color_preset",
            "delete_clip",
            "add_marker",
            "create_subtitles_from_audio",
            "prepare_render_job",
            "start_render_job",
        }:
            assert arguments is not None
            assert create_backup is True
            assert idempotency_key == "stable-key"
            assert allow_destructive is (action == "delete_clip")
        elif action == "list_timeline_items":
            assert arguments == {"timeline_id": "timeline-1"}
            assert create_backup is False
            assert allow_destructive is False
        elif action == "get_editing_metadata":
            assert arguments == {
                "timeline_id": "timeline-1",
                "asset_ids": ["asset-1"],
            }
            assert create_backup is False
            assert allow_destructive is False
        elif action in {
            "get_subtitle_environment",
            "get_color_environment",
        }:
            assert arguments == {"timeline_id": "timeline-1"}
            assert create_backup is False
            assert allow_destructive is False
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
            "stop_bridge": {"status": "stopping"},
            "get_capabilities": {
                "bridge.ping": True,
                "timeline.create": "unknown",
            },
            "get_current_project": {"name": "Test Project"},
            "list_timelines": [{"index": 1, "name": "Main"}],
            "get_current_timeline": {"name": "Main"},
            "list_timeline_items": {
                "timeline_id": "timeline-1",
                "name": "Main",
                "items": [
                    {
                        "timeline_item_id": "item-1",
                        "track_type": "video",
                        "track_index": 1,
                    }
                ],
            },
            "list_media_pool_items": {
                "items": [
                    {
                        "asset_id": "asset-1",
                        "name": "screen.mkv",
                        "folder_id": "folder-root",
                        "folder_path": ["Master"],
                    }
                ],
                "folder_count": 1,
            },
            "get_editing_metadata": {
                "timeline": {
                    "timeline_id": "timeline-1",
                    "video_track_count": 1,
                    "audio_track_count": 1,
                    "frame_rate": 60.0,
                    "resolution_width": 1920,
                    "resolution_height": 1080,
                },
                "assets": [
                    {
                        "asset_id": "asset-1",
                        "duration_frames": 240,
                        "frame_rate": 60.0,
                    }
                ],
            },
            "get_subtitle_environment": {
                "timeline_id": "timeline-1",
                "subtitle_track_count": 0,
                "subtitle_item_count": 0,
                "tracks": [],
                "auto_caption": {"method_available": True},
            },
            "get_color_environment": {
                "timeline": {"timeline_id": "timeline-1", "name": "Main"},
                "methods": {"GetCurrentVersion": True},
                "items": [{"timeline_item_id": "item-1"}],
                "ready": True,
                "apply_candidate": True,
            },
            "create_subtitles_from_audio": {
                "timeline_id": "timeline-1",
                "policy": {"language": "auto"},
                "subtitle_environment": {"subtitle_item_count": 1},
                "backup_path": "backup.drp",
            },
            "get_workspace_snapshot": {
                "bridge": {"bridge_version": "0.1.0"},
                "project": {"name": "Test Project"},
                "timelines": [{"timeline_id": "timeline-1", "name": "Main"}],
                "current_timeline": {
                    "timeline_id": "timeline-1",
                    "name": "Main",
                },
                "timeline_items": {"items": []},
                "media_pool": {"items": [], "folder_count": 1},
                "render": {"formats": []},
            },
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
            "append_subtitle_file": {
                "timeline_id": "timeline-1",
                "asset_id": "asset-1",
                "items": [{"timeline_item_id": "subtitle-1"}],
                "timeline_start_frame": 86400,
                "timeline_frame_rate": 24.0,
            },
            "ensure_timeline_tracks": {
                "timeline": {"timeline_id": "timeline-1"},
                "after": {
                    "video_track_count": 2,
                    "audio_track_count": 1,
                },
            },
            "duplicate_timeline": {
                "source_timeline": {
                    "timeline_id": "timeline-1",
                    "name": "M4 Timeline",
                },
                "timeline": {
                    "timeline_id": "timeline-2",
                    "name": "Agent Draft",
                },
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
            "insert_title": {
                "timeline_id": "timeline-1",
                "title_name": "Text",
                "item": {"timeline_item_id": "title-1"},
            },
            "insert_animation_template": {
                "timeline_id": "timeline-1",
                "template_id": "accent-card-v1",
                "resolve_name": "DaVinci Agent Accent Card",
                "fusion_comp_count": 1,
                "item": {"timeline_item_id": "animation-1"},
            },
            "insert_clip": {
                "timeline_id": "timeline-1",
                "asset_id": "asset-1",
                "item": {"source_start_frame": 0, "source_end_frame": 240},
            },
            "insert_clips": {
                "timeline_id": "timeline-1",
                "items": [{"timeline_item_id": "item-1"}],
            },
            "set_clip_enabled": {
                "timeline_id": "timeline-1",
                "timeline_item_id": "item-1",
                "previous_enabled": True,
                "enabled": False,
            },
            "set_clips_linked": {
                "timeline_id": "timeline-1",
                "linked": True,
                "items": [
                    {
                        "timeline_item_id": "video-1",
                        "linked_item_ids": ["audio-1"],
                    },
                    {
                        "timeline_item_id": "audio-1",
                        "linked_item_ids": ["video-1"],
                    },
                ],
            },
            "set_clip_transform": {
                "timeline_id": "timeline-1",
                "timeline_item_id": "item-1",
                "properties": {
                    "Pan": 320.0,
                    "ZoomX": 0.5,
                    "ZoomY": 0.5,
                },
            },
            "set_clip_link_groups": {
                "timeline_id": "timeline-1",
                "linked": True,
                "groups": [{"group_index": 0, "items": []}],
            },
            "set_clip_transforms": {
                "timeline_id": "timeline-1",
                "items": [{"timeline_item_id": "item-1"}],
            },
            "apply_color_preset": {
                "timeline_id": "timeline-1",
                "preset_id": "tutorial-clean-v1",
                "items": [{"timeline_item_id": "item-1"}],
            },
            "delete_clip": {
                "timeline_id": "timeline-1",
                "timeline_item_id": "item-1",
                "deleted": True,
                "ripple": False,
            },
            "add_marker": {
                "timeline_id": "timeline-1",
                "frame": 0,
                "color": "Green",
            },
            "prepare_render_job": {
                "job_id": "job-1",
                "timeline_id": "timeline-1",
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
    assert client.stop_bridge() == {"status": "stopping"}
    assert client.capabilities()["bridge.ping"] is True
    assert client.current_project() == {"name": "Test Project"}
    assert client.timelines() == [{"index": 1, "name": "Main"}]
    assert client.current_timeline() == {"name": "Main"}
    assert client.timeline_items("timeline-1")["items"][0][
        "timeline_item_id"
    ] == "item-1"
    assert client.media_pool_items()["items"][0]["asset_id"] == "asset-1"
    editing_metadata = client.editing_metadata("timeline-1", ["asset-1"])
    assert editing_metadata["assets"][0]["frame_rate"] == 60.0
    assert editing_metadata["timeline"]["frame_rate"] == 60.0
    assert editing_metadata["timeline"]["resolution_width"] == 1920
    assert editing_metadata["timeline"]["resolution_height"] == 1080
    assert client.subtitle_environment("timeline-1")[
        "subtitle_track_count"
    ] == 0
    assert client.color_environment("timeline-1")["apply_candidate"] is True
    assert client.create_subtitles_from_audio(
        "timeline-1",
        confirm_create=True,
        idempotency_key="stable-key",
    )["subtitle_environment"]["subtitle_item_count"] == 1
    assert client.workspace_snapshot()["project"]["name"] == "Test Project"
    assert client.render_environment()["current"]["format"] == "mp4"
    assert client.import_media(
        ["sample.wav"],
        idempotency_key="stable-key",
    )["items"][0]["asset_id"] == "asset-1"
    assert client.create_timeline(
        "M4 Timeline",
        idempotency_key="stable-key",
    )["timeline"]["timeline_id"] == "timeline-1"
    assert client.ensure_timeline_tracks(
        "timeline-1",
        2,
        1,
        idempotency_key="stable-key",
    )["after"]["video_track_count"] == 2
    assert client.duplicate_timeline(
        "timeline-1",
        "Agent Draft",
        idempotency_key="stable-key",
    )["timeline"]["timeline_id"] == "timeline-2"
    assert client.set_current_timeline(
        "timeline-1",
        idempotency_key="stable-key",
    )["timeline"]["name"] == "M4 Timeline"
    assert client.append_clip(
        "timeline-1",
        "asset-1",
        idempotency_key="stable-key",
    )["asset_id"] == "asset-1"
    assert client.insert_title(
        "timeline-1",
        "Text",
        "01:00:05:00",
        confirm_insert=True,
        idempotency_key="stable-key",
    )["item"]["timeline_item_id"] == "title-1"
    assert client.insert_animation_template(
        "timeline-1",
        "accent-card-v1",
        "01:00:05:00",
        confirm_insert=True,
        idempotency_key="stable-key",
    )["item"]["timeline_item_id"] == "animation-1"
    assert client.append_subtitle_file(
        "timeline-1",
        "asset-1",
        "C:/Videos/captions.srt",
        "subtitle-import-key",
        confirm_apply=True,
        idempotency_key="stable-key",
    )["items"][0]["timeline_item_id"] == "subtitle-1"
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
    assert client.insert_clips(
        "timeline-1",
        [
            {
                "asset_id": "asset-1",
                "source_start_frame": 0,
                "source_end_frame": 240,
                "position_frames": 0,
                "track_type": "video",
                "track_index": 1,
            }
        ],
        idempotency_key="stable-key",
    )["items"][0]["timeline_item_id"] == "item-1"
    assert client.set_clip_enabled(
        "timeline-1",
        "item-1",
        False,
        idempotency_key="stable-key",
    )["enabled"] is False
    assert client.set_clips_linked(
        "timeline-1",
        ["video-1", "audio-1"],
        True,
        idempotency_key="stable-key",
    )["linked"] is True
    assert client.set_clip_transform(
        "timeline-1",
        "item-1",
        position_x=320.0,
        zoom=0.5,
        idempotency_key="stable-key",
    )["properties"]["ZoomX"] == 0.5
    assert client.set_clip_link_groups(
        "timeline-1",
        [["video-1", "audio-1"]],
        True,
        idempotency_key="stable-key",
    )["linked"] is True
    assert client.set_clip_transforms(
        "timeline-1",
        [{"timeline_item_id": "item-1", "zoom": 0.5}],
        idempotency_key="stable-key",
    )["items"][0]["timeline_item_id"] == "item-1"
    assert client.apply_color_preset(
        "timeline-1",
        ["item-1"],
        "tutorial-clean-v1",
        confirm_apply=True,
        idempotency_key="stable-key",
    )["preset_id"] == "tutorial-clean-v1"
    assert client.delete_clip(
        "timeline-1",
        "item-1",
        confirm_delete=True,
        idempotency_key="stable-key",
    )["deleted"] is True
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
        timeline_id="timeline-1",
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
        "stop_bridge",
        "get_capabilities",
        "get_current_project",
        "list_timelines",
        "get_current_timeline",
        "list_timeline_items",
        "list_media_pool_items",
        "get_editing_metadata",
        "get_subtitle_environment",
        "get_color_environment",
        "create_subtitles_from_audio",
        "get_workspace_snapshot",
        "get_render_environment",
        "import_media",
        "create_timeline",
        "ensure_timeline_tracks",
        "duplicate_timeline",
        "set_current_timeline",
        "append_clip",
        "insert_title",
        "insert_animation_template",
        "append_subtitle_file",
        "insert_clip",
        "insert_clips",
        "set_clip_enabled",
        "set_clips_linked",
        "set_clip_transform",
        "set_clip_link_groups",
        "set_clip_transforms",
        "apply_color_preset",
        "delete_clip",
        "add_marker",
        "prepare_render_job",
        "get_render_job_status",
        "start_render_job",
    ]


def test_animation_template_retries_one_safe_playhead_readback_failure() -> None:
    class TransientPlayheadClient:
        def __init__(self) -> None:
            self.calls = 0

        def request(self, **kwargs: Any) -> Any:
            self.calls += 1
            if self.calls == 1:
                raise BridgeCommandError(
                    code="TIMECODE_READBACK_FAILED",
                    message="Playhead selection is still settling",
                    retryable=True,
                )
            return {
                "timeline_id": "timeline-1",
                "template_id": "accent-card-v1",
                "resolve_name": "DaVinci Agent Accent Card",
                "fusion_comp_count": 1,
                "item": {"timeline_item_id": "animation-1"},
            }

    command_client = TransientPlayheadClient()
    client = ResolveProviderClient(command_client)

    result = client.insert_animation_template(
        "timeline-1",
        "accent-card-v1",
        "01:00:00:00",
        confirm_insert=True,
        idempotency_key="stable-key",
    )

    assert result["item"]["timeline_item_id"] == "animation-1"
    assert command_client.calls == 2
