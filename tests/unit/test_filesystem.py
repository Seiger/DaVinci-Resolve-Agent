"""Filesystem transport tests."""

from pathlib import Path

import pytest

import transports.filesystem
from transports.filesystem import (
    FilesystemLayout,
    atomic_write_json,
    read_json_object,
)


def test_filesystem_layout_and_atomic_json_write(tmp_path: Path) -> None:
    layout = FilesystemLayout(tmp_path)
    layout.ensure_directories()

    assert all(directory.is_dir() for directory in layout.directories())
    assert layout.diagnostics == tmp_path / "diagnostics"

    response_path = layout.responses / "command-1.json"
    atomic_write_json(response_path, {"status": "success"})

    assert read_json_object(response_path) == {"status": "success"}
    assert not response_path.with_name("command-1.json.tmp").exists()


def test_atomic_json_retries_transient_permission_error(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    output_path = tmp_path / "audit.json"
    original_writer = transports.filesystem.atomic_write_json
    attempts = 0

    def flaky_writer(path: Path, payload: dict[str, object]) -> None:
        nonlocal attempts
        attempts += 1
        if attempts == 1:
            raise PermissionError("simulated Windows file lock")
        original_writer(path, payload)

    monkeypatch.setattr(
        transports.filesystem,
        "atomic_write_json",
        flaky_writer,
    )

    transports.filesystem.atomic_write_json_with_retry(
        output_path,
        {"status": "success"},
        retry_delay_seconds=0,
    )

    assert attempts == 2
    assert read_json_object(output_path) == {"status": "success"}
