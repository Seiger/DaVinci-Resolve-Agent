"""Filesystem transport tests."""

from pathlib import Path

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
