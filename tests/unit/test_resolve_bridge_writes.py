"""Safe Resolve bridge write-operation tests."""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, cast

import pytest

from bridges.resolve.ResolveBridge import (
    _apply_verified_capabilities,
    collect_bridge_state,
    ensure_runtime_directories,
    process_pending_commands,
)


class FakeMediaItem:
    def __init__(self, asset_id: str, name: str) -> None:
        self._asset_id = asset_id
        self._name = name

    def GetMediaId(self) -> str:
        return self._asset_id

    def GetName(self) -> str:
        return self._name


class FakeTimelineItem:
    def __init__(self, item_id: str, name: str) -> None:
        self._item_id = item_id
        self._name = name

    def GetUniqueId(self) -> str:
        return self._item_id

    def GetName(self) -> str:
        return self._name


class FakeFolder:
    def __init__(self) -> None:
        self.clips: list[FakeMediaItem] = []

    def GetClipList(self) -> list[FakeMediaItem]:
        return self.clips

    def GetSubFolderList(self) -> list[FakeFolder]:
        return []


class FakeTimeline:
    def __init__(self, timeline_id: str, name: str) -> None:
        self._timeline_id = timeline_id
        self._name = name
        self.markers: dict[int, dict[str, Any]] = {}

    def GetUniqueId(self) -> str:
        return self._timeline_id

    def GetName(self) -> str:
        return self._name

    def AddMarker(
        self,
        frame: int,
        color: str,
        name: str,
        note: str,
        duration: int,
        custom_data: str,
    ) -> bool:
        self.markers[frame] = {
            "color": color,
            "name": name,
            "note": note,
            "duration": duration,
            "custom_data": custom_data,
        }
        return True


class FakeMediaPool:
    def __init__(self, project: FakeProject) -> None:
        self._project = project
        self.root = FakeFolder()
        self.appended: list[FakeMediaItem] = []

    def GetRootFolder(self) -> FakeFolder:
        return self.root

    def ImportMedia(self, paths: list[str]) -> list[FakeMediaItem]:
        imported = [
            FakeMediaItem(f"asset-{index}", Path(path).name)
            for index, path in enumerate(paths, start=1)
        ]
        self.root.clips.extend(imported)
        return imported

    def CreateEmptyTimeline(self, name: str) -> FakeTimeline:
        timeline = FakeTimeline(f"timeline-{len(self._project.timelines) + 1}", name)
        self._project.timelines.append(timeline)
        return timeline

    def AppendToTimeline(
        self,
        items: list[FakeMediaItem],
    ) -> list[FakeTimelineItem]:
        self.appended.extend(items)
        return [
            FakeTimelineItem(f"item-{len(self.appended)}", items[0].GetName())
        ]


class FakeProject:
    def __init__(self) -> None:
        self.timelines: list[FakeTimeline] = []
        self.media_pool = FakeMediaPool(self)
        self.current_timeline: FakeTimeline | None = None
        self.render_jobs: list[dict[str, Any]] = []
        self.render_settings: dict[str, Any] = {}
        self.render_format = ""
        self.render_codec = ""
        self.render_mode = 0
        self.render_preset = ""
        self.rendering = False
        self.render_start_count = 0
        self.render_statuses: dict[str, dict[str, Any]] = {}

    def GetName(self) -> str:
        return "M4 Test Project"

    def GetMediaPool(self) -> FakeMediaPool:
        return self.media_pool

    def GetTimelineCount(self) -> int:
        return len(self.timelines)

    def GetTimelineByIndex(self, index: int) -> FakeTimeline | None:
        if 1 <= index <= len(self.timelines):
            return self.timelines[index - 1]
        return None

    def GetCurrentTimeline(self) -> FakeTimeline | None:
        return self.current_timeline

    def SetCurrentTimeline(self, timeline: FakeTimeline) -> bool:
        self.current_timeline = timeline
        return True

    def GetRenderPresetList(self) -> list[str]:
        return ["YouTube - 1080p", "YouTube - 2160p"]

    def LoadRenderPreset(self, preset_name: str) -> bool:
        self.render_preset = preset_name
        return preset_name in {"YouTube - 1080p", "YouTube - 2160p"}

    def GetRenderResolutions(
        self,
        render_format: str,
        codec: str,
    ) -> list[dict[str, int]]:
        assert render_format == "MP4"
        assert codec == "H264"
        return [
            {"Width": 1920, "Height": 1080},
            {"Width": 3840, "Height": 2160},
        ]

    def SetCurrentRenderFormatAndCodec(
        self,
        render_format: str,
        codec: str,
    ) -> bool:
        self.render_format = render_format
        self.render_codec = codec
        return True

    def SetCurrentRenderMode(self, render_mode: int) -> bool:
        self.render_mode = render_mode
        return True

    def SetRenderSettings(self, settings: dict[str, Any]) -> bool:
        self.render_settings = settings
        return True

    def AddRenderJob(self) -> str:
        job_id = f"job-{len(self.render_jobs) + 1}"
        self.render_jobs.append(
            {
                "JobId": job_id,
                "TargetDir": self.render_settings["TargetDir"],
                "OutputFilename": (
                    f"{self.render_settings['CustomName']}.mp4"
                ),
                "PresetName": self.render_preset,
                "VideoFormat": self.render_format,
                "VideoCodec": "H.264",
                "FormatWidth": self.render_settings["FormatWidth"],
                "FormatHeight": self.render_settings["FormatHeight"],
            }
        )
        self.render_statuses[job_id] = {
            "JobStatus": "Ready",
            "CompletionPercentage": 0,
        }
        return job_id

    def GetRenderJobList(self) -> list[dict[str, Any]]:
        return self.render_jobs

    def GetRenderJobStatus(self, job_id: str) -> dict[str, Any]:
        return self.render_statuses[job_id]

    def IsRenderingInProgress(self) -> bool:
        return self.rendering

    def StartRendering(
        self,
        job_ids: list[str],
        interactive: bool,
    ) -> bool:
        assert interactive is False
        if len(job_ids) != 1 or job_ids[0] not in self.render_statuses:
            return False
        self.rendering = True
        self.render_start_count += 1
        self.render_statuses[job_ids[0]] = {
            "JobStatus": "Rendering",
            "CompletionPercentage": 1,
        }
        return True


class FakeProjectManager:
    def __init__(self, project: FakeProject) -> None:
        self.project = project
        self.export_count = 0

    def GetCurrentProject(self) -> FakeProject:
        return self.project

    def SaveProject(self) -> bool:
        return True

    def ExportProject(
        self,
        project_name: str,
        file_path: str,
        with_stills_and_luts: bool,
    ) -> bool:
        assert project_name == self.project.GetName()
        assert with_stills_and_luts is False
        Path(file_path).write_text("project backup", encoding="utf-8")
        self.export_count += 1
        return True


class FakeResolve:
    def __init__(self) -> None:
        self.project = FakeProject()
        self.project_manager = FakeProjectManager(self.project)
        self.current_page = "edit"

    def GetProductName(self) -> str:
        return "DaVinci Resolve"

    def GetVersionString(self) -> str:
        return "21.0.3.7"

    def GetVersion(self) -> list[int]:
        return [21, 0, 3, 7, 0]

    def GetProjectManager(self) -> FakeProjectManager:
        return self.project_manager

    def GetCurrentPage(self) -> str:
        return self.current_page

    def OpenPage(self, page_name: str) -> bool:
        self.current_page = page_name
        return True


def _command(
    command_id: str,
    action: str,
    arguments: dict[str, Any],
    *,
    idempotency_key: str | None = None,
) -> dict[str, Any]:
    now = datetime.now(timezone.utc)
    return {
        "protocol_version": "1.0",
        "command_id": command_id,
        "idempotency_key": idempotency_key or command_id,
        "created_at": now.isoformat(),
        "expires_at": (now + timedelta(minutes=5)).isoformat(),
        "provider": "resolve",
        "action": action,
        "arguments": arguments,
        "safety": {
            "allow_destructive": False,
            "create_backup": True,
        },
    }


def _run_command(
    root: Path,
    resolve: FakeResolve,
    state: dict[str, Any],
    command: dict[str, Any],
) -> dict[str, Any]:
    directories = ensure_runtime_directories(root)
    command_path = directories["commands"] / f"{command['command_id']}.json"
    command_path.write_text(json.dumps(command), encoding="utf-8")
    assert process_pending_commands(directories, state, resolve) == 1
    return cast(
        dict[str, Any],
        json.loads(
            (directories["responses"] / command_path.name).read_text(
                encoding="utf-8"
            )
        ),
    )


def test_write_operations_create_backups_and_structured_results(
    tmp_path: Path,
) -> None:
    resolve = FakeResolve()
    state = collect_bridge_state(resolve)
    media_root = tmp_path / "media"
    media_root.mkdir()
    media_file = media_root / "sample.wav"
    media_file.write_bytes(b"fixture")
    state_directory = tmp_path / "state"
    state_directory.mkdir()
    (state_directory / "media-policy.json").write_text(
        json.dumps(
            {
                "policy_version": "1.0",
                "allowed_roots": [str(media_root)],
            }
        ),
        encoding="utf-8",
    )

    imported = _run_command(
        tmp_path,
        resolve,
        state,
        _command("01-import", "import_media", {"paths": [str(media_file)]}),
    )
    created = _run_command(
        tmp_path,
        resolve,
        state,
        _command("02-create", "create_timeline", {"name": "M4 Timeline"}),
    )
    timeline_id = created["result"]["timeline"]["timeline_id"]
    asset_id = imported["result"]["items"][0]["asset_id"]
    appended = _run_command(
        tmp_path,
        resolve,
        state,
        _command(
            "03-append",
            "append_clip",
            {"timeline_id": timeline_id, "asset_id": asset_id},
        ),
    )
    marker = _run_command(
        tmp_path,
        resolve,
        state,
        _command(
            "04-marker",
            "add_marker",
            {
                "timeline_id": timeline_id,
                "frame": 0,
                "color": "Green",
                "name": "M4",
                "note": "safe marker",
                "duration": 1,
            },
        ),
    )

    assert imported["status"] == "success"
    assert created["status"] == "success"
    assert appended["result"]["items"][0]["name"] == "sample.wav"
    assert marker["result"]["custom_data"] == "davinci-agent:04-marker"
    assert resolve.project.timelines[0].markers[0]["color"] == "Green"
    assert len(list((tmp_path / "backups").glob("*.drp"))) == 4
    assert state["capabilities"]["media.import"] is True
    assert state["capabilities"]["timeline.create"] is True
    assert state["capabilities"]["clip.insert"] is True
    assert state["capabilities"]["marker.create"] is True
    fresh_state = collect_bridge_state(resolve)
    _apply_verified_capabilities(fresh_state, tmp_path / "state")
    assert fresh_state["capabilities"]["media.import"] is True
    assert fresh_state["capabilities"]["timeline.create"] is True
    assert fresh_state["capabilities"]["clip.insert"] is True
    assert fresh_state["capabilities"]["marker.create"] is True


def test_write_command_replays_receipt_without_duplicate_edit(
    tmp_path: Path,
) -> None:
    resolve = FakeResolve()
    state = collect_bridge_state(resolve)
    first = _command(
        "create-first",
        "create_timeline",
        {"name": "Idempotent"},
        idempotency_key="stable-create",
    )
    replay = _command(
        "create-replay",
        "create_timeline",
        {"name": "Idempotent"},
        idempotency_key="stable-create",
    )

    first_response = _run_command(tmp_path, resolve, state, first)
    replay_response = _run_command(tmp_path, resolve, state, replay)

    assert first_response["result"] == replay_response["result"]
    assert replay_response["warnings"] == [
        "Returned the stored idempotent result."
    ]
    assert len(resolve.project.timelines) == 1
    assert resolve.project_manager.export_count == 1


def test_import_outside_bridge_policy_is_rejected_before_backup(
    tmp_path: Path,
) -> None:
    resolve = FakeResolve()
    state = collect_bridge_state(resolve)
    allowed_root = tmp_path / "allowed"
    allowed_root.mkdir()
    outside_file = tmp_path / "outside.wav"
    outside_file.write_bytes(b"fixture")
    state_directory = tmp_path / "state"
    state_directory.mkdir()
    (state_directory / "media-policy.json").write_text(
        json.dumps(
            {
                "policy_version": "1.0",
                "allowed_roots": [str(allowed_root)],
            }
        ),
        encoding="utf-8",
    )

    response = _run_command(
        tmp_path,
        resolve,
        state,
        _command(
            "blocked-import",
            "import_media",
            {"paths": [str(outside_file)]},
        ),
    )

    assert response["status"] == "error"
    assert response["error"]["code"] == "MEDIA_PATH_NOT_ALLOWED"
    assert not list((tmp_path / "backups").glob("*.drp"))


def test_prepare_render_job_is_backed_up_and_replay_safe(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("USERPROFILE", str(tmp_path / "profile"))
    resolve = FakeResolve()
    timeline = resolve.project.media_pool.CreateEmptyTimeline("Render Timeline")
    resolve.project.SetCurrentTimeline(timeline)
    state = collect_bridge_state(resolve)
    first = _command(
        "render-first",
        "prepare_render_job",
        {"custom_name": "M7 Test"},
        idempotency_key="stable-render",
    )
    replay = _command(
        "render-replay",
        "prepare_render_job",
        {"custom_name": "M7 Test"},
        idempotency_key="stable-render",
    )

    first_response = _run_command(tmp_path, resolve, state, first)
    replay_response = _run_command(tmp_path, resolve, state, replay)

    assert first_response["status"] == "success"
    assert first_response["result"] == replay_response["result"]
    assert first_response["result"]["started"] is False
    assert first_response["result"]["format"] == "MP4"
    assert first_response["result"]["codec"] == "H264"
    assert first_response["result"]["width"] == 1920
    assert first_response["result"]["height"] == 1080
    assert Path(first_response["result"]["target_directory"]) == (
        tmp_path
        / "profile"
        / "Videos"
        / "DaVinciResolveAgent"
        / "renders"
    )
    assert len(resolve.project.render_jobs) == 1
    assert resolve.project_manager.export_count == 1
    assert state["capabilities"]["render.configure"] is True
    assert resolve.current_page == "edit"


def test_prepare_render_job_supports_verified_fixed_4k_profile(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("USERPROFILE", str(tmp_path / "profile"))
    resolve = FakeResolve()
    timeline = resolve.project.media_pool.CreateEmptyTimeline("4K Timeline")
    resolve.project.SetCurrentTimeline(timeline)
    state = collect_bridge_state(resolve)

    response = _run_command(
        tmp_path,
        resolve,
        state,
        _command(
            "render-4k",
            "prepare_render_job",
            {
                "custom_name": "M9 4K Test",
                "profile": "youtube-2160p-h264-v1",
            },
        ),
    )

    assert response["status"] == "success"
    assert response["result"]["preset"] == "youtube-2160p-h264-v1"
    assert response["result"]["resolve_preset"] == "YouTube - 2160p"
    assert response["result"]["width"] == 3840
    assert response["result"]["height"] == 2160
    assert resolve.project.render_jobs[0]["FormatWidth"] == 3840
    assert resolve.project.render_jobs[0]["FormatHeight"] == 2160


def test_agent_prepared_render_job_starts_once_and_reports_status(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("USERPROFILE", str(tmp_path / "profile"))
    resolve = FakeResolve()
    timeline = resolve.project.media_pool.CreateEmptyTimeline("Render Timeline")
    resolve.project.SetCurrentTimeline(timeline)
    state = collect_bridge_state(resolve)
    prepared = _run_command(
        tmp_path,
        resolve,
        state,
        _command(
            "render-prepare",
            "prepare_render_job",
            {"custom_name": "M8 Test"},
            idempotency_key="stable-prepare",
        ),
    )
    job_id = prepared["result"]["job_id"]
    first = _command(
        "render-start",
        "start_render_job",
        {"job_id": job_id},
        idempotency_key="stable-start",
    )
    replay = _command(
        "render-start-replay",
        "start_render_job",
        {"job_id": job_id},
        idempotency_key="stable-start",
    )

    first_response = _run_command(tmp_path, resolve, state, first)
    replay_response = _run_command(tmp_path, resolve, state, replay)
    status_command = _command(
        "render-status",
        "get_render_job_status",
        {"job_id": job_id},
    )
    status_command["safety"]["create_backup"] = False
    status_response = _run_command(
        tmp_path,
        resolve,
        state,
        status_command,
    )
    resolve.project.rendering = False
    second_key_response = _run_command(
        tmp_path,
        resolve,
        state,
        _command(
            "render-start-second-key",
            "start_render_job",
            {"job_id": job_id},
            idempotency_key="different-start-key",
        ),
    )

    assert first_response["status"] == "success"
    assert first_response["result"] == replay_response["result"]
    assert first_response["result"]["started"] is True
    assert first_response["result"]["status"]["JobStatus"] == "Rendering"
    assert replay_response["warnings"] == [
        "Returned the stored idempotent result."
    ]
    assert status_response["result"]["rendering_in_progress"] is True
    assert second_key_response["status"] == "error"
    assert second_key_response["error"]["code"] == "RENDER_JOB_ALREADY_STARTED"
    assert resolve.project.render_start_count == 1
    assert resolve.project_manager.export_count == 2
    assert state["capabilities"]["render.start"] is True
    assert len(list((tmp_path / "state" / "render-starts").glob("*.json"))) == 1


def test_unprepared_render_job_cannot_start(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("USERPROFILE", str(tmp_path / "profile"))
    resolve = FakeResolve()
    resolve.project.render_jobs.append(
        {
            "JobId": "foreign-job",
            "TargetDir": str(tmp_path),
            "OutputFilename": "foreign.mp4",
            "PresetName": "YouTube - 1080p",
            "VideoFormat": "MP4",
            "VideoCodec": "H.264",
        }
    )
    resolve.project.render_statuses["foreign-job"] = {"JobStatus": "Ready"}
    state = collect_bridge_state(resolve)

    response = _run_command(
        tmp_path,
        resolve,
        state,
        _command(
            "foreign-start",
            "start_render_job",
            {"job_id": "foreign-job"},
        ),
    )

    assert response["status"] == "error"
    assert response["error"]["code"] == "RENDER_JOB_NOT_AGENT_PREPARED"
    assert resolve.project.render_start_count == 0
    assert resolve.project_manager.export_count == 0
