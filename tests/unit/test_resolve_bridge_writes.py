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
    def __init__(
        self,
        item_id: str,
        name: str,
        *,
        timeline_start: int = 0,
        timeline_end: int = 0,
        source_start: int = 0,
        source_end: int = 0,
        track_type: str = "video",
        track_index: int = 1,
    ) -> None:
        self._item_id = item_id
        self._name = name
        self._timeline_start = timeline_start
        self._timeline_end = timeline_end
        self._source_start = source_start
        self._source_end = source_end
        self._track_type = track_type
        self._track_index = track_index
        self._enabled = True
        self._linked_items: list[FakeTimelineItem] = []
        self._properties: dict[str, bool | float] = {
            "Pan": 0.0,
            "Tilt": 0.0,
            "ZoomGang": True,
            "ZoomX": 1.0,
            "ZoomY": 1.0,
            "RotationAngle": 0.0,
            "Opacity": 100.0,
        }

    def GetUniqueId(self) -> str:
        return self._item_id

    def GetName(self) -> str:
        return self._name

    def GetStart(self, subframe_precision: bool) -> int:
        assert subframe_precision is False
        return self._timeline_start

    def GetEnd(self, subframe_precision: bool) -> int:
        assert subframe_precision is False
        return self._timeline_end

    def GetDuration(self, subframe_precision: bool) -> int:
        assert subframe_precision is False
        return self._timeline_end - self._timeline_start

    def GetSourceStartFrame(self) -> int:
        return self._source_start

    def GetSourceEndFrame(self) -> int:
        return self._source_end

    def GetTrackTypeAndIndex(self) -> list[str | int]:
        return [self._track_type, self._track_index]

    def SetClipEnabled(self, enabled: bool) -> bool:
        self._enabled = enabled
        return True

    def GetClipEnabled(self) -> bool:
        return self._enabled

    def GetLinkedItems(self) -> list[FakeTimelineItem]:
        return self._linked_items

    def SetProperty(self, properties: dict[str, bool | float]) -> bool:
        self._properties.update(properties)
        return True

    def GetProperty(self, key: str) -> bool | float:
        return self._properties[key]


class FakeFolder:
    def __init__(
        self,
        folder_id: str = "folder-root",
        name: str = "Master",
    ) -> None:
        self._folder_id = folder_id
        self._name = name
        self.clips: list[FakeMediaItem] = []
        self.subfolders: list[FakeFolder] = []

    def GetUniqueId(self) -> str:
        return self._folder_id

    def GetName(self) -> str:
        return self._name

    def GetClipList(self) -> list[FakeMediaItem]:
        return self.clips

    def GetSubFolderList(self) -> list[FakeFolder]:
        return self.subfolders


class FakeTimeline:
    def __init__(self, timeline_id: str, name: str) -> None:
        self._timeline_id = timeline_id
        self._name = name
        self._project: FakeProject | None = None
        self.markers: dict[int, dict[str, Any]] = {}
        self.items: list[FakeTimelineItem] = []

    def GetUniqueId(self) -> str:
        return self._timeline_id

    def GetName(self) -> str:
        return self._name

    def DuplicateTimeline(self, name: str) -> FakeTimeline | None:
        if self._project is None:
            return None
        duplicate = FakeTimeline(
            f"timeline-{len(self._project.timelines) + 1}",
            name,
        )
        duplicate._project = self._project
        duplicate.items = list(self.items)
        self._project.timelines.append(duplicate)
        self._project.current_timeline = duplicate
        return duplicate

    def GetStartFrame(self) -> int:
        return 86400

    def GetSetting(self, name: str) -> str:
        settings = {
            "timelineResolutionWidth": "1920",
            "timelineResolutionHeight": "1080",
        }
        return settings[name]

    def GetTrackCount(self, track_type: str) -> int:
        assert track_type in {"video", "audio"}
        return 1

    def GetIsTrackLocked(self, track_type: str, track_index: int) -> bool:
        assert track_type in {"video", "audio"}
        assert track_index == 1
        return False

    def GetItemListInTrack(
        self,
        track_type: str,
        track_index: int,
    ) -> list[FakeTimelineItem]:
        return [
            item
            for item in self.items
            if item.GetTrackTypeAndIndex() == [track_type, track_index]
        ]

    def DeleteClips(
        self,
        timeline_items: list[FakeTimelineItem],
        ripple: bool,
    ) -> bool:
        assert ripple is False
        if len(timeline_items) != 1 or timeline_items[0] not in self.items:
            return False
        self.items.remove(timeline_items[0])
        return True

    def SetClipsLinked(
        self,
        timeline_items: list[FakeTimelineItem],
        linked: bool,
    ) -> bool:
        selected = set(timeline_items)
        for item in timeline_items:
            existing = [
                linked_item
                for linked_item in item._linked_items
                if linked_item not in selected
            ]
            item._linked_items = (
                existing + [peer for peer in timeline_items if peer is not item]
                if linked
                else existing
            )
        return True

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
        timeline._project = self._project
        self._project.timelines.append(timeline)
        return timeline

    def AppendToTimeline(self, items: list[Any]) -> list[FakeTimelineItem]:
        if isinstance(items[0], dict):
            clip_info = items[0]
            media_item = cast(FakeMediaItem, clip_info["mediaPoolItem"])
            self.appended.append(media_item)
            track_type = "video" if clip_info["mediaType"] == 1 else "audio"
            duration = clip_info["endFrame"] - clip_info["startFrame"]
            item = FakeTimelineItem(
                f"item-{len(self.appended)}",
                media_item.GetName(),
                timeline_start=clip_info["recordFrame"],
                timeline_end=clip_info["recordFrame"] + duration,
                source_start=clip_info["startFrame"],
                source_end=clip_info["endFrame"],
                track_type=track_type,
                track_index=clip_info["trackIndex"],
            )
            if self._project.current_timeline is not None:
                self._project.current_timeline.items.append(item)
            return [item]
        media_items = cast(list[FakeMediaItem], items)
        self.appended.extend(media_items)
        item = FakeTimelineItem(
            f"item-{len(self.appended)}",
            media_items[0].GetName(),
        )
        if self._project.current_timeline is not None:
            self._project.current_timeline.items.append(item)
        return [item]


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

    def GetRenderFormats(self) -> dict[str, str]:
        return {"mp4": "mp4"}

    def GetRenderCodecs(self, render_format: str) -> dict[str, str]:
        assert render_format == "mp4"
        return {"H.264": "H264"}

    def GetCurrentRenderFormatAndCodec(self) -> dict[str, str]:
        return {"format": "mp4", "codec": "H264"}

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
    allow_destructive: bool = False,
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
            "allow_destructive": allow_destructive,
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


def test_timeline_duplication_is_backed_up_and_replay_safe(
    tmp_path: Path,
) -> None:
    resolve = FakeResolve()
    source = resolve.project.media_pool.CreateEmptyTimeline("Source")
    resolve.project.SetCurrentTimeline(source)
    state = collect_bridge_state(resolve)
    arguments = {
        "timeline_id": source.GetUniqueId(),
        "name": "Source - Agent Draft",
    }
    first = _command(
        "duplicate-first",
        "duplicate_timeline",
        arguments,
        idempotency_key="stable-duplicate",
    )
    replay = _command(
        "duplicate-replay",
        "duplicate_timeline",
        arguments,
        idempotency_key="stable-duplicate",
    )

    first_response = _run_command(tmp_path, resolve, state, first)
    replay_response = _run_command(tmp_path, resolve, state, replay)

    assert first_response["status"] == "success"
    assert first_response["result"] == replay_response["result"]
    assert first_response["result"]["source_timeline"] == {
        "timeline_id": source.GetUniqueId(),
        "name": "Source",
    }
    duplicate = first_response["result"]["timeline"]
    assert duplicate["timeline_id"] != source.GetUniqueId()
    assert duplicate["name"] == "Source - Agent Draft"
    assert first_response["result"]["current_timeline"] == {
        "timeline_id": source.GetUniqueId(),
        "name": "Source",
    }
    assert resolve.project.GetTimelineCount() == 2
    assert resolve.project.GetCurrentTimeline() is source
    assert resolve.project_manager.export_count == 1
    assert replay_response["warnings"] == [
        "Returned the stored idempotent result."
    ]
    assert state["capabilities"]["timeline.duplicate"] is True


def test_current_timeline_selection_is_backed_up_and_replay_safe(
    tmp_path: Path,
) -> None:
    resolve = FakeResolve()
    first_timeline = resolve.project.media_pool.CreateEmptyTimeline("First")
    second_timeline = resolve.project.media_pool.CreateEmptyTimeline("Second")
    resolve.project.SetCurrentTimeline(first_timeline)
    state = collect_bridge_state(resolve)
    first = _command(
        "select-first",
        "set_current_timeline",
        {"timeline_id": second_timeline.GetUniqueId()},
        idempotency_key="stable-select",
    )
    replay = _command(
        "select-replay",
        "set_current_timeline",
        first["arguments"],
        idempotency_key="stable-select",
    )

    first_response = _run_command(tmp_path, resolve, state, first)
    replay_response = _run_command(tmp_path, resolve, state, replay)

    assert first_response["status"] == "success"
    assert first_response["result"] == replay_response["result"]
    assert first_response["result"]["previous_timeline"] == {
        "timeline_id": first_timeline.GetUniqueId(),
        "name": "First",
    }
    assert first_response["result"]["timeline"] == {
        "timeline_id": second_timeline.GetUniqueId(),
        "name": "Second",
    }
    assert resolve.project.GetCurrentTimeline() is second_timeline
    assert state["current_timeline_id"] == second_timeline.GetUniqueId()
    assert state["current_timeline_name"] == "Second"
    assert resolve.project_manager.export_count == 1
    assert replay_response["warnings"] == [
        "Returned the stored idempotent result."
    ]
    assert state["capabilities"]["timeline.select"] is True


def test_ranged_clip_insert_is_backed_up_and_replay_safe(
    tmp_path: Path,
) -> None:
    resolve = FakeResolve()
    timeline = resolve.project.media_pool.CreateEmptyTimeline("M10 Short")
    resolve.project.SetCurrentTimeline(timeline)
    media_item = FakeMediaItem("asset-1", "source.mkv")
    resolve.project.media_pool.root.clips.append(media_item)
    state = collect_bridge_state(resolve)
    first = _command(
        "insert-first",
        "insert_clip",
        {
            "timeline_id": timeline.GetUniqueId(),
            "asset_id": media_item.GetMediaId(),
            "source_start_frame": 0,
            "source_end_frame": 240,
            "position_frames": 0,
            "track_type": "video",
            "track_index": 1,
        },
        idempotency_key="stable-insert",
    )
    replay = _command(
        "insert-replay",
        "insert_clip",
        first["arguments"],
        idempotency_key="stable-insert",
    )

    first_response = _run_command(tmp_path, resolve, state, first)
    replay_response = _run_command(tmp_path, resolve, state, replay)

    assert first_response["status"] == "success"
    assert first_response["result"] == replay_response["result"]
    assert replay_response["warnings"] == [
        "Returned the stored idempotent result."
    ]
    assert first_response["result"]["item"] == {
        "timeline_item_id": "item-1",
        "name": "source.mkv",
        "timeline_start_frame": 86400,
        "timeline_end_frame": 86640,
        "source_start_frame": 0,
        "source_end_frame": 240,
        "track_type": "video",
        "track_index": 1,
    }
    assert len(resolve.project.media_pool.appended) == 1
    assert resolve.project_manager.export_count == 1
    assert state["capabilities"]["clip.range_insert"] is True


def test_clip_enabled_state_is_backed_up_read_back_and_replay_safe(
    tmp_path: Path,
) -> None:
    resolve = FakeResolve()
    timeline = resolve.project.media_pool.CreateEmptyTimeline("M12 Enable")
    resolve.project.SetCurrentTimeline(timeline)
    item = FakeTimelineItem("item-1", "source.mkv")
    timeline.items.append(item)
    state = collect_bridge_state(resolve)
    first = _command(
        "disable-first",
        "set_clip_enabled",
        {
            "timeline_id": timeline.GetUniqueId(),
            "timeline_item_id": item.GetUniqueId(),
            "enabled": False,
        },
        idempotency_key="stable-disable",
    )
    replay = _command(
        "disable-replay",
        "set_clip_enabled",
        first["arguments"],
        idempotency_key="stable-disable",
    )

    first_response = _run_command(tmp_path, resolve, state, first)
    replay_response = _run_command(tmp_path, resolve, state, replay)

    assert first_response["status"] == "success"
    assert first_response["result"] == replay_response["result"]
    assert first_response["result"]["previous_enabled"] is True
    assert first_response["result"]["enabled"] is False
    assert first_response["result"]["track_type"] == "video"
    assert item.GetClipEnabled() is False
    assert resolve.project_manager.export_count == 1
    assert replay_response["warnings"] == [
        "Returned the stored idempotent result."
    ]
    assert state["capabilities"]["clip.enable"] is True


def test_clip_links_are_backed_up_read_back_and_replay_safe(
    tmp_path: Path,
) -> None:
    resolve = FakeResolve()
    timeline = resolve.project.media_pool.CreateEmptyTimeline("M19 Links")
    resolve.project.SetCurrentTimeline(timeline)
    video = FakeTimelineItem("video-1", "source.mkv", track_type="video")
    audio = FakeTimelineItem("audio-1", "source.mkv", track_type="audio")
    timeline.items.extend([video, audio])
    state = collect_bridge_state(resolve)
    arguments = {
        "timeline_id": timeline.GetUniqueId(),
        "timeline_item_ids": ["video-1", "audio-1"],
        "linked": True,
    }
    first = _command(
        "link-first",
        "set_clips_linked",
        arguments,
        idempotency_key="stable-link",
    )
    replay = _command(
        "link-replay",
        "set_clips_linked",
        arguments,
        idempotency_key="stable-link",
    )
    unlink = _command(
        "unlink",
        "set_clips_linked",
        {**arguments, "linked": False},
        idempotency_key="stable-unlink",
    )

    first_response = _run_command(tmp_path, resolve, state, first)
    replay_response = _run_command(tmp_path, resolve, state, replay)

    assert first_response["status"] == "success"
    assert first_response["result"] == replay_response["result"]
    assert first_response["result"]["linked"] is True
    assert first_response["result"]["items"][0]["linked_item_ids"] == [
        "audio-1"
    ]
    assert first_response["result"]["items"][1]["linked_item_ids"] == [
        "video-1"
    ]
    assert resolve.project_manager.export_count == 1
    assert replay_response["warnings"] == [
        "Returned the stored idempotent result."
    ]

    unlink_response = _run_command(tmp_path, resolve, state, unlink)

    assert unlink_response["status"] == "success"
    assert unlink_response["result"]["linked"] is False
    assert all(
        not item["linked_item_ids"]
        for item in unlink_response["result"]["items"]
    )
    assert resolve.project_manager.export_count == 2
    assert state["capabilities"]["clip.link"] is True


def test_timeline_items_are_discovered_with_bounded_metadata(
    tmp_path: Path,
) -> None:
    resolve = FakeResolve()
    timeline = resolve.project.media_pool.CreateEmptyTimeline("M16 Items")
    resolve.project.SetCurrentTimeline(timeline)
    timeline.items.extend(
        [
            FakeTimelineItem(
                "video-1",
                "screen.mkv",
                timeline_start=86400,
                timeline_end=86640,
                source_start=0,
                source_end=240,
                track_type="video",
            ),
            FakeTimelineItem(
                "audio-1",
                "screen.mkv",
                timeline_start=86400,
                timeline_end=86640,
                source_start=0,
                source_end=240,
                track_type="audio",
            ),
        ]
    )
    state = collect_bridge_state(resolve)
    command = _command(
        "list-items",
        "list_timeline_items",
        {"timeline_id": timeline.GetUniqueId()},
    )
    command["safety"]["create_backup"] = False

    response = _run_command(tmp_path, resolve, state, command)

    assert response["status"] == "success"
    assert response["result"]["timeline_id"] == timeline.GetUniqueId()
    assert response["result"]["items"] == [
        {
            "timeline_item_id": "video-1",
            "name": "screen.mkv",
            "track_type": "video",
            "track_index": 1,
            "duration_frames": 240,
            "timeline_start_frame": 86400,
            "timeline_end_frame": 86640,
            "source_start_frame": 0,
            "source_end_frame": 240,
        },
        {
            "timeline_item_id": "audio-1",
            "name": "screen.mkv",
            "track_type": "audio",
            "track_index": 1,
            "duration_frames": 240,
            "timeline_start_frame": 86400,
            "timeline_end_frame": 86640,
            "source_start_frame": 0,
            "source_end_frame": 240,
        },
    ]
    assert resolve.project_manager.export_count == 0
    assert state["capabilities"]["clip.read"] is True


def test_media_pool_items_are_discovered_recursively_without_backup(
    tmp_path: Path,
) -> None:
    resolve = FakeResolve()
    root = resolve.project.media_pool.root
    root.clips.append(FakeMediaItem("asset-root", "screen.mkv"))
    child = FakeFolder("folder-child", "Interviews")
    child.clips.append(FakeMediaItem("asset-child", "webcam.mkv"))
    root.subfolders.append(child)
    state = collect_bridge_state(resolve)
    command = _command("list-items", "list_media_pool_items", {})
    command["safety"]["create_backup"] = False

    response = _run_command(tmp_path, resolve, state, command)

    assert response["status"] == "success"
    assert response["result"] == {
        "items": [
            {
                "asset_id": "asset-root",
                "name": "screen.mkv",
                "folder_id": "folder-root",
                "folder_path": ["Master"],
            },
            {
                "asset_id": "asset-child",
                "name": "webcam.mkv",
                "folder_id": "folder-child",
                "folder_path": ["Master", "Interviews"],
            },
        ],
        "folder_count": 2,
    }
    assert resolve.project_manager.export_count == 0
    assert state["capabilities"]["media.read"] is True


def test_workspace_snapshot_collects_read_only_sections_in_one_command(
    tmp_path: Path,
) -> None:
    resolve = FakeResolve()
    timeline = FakeTimeline("timeline-main", "Main")
    timeline.items.append(
        FakeTimelineItem(
            "item-video",
            "screen.mkv",
            timeline_start=86400,
            timeline_end=86496,
            source_start=0,
            source_end=240,
        )
    )
    resolve.project.timelines.append(timeline)
    resolve.project.current_timeline = timeline
    resolve.project.media_pool.root.clips.append(
        FakeMediaItem("asset-screen", "screen.mkv")
    )
    state = collect_bridge_state(resolve)
    command = _command("workspace-snapshot", "get_workspace_snapshot", {})
    command["safety"]["create_backup"] = False

    response = _run_command(tmp_path, resolve, state, command)

    assert response["status"] == "success"
    result = response["result"]
    assert result["project"] == {"name": "M4 Test Project"}
    assert result["current_timeline"] == {
        "timeline_id": "timeline-main",
        "name": "Main",
    }
    assert result["timeline_items"]["items"][0]["timeline_item_id"] == (
        "item-video"
    )
    assert result["media_pool"]["items"][0]["asset_id"] == "asset-screen"
    assert result["render"]["current"] == {
        "format": "mp4",
        "codec": "H264",
    }
    assert not list((tmp_path / "backups").glob("*.drp"))
    assert state["capabilities"]["clip.read"] is True
    assert state["capabilities"]["media.read"] is True
    assert state["capabilities"]["render.discovery"] is True


def test_clip_transform_is_bounded_backed_up_and_replay_safe(
    tmp_path: Path,
) -> None:
    resolve = FakeResolve()
    timeline = resolve.project.media_pool.CreateEmptyTimeline("M14 Transform")
    resolve.project.SetCurrentTimeline(timeline)
    item = FakeTimelineItem("item-1", "source.mkv")
    timeline.items.append(item)
    state = collect_bridge_state(resolve)
    arguments = {
        "timeline_id": timeline.GetUniqueId(),
        "timeline_item_id": item.GetUniqueId(),
        "position_x": 320.0,
        "position_y": -180.0,
        "zoom": 0.5,
        "rotation_degrees": 5.0,
        "opacity_percent": 80.0,
    }
    first = _command(
        "transform-first",
        "set_clip_transform",
        arguments,
        idempotency_key="stable-transform",
    )
    replay = _command(
        "transform-replay",
        "set_clip_transform",
        arguments,
        idempotency_key="stable-transform",
    )

    first_response = _run_command(tmp_path, resolve, state, first)
    replay_response = _run_command(tmp_path, resolve, state, replay)

    assert first_response["status"] == "success"
    assert first_response["result"] == replay_response["result"]
    assert first_response["result"]["previous_properties"] == {
        "Pan": 0.0,
        "Tilt": 0.0,
        "ZoomGang": True,
        "ZoomX": 1.0,
        "ZoomY": 1.0,
        "RotationAngle": 0.0,
        "Opacity": 100.0,
    }
    assert first_response["result"]["properties"] == {
        "Pan": 320.0,
        "Tilt": -180.0,
        "ZoomGang": True,
        "ZoomX": 0.5,
        "ZoomY": 0.5,
        "RotationAngle": 5.0,
        "Opacity": 80.0,
    }
    assert resolve.project_manager.export_count == 1
    assert replay_response["warnings"] == [
        "Returned the stored idempotent result."
    ]
    assert state["capabilities"]["clip.transform"] is True


def test_clip_delete_requires_destructive_flag_backup_and_replays_safely(
    tmp_path: Path,
) -> None:
    resolve = FakeResolve()
    timeline = resolve.project.media_pool.CreateEmptyTimeline("M15 Delete")
    resolve.project.SetCurrentTimeline(timeline)
    item = FakeTimelineItem(
        "item-1",
        "disposable.mkv",
        timeline_start=86400,
        timeline_end=86640,
    )
    timeline.items.append(item)
    state = collect_bridge_state(resolve)
    arguments = {
        "timeline_id": timeline.GetUniqueId(),
        "timeline_item_id": item.GetUniqueId(),
        "confirm_delete": True,
    }
    first = _command(
        "delete-first",
        "delete_clip",
        arguments,
        idempotency_key="stable-delete",
        allow_destructive=True,
    )
    replay = _command(
        "delete-replay",
        "delete_clip",
        arguments,
        idempotency_key="stable-delete",
        allow_destructive=True,
    )

    first_response = _run_command(tmp_path, resolve, state, first)
    replay_response = _run_command(tmp_path, resolve, state, replay)

    assert first_response["status"] == "success"
    assert first_response["result"] == replay_response["result"]
    assert first_response["result"]["deleted"] is True
    assert first_response["result"]["ripple"] is False
    assert first_response["result"]["item"] == {
        "timeline_item_id": "item-1",
        "name": "disposable.mkv",
        "timeline_start_frame": 86400,
        "timeline_end_frame": 86640,
        "track_type": "video",
        "track_index": 1,
    }
    assert timeline.items == []
    assert resolve.project_manager.export_count == 1
    assert replay_response["warnings"] == [
        "Returned the stored idempotent result."
    ]
    assert state["capabilities"]["clip.delete"] is True


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
