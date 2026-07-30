"""Provider-neutral filesystem command-client tests."""

from __future__ import annotations

import threading
import time
from pathlib import Path
from typing import Any

import pytest

from agent.client import CommandTimeoutError, FilesystemCommandClient
from transports.filesystem import (
    FilesystemLayout,
    atomic_write_json,
    read_json_object,
)


def _respond_to_first_command(layout: FilesystemLayout) -> None:
    deadline = time.monotonic() + 2
    while time.monotonic() < deadline:
        command_paths = list(layout.commands.glob("*.json"))
        if command_paths:
            command = read_json_object(command_paths[0])
            atomic_write_json(
                layout.responses / command_paths[0].name,
                {
                    "protocol_version": "1.0",
                    "command_id": command["command_id"],
                    "status": "success",
                    "started_at": command["created_at"],
                    "finished_at": command["created_at"],
                    "result": {"message": "pong"},
                    "error": None,
                    "warnings": [],
                },
            )
            return
        time.sleep(0.01)
    raise AssertionError("Test command did not appear.")


def test_client_submits_valid_command_and_reads_response(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    layout = FilesystemLayout(tmp_path)
    layout.ensure_directories()
    worker = threading.Thread(target=_respond_to_first_command, args=(layout,))
    worker.start()
    client = FilesystemCommandClient(tmp_path, poll_interval_seconds=0.01)
    original_reader = FilesystemCommandClient._read_response
    response_attempts = 0

    def transiently_locked_reader(command_id: str, path: Path) -> Any:
        nonlocal response_attempts
        response_attempts += 1
        if response_attempts == 1:
            raise PermissionError("simulated transient Windows file lock")
        return original_reader(command_id, path)

    monkeypatch.setattr(
        FilesystemCommandClient,
        "_read_response",
        staticmethod(transiently_locked_reader),
    )

    result: Any = client.request(
        provider="resolve",
        action="ping",
        timeout_seconds=2,
    )
    worker.join(timeout=2)

    assert not worker.is_alive()
    assert response_attempts >= 2
    assert result == {"message": "pong"}
    command = read_json_object(next(layout.commands.glob("*.json")))
    assert command["action"] == "ping"
    assert command["safety"]["allow_destructive"] is False


def test_client_timeout_is_structured_and_leaves_auditable_command(
    tmp_path: Path,
) -> None:
    client = FilesystemCommandClient(tmp_path, poll_interval_seconds=0.005)

    with pytest.raises(CommandTimeoutError) as error_info:
        client.request(
            provider="resolve",
            action="ping",
            timeout_seconds=0.03,
        )

    assert error_info.value.command_id
    assert list((tmp_path / "commands").glob("*.json"))


def test_client_serializes_explicit_destructive_safety_flag(
    tmp_path: Path,
) -> None:
    client = FilesystemCommandClient(tmp_path, poll_interval_seconds=0.005)

    with pytest.raises(CommandTimeoutError):
        client.request(
            provider="resolve",
            action="delete_clip",
            arguments={
                "timeline_id": "timeline-1",
                "timeline_item_id": "item-1",
                "confirm_delete": True,
            },
            timeout_seconds=0.03,
            create_backup=True,
            allow_destructive=True,
        )

    layout = FilesystemLayout(tmp_path)
    command = read_json_object(next(layout.commands.glob("*.json")))
    assert command["safety"] == {
        "allow_destructive": True,
        "create_backup": True,
    }
