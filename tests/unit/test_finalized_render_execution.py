"""M45 finalized render start and status tests."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from agent.finalized_render_execution import (
    FinalizedRenderExecutionError,
    FinalizedRenderExecutor,
)

PREPARATION_ID = "a" * 64


class StubGateway:
    def __init__(self, output_directory: Path) -> None:
        self.output_directory = output_directory
        self.starts = 0
        self.rendering = False
        self.completed = False

    def render_job_status(
        self,
        job_id: str,
        *,
        timeout_seconds: float,
    ) -> dict[str, Any]:
        return {
            "job_id": job_id,
            "rendering_in_progress": self.rendering,
            "status": {
                "JobStatus": "Complete" if self.completed else "Ready",
                "CompletionPercentage": 100 if self.completed else 0,
            },
            "job": {
                "JobId": job_id,
                "TimelineName": "M42 Final",
                "TargetDir": str(self.output_directory),
                "OutputFilename": "M44 Final.mp4",
                "PresetName": "YouTube - 1080p",
                "FormatWidth": 1920,
                "FormatHeight": 1080,
                "VideoFormat": "MP4",
                "VideoCodec": "H.264",
            },
        }

    def start_render_job(
        self,
        job_id: str,
        *,
        timeout_seconds: float,
        idempotency_key: str,
    ) -> dict[str, Any]:
        self.starts += 1
        self.rendering = True
        return {"job_id": job_id, "started": True}


def _write_preparation(root: Path, output_directory: Path) -> None:
    root.mkdir(parents=True)
    receipt = {
        "render_preparation_version": "1.0",
        "receipt_id": PREPARATION_ID,
        "status": "applied",
        "inputs": {
            "finalization_receipt_id": "b" * 64,
            "custom_name": "M44 Final",
            "profile": "youtube-1080p-h264-v1",
        },
        "target": {
            "timeline_id": "timeline-final",
            "timeline_name": "M42 Final",
        },
        "operation": {
            "operation": "prepare_render_job",
            "status": "applied",
            "result": {
                "job_id": "job-final",
                "timeline_id": "timeline-final",
                "timeline_name": "M42 Final",
                "preset": "youtube-1080p-h264-v1",
                "resolve_preset": "YouTube - 1080p",
                "format": "MP4",
                "codec": "H264",
                "width": 1920,
                "height": 1080,
                "target_directory": str(output_directory),
                "custom_name": "M44 Final",
                "started": False,
            },
        },
    }
    (root / f"{PREPARATION_ID}.json").write_text(
        json.dumps(receipt), encoding="utf-8"
    )


def _executor(
    tmp_path: Path,
    gateway: StubGateway,
    *,
    capabilities: dict[str, Any] | None = None,
) -> FinalizedRenderExecutor:
    preparations = tmp_path / "preparations"
    _write_preparation(preparations, gateway.output_directory)
    return FinalizedRenderExecutor(
        gateway=gateway,
        capabilities=lambda: capabilities
        or {"render.discovery": True, "render.start": True},
        preparations_root=preparations,
        receipts_root=tmp_path / "executions",
        expected_output_directory=gateway.output_directory,
    )


def test_starts_once_and_reports_completed_output(tmp_path: Path) -> None:
    output_directory = tmp_path / "renders"
    output_directory.mkdir()
    gateway = StubGateway(output_directory)
    executor = _executor(tmp_path, gateway)

    first = executor.start(
        preparation_receipt_id=PREPARATION_ID,
        confirm_render=True,
    )
    replay = executor.start(
        preparation_receipt_id=PREPARATION_ID,
        confirm_render=True,
    )

    assert first == replay
    assert first["status"] == "started"
    assert gateway.starts == 1

    gateway.rendering = False
    gateway.completed = True
    (output_directory / "M44 Final.mp4").write_bytes(b"video")
    status = executor.status(first["receipt_id"])

    assert status["live"]["status"]["JobStatus"] == "Complete"
    assert status["output"]["validation"]["passed"] is True


def test_requires_confirmation_capabilities_and_absent_output(
    tmp_path: Path,
) -> None:
    output_directory = tmp_path / "renders"
    output_directory.mkdir()
    gateway = StubGateway(output_directory)
    executor = _executor(tmp_path / "confirmation", gateway)

    with pytest.raises(FinalizedRenderExecutionError, match="confirm_render"):
        executor.start(
            preparation_receipt_id=PREPARATION_ID,
            confirm_render=False,
        )

    blocked = _executor(
        tmp_path / "capability",
        gateway,
        capabilities={"render.discovery": True, "render.start": False},
    )
    with pytest.raises(FinalizedRenderExecutionError, match="render.start"):
        blocked.start(
            preparation_receipt_id=PREPARATION_ID,
            confirm_render=True,
        )

    (output_directory / "M44 Final.mp4").write_bytes(b"existing")
    existing = _executor(tmp_path / "existing", gateway)
    with pytest.raises(FinalizedRenderExecutionError, match="already exists"):
        existing.start(
            preparation_receipt_id=PREPARATION_ID,
            confirm_render=True,
        )


def test_rejects_live_job_identity_drift(tmp_path: Path) -> None:
    output_directory = tmp_path / "renders"
    output_directory.mkdir()
    gateway = StubGateway(output_directory)
    executor = _executor(tmp_path, gateway)
    original = gateway.render_job_status

    def drifted(job_id: str, *, timeout_seconds: float) -> dict[str, Any]:
        result = original(job_id, timeout_seconds=timeout_seconds)
        result["job"]["TimelineName"] = "Wrong Timeline"
        return result

    gateway.render_job_status = drifted  # type: ignore[method-assign]
    with pytest.raises(FinalizedRenderExecutionError, match="no longer matches"):
        executor.start(
            preparation_receipt_id=PREPARATION_ID,
            confirm_render=True,
        )
