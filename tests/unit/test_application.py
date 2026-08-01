"""Application-service boundary tests."""

from __future__ import annotations

from collections.abc import Callable
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pytest

from agent.application import AgentApplication


class StubResolveReader:
    def __init__(self) -> None:
        self.timeouts: list[float] = []

    def current_project(self, timeout_seconds: float = 30) -> dict[str, Any]:
        self.timeouts.append(timeout_seconds)
        return {"name": "Test Project"}

    def stop_bridge(self, timeout_seconds: float = 30) -> dict[str, Any]:
        self.timeouts.append(timeout_seconds)
        return {"status": "stopping"}

    def timelines(self, timeout_seconds: float = 30) -> list[dict[str, Any]]:
        self.timeouts.append(timeout_seconds)
        return [{"index": 1, "name": "Main"}]

    def current_timeline(self, timeout_seconds: float = 30) -> dict[str, Any]:
        self.timeouts.append(timeout_seconds)
        return {"name": "Main"}

    def timeline_items(
        self,
        timeline_id: str,
        *,
        timeout_seconds: float = 30,
    ) -> dict[str, Any]:
        self.timeouts.append(timeout_seconds)
        return {
            "timeline_id": timeline_id,
            "name": "Main",
            "items": [{"timeline_item_id": "item-1"}],
        }

    def media_pool_items(
        self,
        timeout_seconds: float = 30,
    ) -> dict[str, Any]:
        self.timeouts.append(timeout_seconds)
        return {
            "items": [{"asset_id": "asset-1", "name": "screen.mkv"}],
            "folder_count": 1,
        }

    def editing_metadata(
        self,
        timeline_id: str,
        asset_ids: list[str],
        *,
        timeout_seconds: float = 30,
    ) -> dict[str, Any]:
        self.timeouts.append(timeout_seconds)
        return {
            "timeline": {
                "timeline_id": timeline_id,
                "video_track_count": 1,
                "audio_track_count": 1,
                "frame_rate": 60.0,
            },
            "assets": [
                {
                    "asset_id": asset_id,
                    "duration_frames": 240,
                    "frame_rate": 60.0,
                }
                for asset_id in asset_ids
            ],
        }

    def workspace_snapshot(
        self,
        timeout_seconds: float = 30,
    ) -> dict[str, Any]:
        self.timeouts.append(timeout_seconds)
        return {
            "project": {"name": "Test Project"},
            "timelines": [{"index": 1, "name": "Main"}],
        }

    def render_environment(
        self,
        timeout_seconds: float = 30,
    ) -> dict[str, Any]:
        self.timeouts.append(timeout_seconds)
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

    def ensure_timeline_tracks(
        self,
        timeline_id: str,
        video_track_count: int,
        audio_track_count: int,
        *,
        timeout_seconds: float = 30,
        idempotency_key: str | None = None,
    ) -> dict[str, Any]:
        self.timeouts.append(timeout_seconds)
        return {
            "timeline": {"timeline_id": timeline_id},
            "after": {
                "video_track_count": video_track_count,
                "audio_track_count": audio_track_count,
            },
        }

    def duplicate_timeline(
        self,
        timeline_id: str,
        name: str,
        *,
        timeout_seconds: float = 30,
        idempotency_key: str | None = None,
    ) -> dict[str, Any]:
        self.timeouts.append(timeout_seconds)
        return {
            "source_timeline": {"timeline_id": timeline_id},
            "timeline": {"timeline_id": "timeline-2", "name": name},
        }

    def set_current_timeline(
        self,
        timeline_id: str,
        *,
        timeout_seconds: float = 30,
        idempotency_key: str | None = None,
    ) -> dict[str, Any]:
        self.timeouts.append(timeout_seconds)
        return {
            "timeline": {
                "timeline_id": timeline_id,
                "name": "Selected",
            }
        }

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
        self.timeouts.append(timeout_seconds)
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

    def set_clip_enabled(
        self,
        timeline_id: str,
        timeline_item_id: str,
        enabled: bool,
        *,
        timeout_seconds: float = 30,
        idempotency_key: str | None = None,
    ) -> dict[str, Any]:
        self.timeouts.append(timeout_seconds)
        return {
            "timeline_id": timeline_id,
            "timeline_item_id": timeline_item_id,
            "previous_enabled": not enabled,
            "enabled": enabled,
        }

    def set_clips_linked(
        self,
        timeline_id: str,
        timeline_item_ids: list[str],
        linked: bool,
        *,
        timeout_seconds: float = 30,
        idempotency_key: str | None = None,
    ) -> dict[str, Any]:
        self.timeouts.append(timeout_seconds)
        return {
            "timeline_id": timeline_id,
            "timeline_item_ids": timeline_item_ids,
            "linked": linked,
        }

    def set_clip_transform(
        self,
        timeline_id: str,
        timeline_item_id: str,
        *,
        position_x: float | None = None,
        position_y: float | None = None,
        zoom: float | None = None,
        rotation_degrees: float | None = None,
        opacity_percent: float | None = None,
        timeout_seconds: float = 30,
        idempotency_key: str | None = None,
    ) -> dict[str, Any]:
        self.timeouts.append(timeout_seconds)
        return {
            "timeline_id": timeline_id,
            "timeline_item_id": timeline_item_id,
            "transform": {
                "position_x": position_x,
                "position_y": position_y,
                "zoom": zoom,
                "rotation_degrees": rotation_degrees,
                "opacity_percent": opacity_percent,
            },
        }

    def delete_clip(
        self,
        timeline_id: str,
        timeline_item_id: str,
        *,
        confirm_delete: bool,
        timeout_seconds: float = 30,
        idempotency_key: str | None = None,
    ) -> dict[str, Any]:
        assert confirm_delete is True
        self.timeouts.append(timeout_seconds)
        return {
            "timeline_id": timeline_id,
            "timeline_item_id": timeline_item_id,
            "deleted": True,
            "ripple": False,
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
        self.timeouts.append(timeout_seconds)
        return {"timeline_id": timeline_id, "frame": frame, "color": color}

    def prepare_render_job(
        self,
        custom_name: str,
        *,
        profile: str = "youtube-1080p-h264-v1",
        timeout_seconds: float = 30,
        idempotency_key: str | None = None,
    ) -> dict[str, Any]:
        self.timeouts.append(timeout_seconds)
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
        self.timeouts.append(timeout_seconds)
        return {
            "job_id": job_id,
            "rendering_in_progress": False,
            "status": {
                "JobStatus": "Ready",
                "CompletionPercentage": 0,
            },
            "job": {
                "TargetDir": "",
                "OutputFilename": "M11 Test.mp4",
            },
        }

    def start_render_job(
        self,
        job_id: str,
        *,
        timeout_seconds: float = 30,
        idempotency_key: str | None = None,
    ) -> dict[str, Any]:
        self.timeouts.append(timeout_seconds)
        return {"job_id": job_id, "started": True}


class StubCompletedResolveReader(StubResolveReader):
    def __init__(self, output_directory: Path) -> None:
        super().__init__()
        self.output_directory = output_directory

    def render_job_status(
        self,
        job_id: str,
        *,
        timeout_seconds: float = 30,
    ) -> dict[str, Any]:
        self.timeouts.append(timeout_seconds)
        return {
            "job_id": job_id,
            "rendering_in_progress": False,
            "status": {
                "JobStatus": "Complete",
                "CompletionPercentage": 100,
            },
            "job": {
                "TargetDir": str(self.output_directory),
                "OutputFilename": "M11 Test.mp4",
            },
        }


class StubMediaPolicy:
    def __init__(self) -> None:
        self.paths: list[str] = []

    def prepare_import(self, paths: list[str]) -> list[str]:
        self.paths = paths
        return [f"normalized:{path}" for path in paths]

    def validate_files(self, paths: list[str]) -> list[str]:
        self.paths = paths
        return [f"normalized:{path}" for path in paths]


class StubRoughCutPlanner:
    def __init__(self) -> None:
        self.arguments: dict[str, Any] = {}

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
        self.arguments = {
            "screen_file": screen_file,
            "webcam_file": webcam_file,
            "screen_audio_file": screen_audio_file,
            "webcam_audio_file": webcam_audio_file,
            "speech_audio_file": speech_audio_file,
            "timeline_name": timeline_name,
            "max_sync_offset_ms": max_sync_offset_ms,
            "pause_threshold_dbfs": pause_threshold_dbfs,
            "min_pause_duration_ms": min_pause_duration_ms,
            "preserve_context_ms": preserve_context_ms,
        }
        return {
            "status": "pending_review",
            "review": {"apply_supported": False},
        }


class StubRoughCutReviewer:
    def __init__(self) -> None:
        self.plan_id = ""
        self.confirm_review = False

    def approve(
        self,
        plan_id: str,
        *,
        confirm_review: bool,
    ) -> dict[str, Any]:
        self.plan_id = plan_id
        self.confirm_review = confirm_review
        return {
            "plan_id": plan_id,
            "status": "approved",
            "apply_supported": False,
        }


class StubRoughCutInspector:
    def get_plan(self, plan_id: str) -> dict[str, Any]:
        return {
            "plan": {"plan_id": plan_id},
            "approval": None,
            "effective_status": "pending_review",
        }

    def list_plans(self, limit: int = 100) -> dict[str, Any]:
        return {
            "plans": [{"plan_id": "a" * 64}],
            "count": 1,
            "truncated": limit < 1,
        }


class StubSynchronizedPairAssembler:
    def __init__(self) -> None:
        self.arguments: dict[str, Any] = {}

    def assemble(
        self,
        *,
        timeline_name: str,
        screen_asset_id: str,
        webcam_asset_id: str,
        webcam_offset_ms: int,
        confirm_sync: bool,
        timeout_seconds: float = 30,
    ) -> dict[str, Any]:
        self.arguments = {
            "timeline_name": timeline_name,
            "screen_asset_id": screen_asset_id,
            "webcam_asset_id": webcam_asset_id,
            "webcam_offset_ms": webcam_offset_ms,
            "confirm_sync": confirm_sync,
            "timeout_seconds": timeout_seconds,
        }
        return {"status": "applied", "timeline": {"name": timeline_name}}


class StubPictureInPictureComposer:
    def __init__(self) -> None:
        self.arguments: dict[str, Any] = {}

    def compose(
        self,
        *,
        synchronized_pair_receipt_id: str,
        size_percent: float,
        center_x_percent: float,
        center_y_percent: float,
        confirm_layout: bool,
        timeout_seconds: float = 30,
    ) -> dict[str, Any]:
        self.arguments = {
            "synchronized_pair_receipt_id": synchronized_pair_receipt_id,
            "size_percent": size_percent,
            "center_x_percent": center_x_percent,
            "center_y_percent": center_y_percent,
            "confirm_layout": confirm_layout,
            "timeout_seconds": timeout_seconds,
        }
        return {"status": "applied", "transform": {"zoom": 0.25}}


class StubSynchronizedScreenLinker:
    def __init__(self) -> None:
        self.arguments: dict[str, Any] = {}

    def link(
        self,
        *,
        synchronized_pair_receipt_id: str,
        confirm_link: bool,
        timeout_seconds: float = 30,
    ) -> dict[str, Any]:
        self.arguments = {
            "synchronized_pair_receipt_id": synchronized_pair_receipt_id,
            "confirm_link": confirm_link,
            "timeout_seconds": timeout_seconds,
        }
        return {"status": "applied", "operation": {"status": "applied"}}


class StubPauseCompactionPreviewer:
    def __init__(self) -> None:
        self.arguments: dict[str, Any] = {}

    def preview(
        self,
        *,
        plan_id: str,
        synchronized_pair_receipt_id: str,
        target_timeline_name: str,
        timeout_seconds: float = 30,
    ) -> dict[str, Any]:
        self.arguments = {
            "plan_id": plan_id,
            "synchronized_pair_receipt_id": synchronized_pair_receipt_id,
            "target_timeline_name": target_timeline_name,
            "timeout_seconds": timeout_seconds,
        }
        return {"status": "preview", "apply_supported": False}


class StubPauseCompactionApplier:
    def __init__(self) -> None:
        self.arguments: dict[str, Any] = {}

    def apply(
        self,
        *,
        plan_id: str,
        synchronized_pair_receipt_id: str,
        target_timeline_name: str,
        confirm_apply: bool,
        timeout_seconds: float = 30,
    ) -> dict[str, Any]:
        self.arguments = {
            "plan_id": plan_id,
            "synchronized_pair_receipt_id": synchronized_pair_receipt_id,
            "target_timeline_name": target_timeline_name,
            "confirm_apply": confirm_apply,
            "timeout_seconds": timeout_seconds,
        }
        return {"status": "applied", "placement_count": 6}


class StubAudioProcessor:
    def __init__(self) -> None:
        self.source_file = ""
        self.preset = ""

    def process(
        self,
        source_file: str,
        *,
        preset: str = "pcm-dialogue-level-v1",
    ) -> dict[str, Any]:
        self.source_file = source_file
        self.preset = preset
        return {
            "status": "completed",
            "source": {"preserved": True},
            "validation": {"target_met": True},
        }


class StubAudioReportInspector:
    def get_report(self, report_id: str) -> dict[str, Any]:
        return {"report_id": report_id, "status": "completed"}

    def list_reports(self, limit: int = 100) -> dict[str, Any]:
        return {
            "reports": [{"report_id": "b" * 64}],
            "count": 1,
            "truncated": limit < 1,
        }


class StubWorkflowAuditor:
    def __init__(self) -> None:
        self.operations: list[str] = []

    def run(
        self,
        operation: str,
        callback: Callable[[], Any],
    ) -> Any:
        self.operations.append(operation)
        return callback()


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
    assert application.resolve_stop_bridge(12) == {"status": "stopping"}
    assert application.resolve_list_timelines(20) == [
        {"index": 1, "name": "Main"}
    ]
    assert application.resolve_get_timeline(30) == {"name": "Main"}
    assert application.resolve_list_timeline_items(
        "timeline-1",
        35,
    )["items"][0]["timeline_item_id"] == "item-1"
    assert application.resolve_list_media_pool_items(37)["items"][0][
        "asset_id"
    ] == "asset-1"
    editing_metadata = application.resolve_get_editing_metadata(
        "timeline-1", ["asset-1"], 37.5
    )
    assert editing_metadata["assets"][0]["frame_rate"] == 60.0
    assert editing_metadata["timeline"]["frame_rate"] == 60.0
    assert application.resolve_get_workspace_snapshot(38)["project"]["name"] == (
        "Test Project"
    )
    assert application.resolve_get_render_options(40)["current"] == {
        "format": "mp4",
        "codec": "H264",
    }
    assert resolve.timeouts == [10, 12, 20, 30, 35, 37, 37.5, 38, 40]


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
    tracks = application.resolve_ensure_timeline_tracks(
        "timeline-1",
        2,
        1,
        timeout_seconds=21,
    )
    duplicated = application.resolve_duplicate_timeline(
        "timeline-1",
        "Agent Draft",
        timeout_seconds=22,
    )
    selected = application.resolve_set_current_timeline(
        "timeline-1",
        timeout_seconds=25,
    )
    appended = application.resolve_append_clip(
        "timeline-1",
        "asset-1",
        timeout_seconds=30,
    )
    inserted = application.resolve_insert_clip(
        "timeline-1",
        "asset-1",
        0,
        240,
        0,
        "video",
        1,
        timeout_seconds=35,
    )
    disabled = application.resolve_set_clip_enabled(
        "timeline-1",
        "item-1",
        False,
        timeout_seconds=37,
    )
    linked = application.resolve_set_clips_linked(
        "timeline-1",
        ["video-1", "audio-1"],
        True,
        timeout_seconds=37.5,
    )
    transformed = application.resolve_set_clip_transform(
        "timeline-1",
        "item-1",
        position_x=320.0,
        zoom=0.5,
        timeout_seconds=38,
    )
    deleted = application.resolve_delete_clip(
        "timeline-1",
        "item-1",
        confirm_delete=True,
        timeout_seconds=39,
    )
    marker = application.resolve_add_marker(
        "timeline-1",
        0,
        "Green",
        timeout_seconds=40,
    )
    render_job = application.resolve_prepare_render_job(
        "M7 Test",
        profile="youtube-2160p-h264-v1",
        timeout_seconds=50,
    )
    render_status = application.resolve_get_render_job_status(
        "job-1",
        timeout_seconds=60,
    )
    render_start = application.resolve_start_render_job(
        "job-1",
        timeout_seconds=70,
    )

    assert media_policy.paths == ["sample.wav"]
    assert imported["items"][0]["name"] == "normalized:sample.wav"
    assert created["timeline"]["name"] == "M4 Timeline"
    assert tracks["after"] == {
        "video_track_count": 2,
        "audio_track_count": 1,
    }
    assert duplicated["timeline"]["name"] == "Agent Draft"
    assert selected["timeline"]["timeline_id"] == "timeline-1"
    assert appended["asset_id"] == "asset-1"
    assert inserted["item"]["source_end_frame"] == 240
    assert inserted["item"]["track_type"] == "video"
    assert disabled["timeline_item_id"] == "item-1"
    assert disabled["enabled"] is False
    assert linked["linked"] is True
    assert transformed["transform"]["position_x"] == 320.0
    assert transformed["transform"]["zoom"] == 0.5
    assert deleted["deleted"] is True
    assert deleted["ripple"] is False
    assert marker["color"] == "Green"
    assert render_job["started"] is False
    assert render_job["custom_name"] == "M7 Test"
    assert render_job["preset"] == "youtube-2160p-h264-v1"
    assert render_status["status"]["JobStatus"] == "Ready"
    assert render_start["started"] is True
    assert resolve.timeouts == [
        10,
        20,
        21,
        22,
        25,
        30,
        35,
        37,
        37.5,
        38,
        39,
        40,
        50,
        60,
        70,
    ]


def test_application_requires_explicit_delete_confirmation() -> None:
    application = AgentApplication(resolve=StubResolveReader())

    with pytest.raises(ValueError, match="confirm_delete must be true"):
        application.resolve_delete_clip(
            "timeline-1",
            "item-1",
            confirm_delete=False,
        )


def test_application_verifies_completed_render_output(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    profile = tmp_path / "profile"
    output_directory = (
        profile / "Videos" / "DaVinciResolveAgent" / "renders"
    )
    output_directory.mkdir(parents=True)
    output_file = output_directory / "M11 Test.mp4"
    output_file.write_bytes(b"rendered")
    monkeypatch.setenv("USERPROFILE", str(profile))
    resolve = StubCompletedResolveReader(output_directory)
    application = AgentApplication(resolve=resolve)

    result = application.resolve_verify_render_output(
        "job-1",
        timeout_seconds=25,
    )

    assert result["output"]["path"] == str(output_file.resolve())
    assert result["output"]["size_bytes"] == 8
    assert result["validation"] == {
        "completed": True,
        "managed_path": True,
        "non_empty": True,
        "passed": True,
    }


def test_application_creates_review_only_plan_without_resolve_call() -> None:
    resolve = StubResolveReader()
    media_policy = StubMediaPolicy()
    planner = StubRoughCutPlanner()
    audit = StubWorkflowAuditor()
    application = AgentApplication(
        resolve=resolve,
        media_policy=media_policy,
        rough_cut_planner=planner,
        workflow_audit=audit,
    )

    plan = application.create_rough_cut(
        screen_file="screen.mkv",
        webcam_file="webcam.mkv",
        screen_audio_file="screen.wav",
        webcam_audio_file="webcam.wav",
        speech_audio_file="speech.wav",
        timeline_name="M5 Draft",
    )

    assert plan["status"] == "pending_review"
    assert plan["review"]["apply_supported"] is False
    assert planner.arguments["screen_file"] == "normalized:screen.mkv"
    assert media_policy.paths == [
        "screen.mkv",
        "webcam.mkv",
        "screen.wav",
        "webcam.wav",
        "speech.wav",
    ]
    assert audit.operations == ["create_rough_cut"]
    assert resolve.timeouts == []


def test_application_approves_plan_without_resolve_call() -> None:
    resolve = StubResolveReader()
    reviewer = StubRoughCutReviewer()
    audit = StubWorkflowAuditor()
    application = AgentApplication(
        resolve=resolve,
        rough_cut_reviewer=reviewer,
        workflow_audit=audit,
    )

    approval = application.approve_rough_cut(
        "a" * 64,
        confirm_review=True,
    )

    assert approval["status"] == "approved"
    assert approval["apply_supported"] is False
    assert reviewer.plan_id == "a" * 64
    assert reviewer.confirm_review is True
    assert audit.operations == ["approve_rough_cut"]
    assert resolve.timeouts == []


def test_application_inspects_plans_without_resolve_call() -> None:
    resolve = StubResolveReader()
    audit = StubWorkflowAuditor()
    application = AgentApplication(
        resolve=resolve,
        rough_cut_inspector=StubRoughCutInspector(),
        workflow_audit=audit,
    )

    detail = application.get_rough_cut_plan("a" * 64)
    listing = application.list_rough_cut_plans(limit=10)

    assert detail["effective_status"] == "pending_review"
    assert listing["count"] == 1
    assert audit.operations == [
        "get_rough_cut_plan",
        "list_rough_cut_plans",
    ]
    assert resolve.timeouts == []


def test_application_runs_synchronized_pair_workflow() -> None:
    assembler = StubSynchronizedPairAssembler()
    audit = StubWorkflowAuditor()
    application = AgentApplication(
        resolve=StubResolveReader(),
        synchronized_pair_assembler=assembler,
        workflow_audit=audit,
    )

    result = application.sync_screen_and_webcam(
        timeline_name="M38 Synced Pair",
        screen_asset_id="screen",
        webcam_asset_id="webcam",
        webcam_offset_ms=200,
        confirm_sync=True,
        timeout_seconds=45,
    )

    assert result["status"] == "applied"
    assert assembler.arguments == {
        "timeline_name": "M38 Synced Pair",
        "screen_asset_id": "screen",
        "webcam_asset_id": "webcam",
        "webcam_offset_ms": 200,
        "confirm_sync": True,
        "timeout_seconds": 45,
    }
    assert audit.operations == ["sync_screen_and_webcam"]


def test_application_runs_picture_in_picture_workflow() -> None:
    composer = StubPictureInPictureComposer()
    audit = StubWorkflowAuditor()
    application = AgentApplication(
        resolve=StubResolveReader(),
        picture_in_picture_composer=composer,
        workflow_audit=audit,
    )

    result = application.compose_webcam_picture_in_picture(
        synchronized_pair_receipt_id="a" * 64,
        size_percent=25,
        center_x_percent=82,
        center_y_percent=82,
        confirm_layout=True,
        timeout_seconds=45,
    )

    assert result["status"] == "applied"
    assert composer.arguments == {
        "synchronized_pair_receipt_id": "a" * 64,
        "size_percent": 25,
        "center_x_percent": 82,
        "center_y_percent": 82,
        "confirm_layout": True,
        "timeout_seconds": 45,
    }
    assert audit.operations == ["compose_webcam_picture_in_picture"]


def test_application_runs_synchronized_screen_link_workflow() -> None:
    linker = StubSynchronizedScreenLinker()
    audit = StubWorkflowAuditor()
    application = AgentApplication(
        resolve=StubResolveReader(),
        synchronized_screen_linker=linker,
        workflow_audit=audit,
    )

    result = application.link_synchronized_screen_pair(
        synchronized_pair_receipt_id="a" * 64,
        confirm_link=True,
        timeout_seconds=45,
    )

    assert result["status"] == "applied"
    assert linker.arguments == {
        "synchronized_pair_receipt_id": "a" * 64,
        "confirm_link": True,
        "timeout_seconds": 45,
    }
    assert audit.operations == ["link_synchronized_screen_pair"]


def test_application_previews_synchronized_pause_compaction() -> None:
    previewer = StubPauseCompactionPreviewer()
    audit = StubWorkflowAuditor()
    application = AgentApplication(
        resolve=StubResolveReader(),
        pause_compaction_previewer=previewer,
        workflow_audit=audit,
    )

    result = application.preview_synchronized_pause_compaction(
        plan_id="a" * 64,
        synchronized_pair_receipt_id="b" * 64,
        target_timeline_name="M41 Preview",
        timeout_seconds=45,
    )

    assert result == {"status": "preview", "apply_supported": False}
    assert previewer.arguments == {
        "plan_id": "a" * 64,
        "synchronized_pair_receipt_id": "b" * 64,
        "target_timeline_name": "M41 Preview",
        "timeout_seconds": 45,
    }
    assert audit.operations == ["preview_synchronized_pause_compaction"]


def test_application_applies_synchronized_pause_compaction() -> None:
    applier = StubPauseCompactionApplier()
    audit = StubWorkflowAuditor()
    application = AgentApplication(
        resolve=StubResolveReader(),
        pause_compaction_applier=applier,
        workflow_audit=audit,
    )

    result = application.apply_synchronized_pause_compaction(
        plan_id="a" * 64,
        synchronized_pair_receipt_id="b" * 64,
        target_timeline_name="M42 Apply",
        confirm_apply=True,
        timeout_seconds=45,
    )

    assert result == {"status": "applied", "placement_count": 6}
    assert applier.arguments == {
        "plan_id": "a" * 64,
        "synchronized_pair_receipt_id": "b" * 64,
        "target_timeline_name": "M42 Apply",
        "confirm_apply": True,
        "timeout_seconds": 45,
    }
    assert audit.operations == ["apply_synchronized_pause_compaction"]


def test_application_processes_audio_without_resolve_call() -> None:
    resolve = StubResolveReader()
    media_policy = StubMediaPolicy()
    processor = StubAudioProcessor()
    audit = StubWorkflowAuditor()
    application = AgentApplication(
        resolve=resolve,
        media_policy=media_policy,
        audio_processor=processor,
        workflow_audit=audit,
    )

    report = application.clean_dialogue_audio("dialogue.wav")

    assert report["status"] == "completed"
    assert report["source"]["preserved"] is True
    assert processor.source_file == "normalized:dialogue.wav"
    assert processor.preset == "pcm-dialogue-level-v1"
    assert audit.operations == ["clean_dialogue_audio"]
    assert resolve.timeouts == []


def test_application_inspects_audio_reports_without_resolve_call() -> None:
    resolve = StubResolveReader()
    audit = StubWorkflowAuditor()
    application = AgentApplication(
        resolve=resolve,
        audio_report_inspector=StubAudioReportInspector(),
        workflow_audit=audit,
    )

    detail = application.get_audio_report("b" * 64)
    listing = application.list_audio_reports(limit=10)

    assert detail["status"] == "completed"
    assert listing["count"] == 1
    assert audit.operations == [
        "get_audio_report",
        "list_audio_reports",
    ]
    assert resolve.timeouts == []


@pytest.mark.parametrize("timeout_seconds", [0, -1, 301])
def test_application_rejects_unsafe_timeout(timeout_seconds: float) -> None:
    application = AgentApplication(resolve=StubResolveReader())

    with pytest.raises(ValueError, match="timeout_seconds"):
        application.resolve_get_project(timeout_seconds)
