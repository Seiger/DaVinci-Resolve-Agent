"""Failure boundaries and replay guarantees of Lua editing requests."""

from __future__ import annotations

import json
import re
import threading
import time
import zipfile
from pathlib import Path
from typing import Any

import pytest

from agent.client import BridgeProtocolError, CommandTimeoutError
from providers.resolve.lua_editing import WriteReceipt, validate_edit
from providers.resolve.lua_transport import LuaSnapshotClient, prepare


def exported(path: Path, project: str = "test-project") -> None:
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr(
            "project.xml",
            f'<SM_Project DbId="{project}">'
            "<ProjectName>Test</ProjectName></SM_Project>",
        )


def serve(root: Path, status: str = "ok", backup: bool = True) -> threading.Thread:
    def run() -> None:
        for _ in range(300):
            raw = (root / "request.lua").read_text()
            found = re.search(r',id="((?:\\[0-9]{3})+)"', raw)
            if found:
                identity = bytes(
                    int(n) for n in re.findall(r"\\(\d{3})", found[1])
                ).decode()
                if backup:
                    exported(root / f"{identity}.before.drp")
                exported(root / f"{identity}.{status}.drp")
                return
            time.sleep(0.01)

    worker = threading.Thread(target=run)
    worker.start()
    return worker


def test_completed_write_replays_after_client_restart_without_new_export(
    tmp_path: Path,
) -> None:
    root = tmp_path / "session"
    prepare(root)
    worker = serve(root)
    kwargs: dict[str, Any] = dict(
        arguments={"name": "Test"},
        expected_project_id="test-project",
        confirm=True,
        idempotency_key="timeline-1",
    )
    try:
        first = LuaSnapshotClient(root).request("create_timeline", 3, **kwargs)
    finally:
        worker.join(4)
    before = set(root.glob("*.drp"))
    replay = LuaSnapshotClient(root).request("create_timeline", 3, **kwargs)
    assert replay["replayed"] and replay["backup_path"] == first["backup_path"]
    assert set(root.glob("*.drp")) == before
    with pytest.raises(ValueError, match="different arguments"):
        LuaSnapshotClient(root).request(
            "create_timeline", 3, **dict(kwargs, arguments={"name": "Other"})
        )


def test_timeout_blocks_retry_and_new_write_even_after_restart(tmp_path: Path) -> None:
    root = tmp_path / "session"
    prepare(root)
    client = LuaSnapshotClient(root)
    kwargs: dict[str, Any] = dict(
        arguments={"name": "Test"}, expected_project_id="test-project", confirm=True
    )
    with pytest.raises(CommandTimeoutError):
        client.request("create_timeline", 0.01, idempotency_key="first", **kwargs)
    for key in ("first", "second"):
        with pytest.raises(RuntimeError):
            LuaSnapshotClient(root).request(
                "create_timeline", 0.01, idempotency_key=key, **kwargs
            )
    assert (root / "request.lua").read_text() == "return nil\n"


@pytest.mark.parametrize(
    "status,expected",
    [("error_PROJECT_CHANGED", "rejected"), ("error_VERIFY_FAILED", "pending")],
)
def test_preflight_rejection_differs_from_possible_partial_write(
    tmp_path: Path, status: str, expected: str
) -> None:
    root = tmp_path / "session"
    prepare(root)
    worker = serve(root, status, backup=False)
    try:
        with pytest.raises(BridgeProtocolError):
            LuaSnapshotClient(root).request(
                "create_timeline",
                3,
                arguments={"name": "Test"},
                expected_project_id="test-project",
                confirm=True,
                idempotency_key="test",
            )
    finally:
        worker.join(4)
    receipt = json.loads(next((root / "receipts").glob("*.json")).read_text())
    assert receipt["status"] == expected


def test_success_without_backup_is_not_completed(tmp_path: Path) -> None:
    root = tmp_path / "session"
    prepare(root)
    worker = serve(root, backup=False)
    try:
        with pytest.raises(OSError):
            LuaSnapshotClient(root).request(
                "create_timeline",
                3,
                arguments={"name": "Test"},
                expected_project_id="test-project",
                confirm=True,
                idempotency_key="test",
            )
    finally:
        worker.join(4)
    assert (
        json.loads(next((root / "receipts").glob("*.json")).read_text())["status"]
        == "pending"
    )


@pytest.mark.parametrize("confirmation", [False, 1, "yes"])
def test_write_confirmation_required_before_queueing(
    tmp_path: Path, confirmation: Any
) -> None:
    root = tmp_path / "session"
    prepare(root)
    with pytest.raises(ValueError):
        LuaSnapshotClient(root).request(
            "create_timeline",
            arguments={"name": "Test"},
            expected_project_id="test-project",
            confirm=confirmation,
            idempotency_key="test",
        )
    assert (root / "request.lua").read_text() == "return nil\n"


def test_media_roots_and_duplicate_paths_are_enforced(tmp_path: Path) -> None:
    allowed = tmp_path / "media"
    allowed.mkdir()
    inside = allowed / "clip.mp4"
    inside.write_bytes(b"fixture")
    outside = tmp_path / "private.mp4"
    outside.write_bytes(b"fixture")
    assert validate_edit("import_media", {"paths": [str(inside)]}, [allowed])[
        "paths"
    ] == [inside.as_posix()]
    for paths in ([str(outside)], [str(inside), str(inside)]):
        with pytest.raises(ValueError):
            validate_edit("import_media", {"paths": paths}, [allowed])


@pytest.mark.parametrize("start,end", [(1, None), (-1, 2), (2, 1), (True, 2), (0, 2.5)])
def test_bad_trim_range_rejected(tmp_path: Path, start: object, end: object) -> None:
    with pytest.raises(ValueError):
        validate_edit(
            "append_clip",
            {
                "timeline_name": "T",
                "media_path": "unused",
                "start_frame": start,
                "end_frame": end,
            },
            [tmp_path],
        )


def test_receipt_fingerprint_binds_project(tmp_path: Path) -> None:
    receipt = WriteReceipt(
        tmp_path, "key", "create_timeline", "project-one", {"name": "T"}
    )
    receipt.begin("request")
    receipt.complete({"status": "completed"})
    with pytest.raises(ValueError):
        WriteReceipt(
            tmp_path, "key", "create_timeline", "project-two", {"name": "T"}
        ).replay()
