"""CLI integration through the real filesystem client and bridge processor."""

from __future__ import annotations

import threading
import time
from pathlib import Path

import pytest

from agent.cli import EXIT_TIMEOUT, main
from agent.paths import runtime_directory
from bridges.resolve.ResolveBridge import (
    collect_bridge_state,
    ensure_runtime_directories,
    process_pending_commands,
)


class FakeTimeline:
    def GetName(self) -> str:
        return "Main"


class FakeProject:
    def GetName(self) -> str:
        return "CLI Project"

    def GetTimelineCount(self) -> int:
        return 1

    def GetTimelineByIndex(self, index: int) -> FakeTimeline | None:
        return FakeTimeline() if index == 1 else None

    def GetCurrentTimeline(self) -> FakeTimeline:
        return FakeTimeline()


class FakeProjectManager:
    def GetCurrentProject(self) -> FakeProject:
        return FakeProject()


class FakeResolve:
    def GetProductName(self) -> str:
        return "DaVinci Resolve"

    def GetVersionString(self) -> str:
        return "21.0.3.7"

    def GetVersion(self) -> list[int]:
        return [21, 0, 3, 7, 0]

    def GetProjectManager(self) -> FakeProjectManager:
        return FakeProjectManager()


def _process_one_command(runtime_root: Path) -> None:
    directories = ensure_runtime_directories(runtime_root)
    state = collect_bridge_state(FakeResolve())
    deadline = time.monotonic() + 2
    while time.monotonic() < deadline:
        if list(directories["commands"].glob("*.json")):
            process_pending_commands(directories, state)
            return
        time.sleep(0.01)
    raise AssertionError("CLI command did not appear.")


def test_cli_ping_round_trip(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))
    root = runtime_directory({"LOCALAPPDATA": str(tmp_path)})
    worker = threading.Thread(target=_process_one_command, args=(root,))
    worker.start()

    assert main(["ping", "--timeout-seconds", "2"]) == 0
    worker.join(timeout=2)

    assert not worker.is_alive()
    assert capsys.readouterr().out.strip() == "pong"


def test_cli_timeout_has_distinct_exit_code(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))

    assert main(["ping", "--timeout-seconds", "0.03"]) == EXIT_TIMEOUT
    assert "timed out" in capsys.readouterr().err
