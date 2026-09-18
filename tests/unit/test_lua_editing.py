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
            try:
                raw = (root / "request.lua").read_text()
            except OSError:
                time.sleep(0.01)
                continue
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


def test_transient_windows_publication_lock_reuses_one_command(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root = tmp_path / "session"
    prepare(root)
    original = Path.replace
    attempts: list[str] = []

    def locked_replace(path: Path, target: Any) -> Path:
        if Path(target) == root / "request.lua":
            attempts.append(path.name)
            if len(attempts) <= 2:
                raise PermissionError("Windows reader holds delete sharing")
        return original(path, target)

    monkeypatch.setattr(Path, "replace", locked_replace)
    worker = serve(root)
    try:
        result = LuaSnapshotClient(root).request(
            "create_timeline",
            3,
            arguments={"name": "Test"},
            expected_project_id="test-project",
            confirm=True,
            idempotency_key="publication",
        )
    finally:
        worker.join(4)
    assert result["status"] == "completed"
    assert len(attempts) >= 3 and len(set(attempts)) == 1
    assert len(list((root / "receipts").glob("*.json"))) == 1


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


def test_sync_group_validation_and_receipt_replay(tmp_path: Path) -> None:
    screen, camera = tmp_path / "screen.mkv", tmp_path / "camera.mkv"
    screen.touch()
    camera.touch()
    group = {
        "screen_path": str(screen),
        "camera_path": str(camera),
        "screen_start_frame": 3600,
        "camera_start_frame": 3588,
        "frame_count": 1200,
    }
    args = {"timeline_name": "Sync", "sync_groups": [group]}
    full = {
        "screen_path": str(screen),
        "camera_path": str(camera),
        "camera_delay_frames": 11,
    }
    assert (
        validate_edit("append_clip", dict(args, sync_groups=[full]), [tmp_path])[
            "sync_groups"
        ][0]["camera_delay_frames"]
        == 11
    )
    for delay in (True, -1, 601, 0.5):
        with pytest.raises(ValueError):
            validate_edit(
                "append_clip",
                dict(args, sync_groups=[dict(full, camera_delay_frames=delay)]),
                [tmp_path],
            )

    result = validate_edit("append_clip", args, [tmp_path])
    assert result["sync_groups"][0]["camera_start_frame"] == 3588
    for change in (
        {"frame_count": 0},
        {"frame_count": True},
        {"camera_start_frame": -1},
        {"screen_start_frame": 1.5},
        {"camera_path": str(screen)},
        {"extra": "code"},
    ):
        with pytest.raises(ValueError):
            validate_edit(
                "append_clip",
                dict(args, sync_groups=[dict(group, **change)]),
                [tmp_path],
            )
    with pytest.raises(ValueError):
        validate_edit("append_clip", dict(args, sync_groups=[group] * 26), [tmp_path])
    root = tmp_path / "session"
    prepare(root, [tmp_path])
    worker = serve(root)
    kw: dict[str, Any] = dict(
        arguments=args,
        expected_project_id="test-project",
        confirm=True,
        idempotency_key="sync-batch",
    )
    try:
        first = LuaSnapshotClient(root).request("append_clip", 3, **kw)
    finally:
        worker.join(4)
    replay = LuaSnapshotClient(root).request("append_clip", 1, **kw)
    assert replay["replayed"] and first["arguments"] == replay["arguments"]
    assert len(list(root.glob("*.before.drp"))) == 1


def test_creation_rejects_inline_rate_change() -> None:
    assert validate_edit("create_timeline", {"name": "Sync"}, []) == {"name": "Sync"}
    for fps in (60, True, 59.94, 0, "60"):
        with pytest.raises(ValueError):
            validate_edit("create_timeline", {"name": "Sync", "frame_rate": fps}, [])


@pytest.mark.parametrize(
    "change",
    [
        {"source_timeline_name": "Copy"},
        {"source_timeline_name": ""},
        {"source_timeline_name": " Source"},
        {"source_timeline_name": "Source\n"},
        {"source_timeline_name": "x" * 129},
        {"source_timeline_name": True},
        {"clear_source": True},
        {"frame_rate": 60},
    ],
)
def test_duplicate_rejects_unsafe_or_unexpected_arguments(
    change: dict[str, Any],
) -> None:
    with pytest.raises(ValueError):
        validate_edit(
            "duplicate_timeline",
            dict({"name": "Copy", "source_timeline_name": "Source"}, **change),
            [],
        )


def test_duplicate_receipt_binds_source_and_replays_without_second_copy(
    tmp_path: Path,
) -> None:
    root = tmp_path / "session"
    prepare(root)
    args = {"name": "Copy", "source_timeline_name": "Source"}
    assert validate_edit("duplicate_timeline", args, []) == args
    with pytest.raises(ValueError):
        validate_edit("create_timeline", args, [])
    kwargs: dict[str, Any] = dict(
        arguments=args,
        expected_project_id="test-project",
        confirm=True,
        idempotency_key="copy-timeline",
    )
    worker = serve(root)
    try:
        result = LuaSnapshotClient(root).request("duplicate_timeline", 3, **kwargs)
    finally:
        worker.join(4)
    replay = LuaSnapshotClient(root).request("duplicate_timeline", 1, **kwargs)
    assert replay["replayed"] and replay["backup_path"] == result["backup_path"]
    assert len(list(root.glob("*.before.drp"))) == 1
    with pytest.raises(ValueError, match="different arguments"):
        LuaSnapshotClient(root).request(
            "duplicate_timeline",
            1,
            **dict(kwargs, arguments=dict(args, source_timeline_name="Different")),
        )


def test_quit_acceptance_replays_without_claiming_exit(tmp_path: Path) -> None:
    root = tmp_path / "session"
    prepare(root)
    worker = serve(root, "accepted")
    kwargs: dict[str, Any] = dict(
        expected_project_id="test-project",
        confirm=True,
        idempotency_key="quit-on-request",
    )
    try:
        result = LuaSnapshotClient(root).request("quit_resolve", 3, **kwargs)
    finally:
        worker.join(4)
    assert result["status"] == "accepted"
    assert result["completion_verified"] is False
    assert LuaSnapshotClient(root).request("quit_resolve", 3, **kwargs)["replayed"]


def test_quit_rejects_old_session_and_missing_confirmation(tmp_path: Path) -> None:
    root = tmp_path / "session"
    prepare(root)
    with pytest.raises(ValueError, match="confirmation"):
        LuaSnapshotClient(root).request(
            "quit_resolve", expected_project_id="test-project"
        )
    metadata = json.loads((root / "session.json").read_text())
    metadata.pop("capabilities")
    (root / "session.json").write_text(json.dumps(metadata))
    with pytest.raises(ValueError, match="freshly prepared"):
        LuaSnapshotClient(root).request("quit_resolve")
    assert (root / "request.lua").read_text().strip() == "return nil"
