"""Resolve bridge tests using a documented-API simulation."""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from bridges.resolve import ResolveBridge as resolve_bridge
from bridges.resolve.ResolveBridge import (
    atomic_write_json,
    collect_bridge_state,
    command_result,
    ensure_runtime_directories,
    get_resolve_application,
    process_pending_commands,
    run_persistent_bridge,
)


def test_bridge_atomic_write_retries_transient_permission_error(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    destination = tmp_path / "bridge.json"
    original_replace = Path.replace
    attempts = 0

    def replace_with_transient_denial(source: Path, target: Path) -> Path:
        nonlocal attempts
        attempts += 1
        if attempts < 3:
            raise PermissionError("simulated Windows sharing violation")
        return original_replace(source, target)

    monkeypatch.setattr(Path, "replace", replace_with_transient_denial)

    atomic_write_json(
        destination,
        {"status": "ready"},
        retry_delay_seconds=0,
    )

    assert attempts == 3
    assert json.loads(destination.read_text(encoding="utf-8")) == {
        "status": "ready"
    }
    assert list(tmp_path.glob("*.tmp")) == []


def test_bridge_atomic_write_cleans_temporary_file_after_final_denial(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def always_deny(source: Path, target: Path) -> Path:
        raise PermissionError("persistent Windows sharing violation")

    monkeypatch.setattr(Path, "replace", always_deny)

    with pytest.raises(PermissionError, match="persistent Windows"):
        atomic_write_json(
            tmp_path / "bridge.json",
            {"status": "ready"},
            attempts=2,
            retry_delay_seconds=0,
        )

    assert list(tmp_path.glob("*.tmp")) == []


def test_persistent_bridge_survives_deferred_state_publication(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    directories = ensure_runtime_directories(tmp_path)
    original_writer = resolve_bridge.atomic_write_json
    calls = 0

    def deny_first_two_writes(path: Path, payload: dict[str, object]) -> None:
        nonlocal calls
        calls += 1
        if calls <= 2:
            raise PermissionError("simulated continuous reader")
        original_writer(path, payload)

    monkeypatch.setattr(
        resolve_bridge,
        "atomic_write_json",
        deny_first_two_writes,
    )

    state, processed = run_persistent_bridge(
        FakeResolve(FakeProject()),
        directories,
        sleep=lambda _: None,
        max_iterations=2,
    )

    assert processed == 0
    assert state["status"] == "ready"
    assert json.loads(
        (directories["state"] / "bridge.json").read_text(encoding="utf-8")
    )["status"] == "ready"
    log = (directories["logs"] / "bridge.jsonl").read_text(encoding="utf-8")
    assert log.count('"event": "state_publish_deferred"') == 2


class FakeTimeline:
    def __init__(self, name: str) -> None:
        self._name = name

    def GetUniqueId(self) -> str:
        return f"id-{self._name.casefold()}"

    def GetName(self) -> str:
        return self._name

    def GetTrackCount(self, track_type: str) -> int:
        return 0 if track_type == "subtitle" else 1

    def GetTrackName(self, track_type: str, index: int) -> str:
        return f"{track_type}-{index}"

    def GetItemListInTrack(
        self,
        track_type: str,
        index: int,
    ) -> list[str]:
        assert index == 1
        return ["item"] if track_type == "video" else []

    def CreateSubtitlesFromAudio(self, settings: dict[object, object]) -> bool:
        raise AssertionError("Read-only discovery must not create subtitles.")


class FakeProject:
    def __init__(self) -> None:
        self._timelines = [FakeTimeline("Main"), FakeTimeline("B-roll")]

    def GetName(self) -> str:
        return "M1 Test Project"

    def GetTimelineCount(self) -> int:
        return len(self._timelines)

    def GetTimelineByIndex(self, index: int) -> FakeTimeline | None:
        if 1 <= index <= len(self._timelines):
            return self._timelines[index - 1]
        return None

    def GetCurrentTimeline(self) -> FakeTimeline:
        return self._timelines[0]

    def GetRenderFormats(self) -> dict[str, str]:
        return {"mp4": "mp4", "mov": "mov"}

    def GetRenderCodecs(self, render_format: str) -> dict[str, str]:
        return (
            {"H.264": "H264"}
            if render_format == "mp4"
            else {"DNxHR": "DNxHR"}
        )

    def GetCurrentRenderFormatAndCodec(self) -> dict[str, str]:
        return {"format": "mp4", "codec": "H264"}

    def GetRenderPresetList(self) -> list[dict[str, str]]:
        return [{"Name": "H.264 Master"}]

    def GetRenderJobList(self) -> list[dict[str, str]]:
        return [{"JobId": "job-1", "JobStatus": "Ready"}]

    def GetRenderResolutions(
        self,
        render_format: str,
        codec: str,
    ) -> list[dict[str, int]]:
        assert render_format == "MP4"
        assert codec == "H264"
        return [
            {"Width": 3840, "Height": 2160},
            {"Width": 1920, "Height": 1080},
        ]


class FakeProjectManager:
    def __init__(self, project: FakeProject | None) -> None:
        self._project = project

    def GetCurrentProject(self) -> FakeProject | None:
        return self._project


class FakeResolve:
    SUBTITLE_LANGUAGE = "subtitle-language"
    SUBTITLE_CAPTION_PRESET = "subtitle-caption-preset"
    SUBTITLE_CHARS_PER_LINE = "subtitle-characters-per-line"
    SUBTITLE_LINE_BREAK = "subtitle-line-break"
    SUBTITLE_GAP = "subtitle-gap"
    AUTO_CAPTION_AUTO = "auto-caption-auto"
    AUTO_CAPTION_SUBTITLE_DEFAULT = "auto-caption-default"
    AUTO_CAPTION_LINE_SINGLE = "auto-caption-line-single"

    def __init__(self, project: FakeProject | None = None) -> None:
        self._project_manager = FakeProjectManager(project)

    def GetProductName(self) -> str:
        return "DaVinci Resolve"

    def GetVersionString(self) -> str:
        return "21.0.3.7"

    def GetVersion(self) -> list[int]:
        return [21, 0, 3, 7, 0]

    def GetProjectManager(self) -> FakeProjectManager:
        return self._project_manager


class FakeFusion:
    def __init__(self, resolve: FakeResolve) -> None:
        self._resolve = resolve

    def GetResolve(self) -> FakeResolve:
        return self._resolve


def test_internal_resolve_context_is_preferred() -> None:
    resolve = FakeResolve(FakeProject())

    assert get_resolve_application({"resolve": resolve}) is resolve
    assert get_resolve_application({"app": resolve}) is resolve
    assert get_resolve_application({"fusion": FakeFusion(resolve)}) is resolve


def test_collect_bridge_state_uses_read_only_documented_api() -> None:
    state = collect_bridge_state(
        FakeResolve(FakeProject()),
        heartbeat="2026-07-30T12:00:00Z",
    )

    assert state["status"] == "ready"
    assert state["product_name"] == "DaVinci Resolve"
    assert state["resolve_version"] == "21.0.3.7"
    assert state["project_name"] == "M1 Test Project"
    assert state["current_timeline_id"] == "id-main"
    assert state["current_timeline_name"] == "Main"
    assert state["timelines"] == [
        {"timeline_id": "id-main", "index": 1, "name": "Main"},
        {"timeline_id": "id-b-roll", "index": 2, "name": "B-roll"},
    ]
    assert state["capabilities"]["project.read"] is True
    assert state["capabilities"]["timeline.read"] is True
    assert state["capabilities"]["timeline.create"] == "unknown"
    assert state["capabilities"]["subtitle.read"] == "unknown"
    assert state["capabilities"]["subtitle.auto_caption"] == "unknown"
    assert state["capabilities"]["subtitle.import"] == "unknown"


def test_subtitle_environment_is_bounded_and_read_only() -> None:
    resolve = FakeResolve(FakeProject())
    state = collect_bridge_state(resolve)

    result = command_result(
        "get_subtitle_environment",
        state,
        resolve,
        {"timeline_id": "id-main"},
    )

    assert result["timeline_id"] == "id-main"
    assert result["subtitle_track_count"] == 0
    assert result["subtitle_item_count"] == 0
    assert result["tracks"] == []
    assert result["auto_caption"] == {
        "method_available": True,
        "required_constants_available": True,
        "missing_constants": [],
        "fixed_policy": {
            "language": "auto",
            "caption_preset": "default",
            "characters_per_line": 42,
            "line_break": "single",
            "gap_frames": 0,
        },
        "verified": False,
    }


def test_collect_bridge_state_handles_no_open_project() -> None:
    state = collect_bridge_state(FakeResolve(), heartbeat="2026-07-30T12:00:00Z")

    assert state["project_open"] is False
    assert state["project_name"] is None
    assert state["current_timeline_id"] is None
    assert state["current_timeline_name"] is None
    assert state["capabilities"]["timeline.read"] == "unknown"


def test_render_environment_uses_documented_read_only_api() -> None:
    resolve = FakeResolve(FakeProject())
    state = collect_bridge_state(resolve)

    result = command_result("get_render_environment", state, resolve)

    assert result == {
        "formats": [
            {
                "format": "mov",
                "extension": "mov",
                "codecs": [
                    {"description": "DNxHR", "codec": "DNxHR"}
                ],
            },
            {
                "format": "mp4",
                "extension": "mp4",
                "codecs": [
                    {"description": "H.264", "codec": "H264"}
                ],
            },
        ],
        "current": {"format": "mp4", "codec": "H264"},
        "presets": [{"Name": "H.264 Master"}],
        "jobs": [{"JobId": "job-1", "JobStatus": "Ready"}],
        "mp4_h264_resolutions": [
            {"width": 1920, "height": 1080},
            {"width": 3840, "height": 2160},
        ],
        "timeline": {
            "name": "Main",
            "video_track_count": 1,
            "audio_track_count": 1,
            "video_item_count": 1,
            "audio_item_count": 0,
        },
    }


def test_ping_command_is_claimed_and_answered(tmp_path: Path) -> None:
    directories = ensure_runtime_directories(tmp_path)
    now = datetime.now(timezone.utc)
    command = {
        "protocol_version": "1.0",
        "command_id": "ping-1",
        "idempotency_key": "ping-1",
        "created_at": now.isoformat(),
        "expires_at": (now + timedelta(minutes=5)).isoformat(),
        "provider": "resolve",
        "action": "ping",
        "arguments": {},
        "safety": {
            "allow_destructive": False,
            "create_backup": False,
        },
    }
    command_path = directories["commands"] / "ping-1.json"
    command_path.write_text(json.dumps(command), encoding="utf-8")
    state = collect_bridge_state(FakeResolve(FakeProject()))

    assert process_pending_commands(directories, state) == 1

    response = json.loads(
        (directories["responses"] / "ping-1.json").read_text(encoding="utf-8")
    )
    assert response["status"] == "success"
    assert response["result"] == {"message": "pong"}
    assert not command_path.exists()
    assert not (directories["processing"] / "ping-1.json").exists()


def test_persistent_bridge_heartbeats_and_stops_cleanly(tmp_path: Path) -> None:
    directories = ensure_runtime_directories(tmp_path)
    now = datetime.now(timezone.utc)
    command = {
        "protocol_version": "1.0",
        "command_id": "stop-1",
        "idempotency_key": "stop-1",
        "created_at": now.isoformat(),
        "expires_at": (now + timedelta(minutes=5)).isoformat(),
        "provider": "resolve",
        "action": "stop_bridge",
        "arguments": {},
        "safety": {
            "allow_destructive": False,
            "create_backup": False,
        },
    }
    (directories["commands"] / "stop-1.json").write_text(
        json.dumps(command), encoding="utf-8"
    )

    state, processed = run_persistent_bridge(
        FakeResolve(FakeProject()),
        directories,
        sleep=lambda _: None,
    )

    assert processed == 1
    assert state["status"] == "stopped"
    assert state["lifecycle"]["mode"] == "stopped"
    response = json.loads(
        (directories["responses"] / "stop-1.json").read_text(encoding="utf-8")
    )
    assert response["result"] == {"status": "stopping"}


def test_unsafe_command_is_rejected_and_preserved(tmp_path: Path) -> None:
    directories = ensure_runtime_directories(tmp_path)
    now = datetime.now(timezone.utc)
    command = {
        "protocol_version": "1.0",
        "command_id": "unsafe-1",
        "idempotency_key": "unsafe-1",
        "created_at": now.isoformat(),
        "expires_at": (now + timedelta(minutes=5)).isoformat(),
        "provider": "resolve",
        "action": "execute_python",
        "arguments": {},
        "safety": {
            "allow_destructive": False,
            "create_backup": False,
        },
    }
    (directories["commands"] / "unsafe-1.json").write_text(
        json.dumps(command),
        encoding="utf-8",
    )

    assert process_pending_commands(directories, {}) == 1

    response = json.loads(
        (directories["responses"] / "unsafe-1.json").read_text(encoding="utf-8")
    )
    assert response["status"] == "error"
    assert response["error"]["code"] == "INVALID_OR_UNSUPPORTED_COMMAND"
    assert (directories["failed"] / "unsafe-1.json").is_file()
