"""MCP tool-surface tests using the official in-memory client."""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from typing import Any

from mcp import Client

from agent.application import AgentApplication
from mcp_server.server import create_server


class StubResolveReader:
    def current_project(self, timeout_seconds: float = 30) -> dict[str, Any]:
        return {"name": "Test Project"}

    def timelines(self, timeout_seconds: float = 30) -> list[dict[str, Any]]:
        return [{"index": 1, "name": "Main"}]

    def current_timeline(self, timeout_seconds: float = 30) -> dict[str, Any]:
        return {"name": "Main"}

    def render_environment(
        self,
        timeout_seconds: float = 30,
    ) -> dict[str, Any]:
        return {
            "formats": [],
            "current": {"format": "mp4", "codec": "H264"},
            "presets": [],
            "jobs": [],
        }

    def import_media(
        self,
        paths: list[str],
        *,
        timeout_seconds: float = 30,
        idempotency_key: str | None = None,
    ) -> dict[str, Any]:
        return {"items": [{"asset_id": "asset-1", "name": paths[0]}]}

    def create_timeline(
        self,
        name: str,
        *,
        timeout_seconds: float = 30,
        idempotency_key: str | None = None,
    ) -> dict[str, Any]:
        return {"timeline": {"timeline_id": "timeline-1", "name": name}}

    def append_clip(
        self,
        timeline_id: str,
        asset_id: str,
        *,
        timeout_seconds: float = 30,
        idempotency_key: str | None = None,
    ) -> dict[str, Any]:
        return {"timeline_id": timeline_id, "asset_id": asset_id}

    def insert_clip(
        self,
        timeline_id: str,
        asset_id: str,
        source_start_frame: int,
        source_end_frame: int,
        position_frames: int,
        track_type: str,
        track_index: int,
        *,
        timeout_seconds: float = 30,
        idempotency_key: str | None = None,
    ) -> dict[str, Any]:
        return {
            "timeline_id": timeline_id,
            "asset_id": asset_id,
            "item": {
                "source_start_frame": source_start_frame,
                "source_end_frame": source_end_frame,
                "timeline_start_frame": position_frames,
                "track_type": track_type,
                "track_index": track_index,
            },
        }

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
        return {"timeline_id": timeline_id, "frame": frame, "color": color}

    def prepare_render_job(
        self,
        custom_name: str,
        *,
        profile: str = "youtube-1080p-h264-v1",
        timeout_seconds: float = 30,
        idempotency_key: str | None = None,
    ) -> dict[str, Any]:
        return {
            "job_id": "job-1",
            "custom_name": custom_name,
            "preset": profile,
            "started": False,
        }

    def render_job_status(
        self,
        job_id: str,
        *,
        timeout_seconds: float = 30,
    ) -> dict[str, Any]:
        return {"job_id": job_id, "status": {"JobStatus": "Ready"}}

    def start_render_job(
        self,
        job_id: str,
        *,
        timeout_seconds: float = 30,
        idempotency_key: str | None = None,
    ) -> dict[str, Any]:
        return {"job_id": job_id, "started": True}


class StubMediaPolicy:
    def prepare_import(self, paths: list[str]) -> list[str]:
        return paths

    def validate_files(self, paths: list[str]) -> list[str]:
        return paths


class StubRoughCutPlanner:
    def create_plan(
        self,
        *,
        screen_file: str,
        webcam_file: str,
        screen_audio_file: str,
        webcam_audio_file: str,
        speech_audio_file: str,
        timeline_name: str,
        max_sync_offset_ms: int = 30_000,
        pause_threshold_dbfs: float = -40.0,
        min_pause_duration_ms: int = 700,
        preserve_context_ms: int = 120,
    ) -> dict[str, Any]:
        return {
            "status": "pending_review",
            "timeline": {"name": timeline_name},
            "review": {"required": True, "apply_supported": False},
        }


class StubAudioProcessor:
    def process(
        self,
        source_file: str,
        *,
        preset: str = "pcm-dialogue-level-v1",
    ) -> dict[str, Any]:
        return {
            "status": "completed",
            "source": {"path": source_file, "preserved": True},
            "preset": {"name": preset},
        }


def _fresh_state() -> dict[str, Any]:
    return {
        "bridge_version": "0.1.0",
        "protocol_version": "1.0",
        "status": "ready",
        "last_heartbeat": datetime.now(timezone.utc).isoformat(),
        "capabilities": {"bridge.ping": True},
    }


def test_mcp_exposes_fixed_m5_tool_surface() -> None:
    application = AgentApplication(
        resolve=StubResolveReader(),
        state_loader=_fresh_state,
        media_policy=StubMediaPolicy(),
        rough_cut_planner=StubRoughCutPlanner(),
        audio_processor=StubAudioProcessor(),
    )
    server = create_server(application)

    async def exercise_server() -> tuple[dict[str, Any], set[str]]:
        async with Client(server) as client:
            tools = await client.list_tools()
            names = {tool.name for tool in tools.tools}
            annotations = {
                tool.name: tool.annotations for tool in tools.tools
            }
            assert all(
                annotation is not None
                and annotation.destructive_hint is False
                for annotation in annotations.values()
            )
            status_annotations = annotations["video_agent_status"]
            import_annotations = annotations["resolve_import_media"]
            rough_cut_annotations = annotations["create_rough_cut"]
            audio_annotations = annotations["clean_dialogue_audio"]
            render_annotations = annotations["resolve_get_render_options"]
            prepare_annotations = annotations["resolve_prepare_render_job"]
            job_status_annotations = annotations[
                "resolve_get_render_job_status"
            ]
            start_annotations = annotations["resolve_start_render_job"]
            verify_annotations = annotations["resolve_verify_render_output"]
            assert status_annotations is not None
            assert import_annotations is not None
            assert rough_cut_annotations is not None
            assert audio_annotations is not None
            assert render_annotations is not None
            assert prepare_annotations is not None
            assert job_status_annotations is not None
            assert start_annotations is not None
            assert verify_annotations is not None
            assert status_annotations.read_only_hint is True
            assert import_annotations.read_only_hint is False
            assert rough_cut_annotations.read_only_hint is False
            assert audio_annotations.read_only_hint is False
            assert render_annotations.read_only_hint is True
            assert prepare_annotations.read_only_hint is False
            assert job_status_annotations.read_only_hint is True
            assert start_annotations.read_only_hint is False
            assert verify_annotations.read_only_hint is True

            results = {
                "project": await client.call_tool("resolve_get_project", {}),
                "timelines": await client.call_tool(
                    "resolve_list_timelines",
                    {},
                ),
                "timeline": await client.call_tool(
                    "resolve_get_timeline",
                    {},
                ),
                "render": await client.call_tool(
                    "resolve_get_render_options",
                    {},
                ),
                "status": await client.call_tool("video_agent_status", {}),
                "imported": await client.call_tool(
                    "resolve_import_media",
                    {"paths": ["sample.wav"]},
                ),
                "created": await client.call_tool(
                    "resolve_create_timeline",
                    {"name": "M4 Timeline"},
                ),
                "appended": await client.call_tool(
                    "resolve_append_clip",
                    {"timeline_id": "timeline-1", "asset_id": "asset-1"},
                ),
                "inserted": await client.call_tool(
                    "resolve_insert_clip",
                    {
                        "timeline_id": "timeline-1",
                        "asset_id": "asset-1",
                        "source_start_frame": 0,
                        "source_end_frame": 240,
                        "position_frames": 0,
                        "track_type": "video",
                        "track_index": 1,
                    },
                ),
                "marker": await client.call_tool(
                    "resolve_add_marker",
                    {
                        "timeline_id": "timeline-1",
                        "frame": 0,
                        "color": "Green",
                    },
                ),
                "prepared": await client.call_tool(
                    "resolve_prepare_render_job",
                    {
                        "custom_name": "M9 Test",
                        "profile": "youtube-2160p-h264-v1",
                    },
                ),
                "render_status": await client.call_tool(
                    "resolve_get_render_job_status",
                    {"job_id": "job-1"},
                ),
                "render_start": await client.call_tool(
                    "resolve_start_render_job",
                    {"job_id": "job-1"},
                ),
                "rough_cut": await client.call_tool(
                    "create_rough_cut",
                    {
                        "screen_file": "screen.mkv",
                        "webcam_file": "webcam.mkv",
                        "screen_audio_file": "screen.wav",
                        "webcam_audio_file": "webcam.wav",
                        "speech_audio_file": "speech.wav",
                        "timeline_name": "M5 Draft",
                    },
                ),
                "audio": await client.call_tool(
                    "clean_dialogue_audio",
                    {"source_file": "dialogue.wav"},
                ),
            }
        return results, names

    results, names = asyncio.run(exercise_server())

    assert names == {
        "video_agent_status",
        "resolve_get_project",
        "resolve_list_timelines",
        "resolve_get_timeline",
        "resolve_get_render_options",
        "resolve_import_media",
        "resolve_create_timeline",
        "resolve_append_clip",
        "resolve_insert_clip",
        "resolve_add_marker",
        "resolve_prepare_render_job",
        "resolve_get_render_job_status",
        "resolve_start_render_job",
        "resolve_verify_render_output",
        "create_rough_cut",
        "clean_dialogue_audio",
    }
    assert results["project"].structured_content == {
        "project": {"name": "Test Project"}
    }
    assert results["timelines"].structured_content == {
        "timelines": [{"index": 1, "name": "Main"}]
    }
    assert results["timeline"].structured_content == {
        "timeline": {"name": "Main"}
    }
    assert results["render"].structured_content["current"]["format"] == "mp4"
    assert results["status"].structured_content["healthy"] is True
    assert results["imported"].structured_content["items"][0]["asset_id"] == (
        "asset-1"
    )
    assert results["created"].structured_content["timeline"]["timeline_id"] == (
        "timeline-1"
    )
    assert results["appended"].structured_content["asset_id"] == "asset-1"
    assert results["inserted"].structured_content["item"][
        "source_end_frame"
    ] == 240
    assert results["marker"].structured_content["color"] == "Green"
    assert results["prepared"].structured_content["started"] is False
    assert results["prepared"].structured_content["preset"] == (
        "youtube-2160p-h264-v1"
    )
    assert results["render_status"].structured_content["status"][
        "JobStatus"
    ] == "Ready"
    assert results["render_start"].structured_content["started"] is True
    assert results["rough_cut"].structured_content["status"] == "pending_review"
    assert results["audio"].structured_content["status"] == "completed"
