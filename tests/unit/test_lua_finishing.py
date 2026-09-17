"""Boundaries for finishing, owned render jobs and explicit session cleanup."""

from __future__ import annotations

import json
import re
import threading
import time
import zipfile
from pathlib import Path
from typing import Any

import pytest

from agent.client import BridgeProtocolError
from providers.resolve.lua_cleanup import cleanup_responses
from providers.resolve.lua_finishing import validate_finishing, verify_video
from providers.resolve.lua_transport import LuaSnapshotClient, prepare


def serve(root: Path, status: str, backup: bool = True) -> threading.Thread:
    def run() -> None:
        for _ in range(300):
            match = re.search(
                r',id="((?:\\[0-9]{3})+)"', (root / "request.lua").read_text()
            )
            if match:
                identity = bytes(
                    int(n) for n in re.findall(r"\\(\d{3})", match[1])
                ).decode()
                for suffix in ["before", status] if backup else [status]:
                    with zipfile.ZipFile(
                        root / f"{identity}.{suffix}.drp", "w"
                    ) as archive:
                        archive.writestr(
                            "project.xml",
                            '<SM_Project DbId="test-project">'
                            '<ProjectName>Test</ProjectName></SM_Project>',
                        )
                return
            time.sleep(0.01)

    worker = threading.Thread(target=run)
    worker.start()
    return worker


@pytest.mark.parametrize(
    "props",
    [
        {"AudioVolume": True},
        {"AudioVolume": float("nan")},
        {"AudioVolume": 13},
        {"ZoomX": 2},
        {"AudioVolume": "0"},
        {},
    ],
)
def test_audio_rejects_unsafe_properties(tmp_path: Path, props: dict[str, Any]) -> None:
    media = tmp_path / "audio.wav"
    media.touch()
    with pytest.raises(ValueError):
        validate_finishing(
            "set_clip_properties",
            {
                "timeline_name": "Test",
                "track_type": "audio",
                "track_index": 1,
                "item_index": 1,
                "expected_media_path": str(media),
                "properties": props,
            },
            [tmp_path],
        )


@pytest.mark.parametrize(
    "text",
    [
        "1\n00:00:02,000 --> 00:00:01,000\nBad",
        "1\n00:99:00,000 --> 01:00:00,000\nBad",
        "1\n00:00:00,000 --> 00:00:02,000\nOne\n\n"
        "2\n00:00:01,000 --> 00:00:03,000\nTwo",
        "",
        "not an srt",
    ],
)
def test_malformed_subtitles_rejected(tmp_path: Path, text: str) -> None:
    srt = tmp_path / "captions.srt"
    srt.write_text(text, encoding="utf-8")
    with pytest.raises(ValueError):
        validate_finishing(
            "add_subtitles",
            {"timeline_name": "Test", "subtitle_path": str(srt)},
            [tmp_path],
        )


def test_subtitle_timing_and_media_boundary(tmp_path: Path) -> None:
    srt = tmp_path / "captions.srt"
    srt.write_text("1\n00:00:00,500 --> 00:00:02,500\nCaption\n", encoding="utf-8")
    args = {"timeline_name": "Test", "subtitle_path": str(srt)}
    validated = validate_finishing("add_subtitles", args, [tmp_path])
    assert (
        validated["cue_count"],
        validated["first_start"],
        validated["last_end"],
    ) == (1, 0.5, 2.5)
    with pytest.raises(ValueError):
        validate_finishing("add_subtitles", args, [tmp_path / "other"])


def prepare_job(root: Path) -> dict[str, Any]:
    worker = serve(root, "ok_job_safe-job-1")
    try:
        return LuaSnapshotClient(root).request(
            "prepare_render",
            3,
            arguments={"timeline_name": "Test"},
            expected_project_id="test-project",
            idempotency_key="prepare",
            confirm=True,
        )
    finally:
        worker.join(4)


def test_render_requires_owned_job_and_replays_preparation(tmp_path: Path) -> None:
    root = tmp_path / "session"
    prepare(root)
    client = LuaSnapshotClient(root)
    with pytest.raises(ValueError, match="not owned"):
        client.request(
            "start_render",
            arguments={"job_id": "foreign"},
            expected_project_id="test-project",
            confirm=True,
            idempotency_key="start",
        )
    first = prepare_job(root)
    assert first["job_id"] == "safe-job-1"
    assert Path(first["output_path"]).parent.is_dir()
    replay = client.request(
        "prepare_render",
        arguments={"timeline_name": "Test"},
        expected_project_id="test-project",
        confirm=True,
        idempotency_key="prepare",
    )
    assert replay["replayed"] and replay["job_id"] == first["job_id"]
    with pytest.raises(ValueError, match="not owned"):
        client.request(
            "get_render_status",
            arguments={"job_id": first["job_id"]},
            expected_project_id="other-project",
        )


def test_complete_status_requires_real_output(tmp_path: Path) -> None:
    root = tmp_path / "session"
    prepare(root)
    job = prepare_job(root)
    worker = serve(root, "ok_state_complete", backup=False)
    try:
        with pytest.raises(ValueError, match="non-empty"):
            LuaSnapshotClient(root).request(
                "get_render_status",
                3,
                arguments={"job_id": job["job_id"]},
                expected_project_id="test-project",
            )
    finally:
        worker.join(4)


def test_malformed_job_ack_is_uncertain(tmp_path: Path) -> None:
    root = tmp_path / "session"
    prepare(root)
    worker = serve(root, "ok_job_bad_token")
    try:
        with pytest.raises(BridgeProtocolError, match="acknowledgement"):
            LuaSnapshotClient(root).request(
                "prepare_render",
                3,
                arguments={"timeline_name": "Test"},
                expected_project_id="test-project",
                confirm=True,
                idempotency_key="prepare",
            )
    finally:
        worker.join(4)
    assert (
        json.loads(next((root / "receipts").glob("*.json")).read_text())["status"]
        == "pending"
    )


def test_cleanup_requires_stop_and_preserves_backups_renders_receipts(
    tmp_path: Path,
) -> None:
    root = tmp_path / "session"
    prepare(root)
    with pytest.raises(FileNotFoundError):
        cleanup_responses(root, confirm=True)
    metadata = json.loads((root / "session.json").read_text())
    (root / "stopped.json").write_text(json.dumps({"session": metadata["session"]}))
    response = root / ("a" * 32 + ".ok.drp")
    backup = root / ("a" * 32 + ".before.drp")
    response.write_bytes(b"response")
    backup.write_bytes(b"backup")
    (root / "renders").mkdir()
    video = root / "renders" / "video.mp4"
    video.write_bytes(b"video")
    assert cleanup_responses(root)["status"] == "preview"
    assert response.exists()
    assert cleanup_responses(root, confirm=True)["files"] == 1
    assert not response.exists() and backup.exists() and video.exists()
    assert cleanup_responses(root, confirm=True)["files"] == 0
    with pytest.raises(ValueError, match="stopped"):
        LuaSnapshotClient(root).request("ping")
    (root / "receipts").mkdir()
    (root / "receipts" / "uncertain.json").write_text('{"status":"pending"}')
    with pytest.raises(ValueError, match="uncertain"):
        cleanup_responses(root, confirm=True)


def test_invalid_render_not_reported_as_verified(tmp_path: Path) -> None:
    path = tmp_path / "video.mp4"
    path.touch()
    with pytest.raises(ValueError, match="non-empty"):
        verify_video(path)
