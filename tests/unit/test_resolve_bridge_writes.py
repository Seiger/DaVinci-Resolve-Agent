"""Safe Resolve bridge write-operation tests."""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, cast

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

    def GetProductName(self) -> str:
        return "DaVinci Resolve"

    def GetVersionString(self) -> str:
        return "21.0.3.7"

    def GetVersion(self) -> list[int]:
        return [21, 0, 3, 7, 0]

    def GetProjectManager(self) -> FakeProjectManager:
        return self.project_manager


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
