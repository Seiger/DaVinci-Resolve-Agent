"""Resolve bridge tests using a documented-API simulation."""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

from bridges.resolve.ResolveBridge import (
    collect_bridge_state,
    ensure_runtime_directories,
    get_resolve_application,
    process_pending_commands,
)


class FakeTimeline:
    def __init__(self, name: str) -> None:
        self._name = name

    def GetName(self) -> str:
        return self._name


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


class FakeProjectManager:
    def __init__(self, project: FakeProject | None) -> None:
        self._project = project

    def GetCurrentProject(self) -> FakeProject | None:
        return self._project


class FakeResolve:
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
    assert state["current_timeline_name"] == "Main"
    assert state["timelines"] == [
        {"index": 1, "name": "Main"},
        {"index": 2, "name": "B-roll"},
    ]
    assert state["capabilities"]["project.read"] is True
    assert state["capabilities"]["timeline.read"] is True
    assert state["capabilities"]["timeline.create"] == "unknown"


def test_collect_bridge_state_handles_no_open_project() -> None:
    state = collect_bridge_state(FakeResolve(), heartbeat="2026-07-30T12:00:00Z")

    assert state["project_open"] is False
    assert state["project_name"] is None
    assert state["current_timeline_name"] is None
    assert state["capabilities"]["timeline.read"] == "unknown"


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
