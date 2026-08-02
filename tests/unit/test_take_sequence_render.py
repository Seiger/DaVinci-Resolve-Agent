from __future__ import annotations

import hashlib
import json
from copy import deepcopy
from pathlib import Path
from typing import Any

import pytest

from agent.take_sequence_render import (
    TakeSequenceRenderError,
    TakeSequenceRenderWorkflow,
)

REPORT_ID = "a" * 64
REVIEW_ID = "b" * 64


class StubQc:
    def __init__(self, decision: str = "approve") -> None:
        self.report = _report()
        self.review = _review(self.report, decision)
        self.calls: list[tuple[str, str, float]] = []

    def get(
        self,
        report_id: str,
        *,
        timeout_seconds: float = 30,
    ) -> dict[str, Any]:
        self.calls.append(("get", report_id, timeout_seconds))
        return deepcopy(self.report)

    def get_review(
        self,
        report_id: str,
        *,
        timeout_seconds: float = 30,
    ) -> dict[str, Any]:
        self.calls.append(("get_review", report_id, timeout_seconds))
        return deepcopy(self.review)


class StubGateway:
    def __init__(self, output_root: Path) -> None:
        self.output_root = output_root
        self.prepare_calls = 0
        self.status_calls = 0
        self.start_calls = 0
        self.fail_start_once = False
        self.rendering = False
        self.completed = False
        self.timeline_name = "Accepted Sequence"
        self.custom_name = ""
        self.profile = ""

    def prepare_render_job(
        self,
        custom_name: str,
        *,
        timeline_id: str,
        profile: str,
        timeout_seconds: float,
        idempotency_key: str,
    ) -> dict[str, Any]:
        self.prepare_calls += 1
        self.custom_name = custom_name
        self.profile = profile
        width, height, preset = (
            (3840, 2160, "YouTube - 2160p")
            if profile == "youtube-2160p-h264-v1"
            else (1920, 1080, "YouTube - 1080p")
        )
        return {
            "job_id": "job-sequence",
            "timeline_id": timeline_id,
            "timeline_name": self.timeline_name,
            "preset": profile,
            "resolve_preset": preset,
            "format": "MP4",
            "codec": "H264",
            "width": width,
            "height": height,
            "target_directory": str(self.output_root),
            "custom_name": custom_name,
            "started": False,
        }

    def render_job_status(
        self,
        job_id: str,
        *,
        timeout_seconds: float,
    ) -> dict[str, Any]:
        self.status_calls += 1
        width, height, preset = (
            (3840, 2160, "YouTube - 2160p")
            if self.profile == "youtube-2160p-h264-v1"
            else (1920, 1080, "YouTube - 1080p")
        )
        return {
            "job_id": job_id,
            "rendering_in_progress": self.rendering,
            "status": {
                "JobStatus": "Complete" if self.completed else "Ready",
                "CompletionPercentage": 100 if self.completed else 0,
            },
            "job": {
                "JobId": job_id,
                "TimelineName": self.timeline_name,
                "TargetDir": str(self.output_root),
                "OutputFilename": f"{self.custom_name}.mp4",
                "PresetName": preset,
                "FormatWidth": width,
                "FormatHeight": height,
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
        self.start_calls += 1
        if self.fail_start_once:
            self.fail_start_once = False
            raise TimeoutError("simulated lost start response")
        self.rendering = True
        return {"job_id": job_id, "started": True}


def _report() -> dict[str, Any]:
    return {
        "qc_version": "1.0",
        "report_id": REPORT_ID,
        "timeline_apply_receipt_id": "c" * 64,
        "timeline_apply_sha256": "d" * 64,
        "status": "ready_for_review",
        "target_timeline": {
            "timeline_id": "timeline-sequence",
            "name": "Accepted Sequence",
        },
        "checks": [
            {"check": "application_applied", "status": "pass", "evidence": 1},
            {
                "check": "source_timeline_unchanged",
                "status": "pass",
                "evidence": 1,
            },
            {"check": "video_sequence_exact", "status": "pass", "evidence": 2},
            {"check": "audio_sequence_exact", "status": "pass", "evidence": 2},
            {
                "check": "video_sequence_contiguous",
                "status": "pass",
                "evidence": 0,
            },
        ],
        "summary": {
            "placement_count": 2,
            "video_item_count": 2,
            "audio_item_count": 2,
            "gap_count": 0,
        },
        "unverified_areas": [
            "dialogue_audio_processing",
            "subtitle_content_and_alignment",
            "color_treatment",
            "visual_and_editorial_quality",
        ],
        "manual_review_required": True,
        "timeline_modified": False,
        "paths_redacted": True,
    }


def _review(report: dict[str, Any], decision: str) -> dict[str, Any]:
    return {
        "review_version": "1.0",
        "review_id": REVIEW_ID,
        "report_id": REPORT_ID,
        "report_sha256": _hash(report),
        "decision": decision,
        "note": "Reviewed in Resolve.",
        "timeline_modified": False,
    }


def _hash(value: object) -> str:
    payload = json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    return hashlib.sha256(payload.encode()).hexdigest()


def _workflow(
    tmp_path: Path,
    *,
    decision: str = "approve",
    capabilities: dict[str, Any] | None = None,
) -> tuple[TakeSequenceRenderWorkflow, StubQc, StubGateway]:
    output_root = tmp_path / "renders"
    output_root.mkdir(parents=True)
    qc = StubQc(decision)
    gateway = StubGateway(output_root)
    workflow = TakeSequenceRenderWorkflow(
        qc=qc,
        gateway=gateway,
        capabilities=lambda: (
            capabilities
            or {
                "render.configure": True,
                "render.discovery": True,
                "render.start": True,
            }
        ),
        receipts_root=tmp_path / "receipts",
        output_root=output_root,
    )
    return workflow, qc, gateway


def test_preview_accepts_only_approved_qc_and_supports_4k(tmp_path: Path) -> None:
    workflow, qc, _ = _workflow(tmp_path)

    preview = workflow.preview(
        qc_report_id=REPORT_ID,
        custom_name="Final tutorial",
        profile="youtube-2160p-h264-v1",
        timeout_seconds=12,
    )

    assert preview["apply_supported"] is True
    assert preview["render"]["width"] == 3840
    assert preview["render"]["height"] == 2160
    assert preview["render"]["custom_name"].endswith(f"-{REVIEW_ID[:12]}")
    assert preview["paths_redacted"] is True
    assert qc.calls == [("get", REPORT_ID, 12.0), ("get_review", REPORT_ID, 12.0)]


def test_start_replays_and_status_verifies_completed_output(tmp_path: Path) -> None:
    workflow, _, gateway = _workflow(tmp_path)
    preview = workflow.preview(
        qc_report_id=REPORT_ID,
        custom_name="Final tutorial",
        profile="youtube-1080p-h264-v1",
    )

    first = workflow.start(
        qc_report_id=REPORT_ID,
        custom_name="Final tutorial",
        profile="youtube-1080p-h264-v1",
        expected_plan_id=preview["plan_id"],
        confirm_render=True,
    )
    replay = workflow.start(
        qc_report_id=REPORT_ID,
        custom_name="Final tutorial",
        profile="youtube-1080p-h264-v1",
        expected_plan_id=preview["plan_id"],
        confirm_render=True,
    )

    assert first == replay
    assert first["status"] == "started"
    assert first["paths_redacted"] is True
    assert gateway.prepare_calls == 1
    assert gateway.start_calls == 1

    gateway.rendering = False
    gateway.completed = True
    output = gateway.output_root / f"{gateway.custom_name}.mp4"
    output.write_bytes(b"rendered video")
    status = workflow.status(first["receipt_id"])

    assert status["status"] == "complete"
    assert status["output"]["validation"]["passed"] is True
    assert status["output"]["output"]["path"] == str(output.resolve())
    completed_replay = workflow.start(
        qc_report_id=REPORT_ID,
        custom_name="Final tutorial",
        profile="youtube-1080p-h264-v1",
        expected_plan_id=preview["plan_id"],
        confirm_render=True,
    )
    assert completed_replay == first
    assert gateway.prepare_calls == 1
    assert gateway.start_calls == 1


def test_preview_rejects_non_approved_qc(tmp_path: Path) -> None:
    workflow, _, _ = _workflow(tmp_path, decision="reject")

    with pytest.raises(TakeSequenceRenderError, match="approve decision"):
        workflow.preview(
            qc_report_id=REPORT_ID,
            custom_name="Final",
            profile="youtube-1080p-h264-v1",
        )


def test_preview_reports_missing_capability_and_existing_output(tmp_path: Path) -> None:
    workflow, _, _ = _workflow(
        tmp_path,
        capabilities={
            "render.configure": True,
            "render.discovery": True,
            "render.start": False,
        },
    )
    preview = workflow.preview(
        qc_report_id=REPORT_ID,
        custom_name="Final",
        profile="youtube-1080p-h264-v1",
    )
    assert preview["apply_supported"] is False
    assert preview["unsupported_capabilities"] == ["render.start"]

    output = tmp_path / "renders" / preview["render"]["output_filename"]
    output.write_bytes(b"existing")
    repeated = workflow.preview(
        qc_report_id=REPORT_ID,
        custom_name="Final",
        profile="youtube-1080p-h264-v1",
    )
    assert repeated["blockers"] == ["managed_output_already_exists"]


def test_start_requires_exact_plan_and_confirmation(tmp_path: Path) -> None:
    workflow, _, _ = _workflow(tmp_path)
    preview = workflow.preview(
        qc_report_id=REPORT_ID,
        custom_name="Final",
        profile="youtube-1080p-h264-v1",
    )
    with pytest.raises(TakeSequenceRenderError, match="confirm_render"):
        workflow.start(
            qc_report_id=REPORT_ID,
            custom_name="Final",
            profile="youtube-1080p-h264-v1",
            expected_plan_id=preview["plan_id"],
            confirm_render=False,
        )
    with pytest.raises(TakeSequenceRenderError, match="expected_plan_id"):
        workflow.start(
            qc_report_id=REPORT_ID,
            custom_name="Final",
            profile="youtube-1080p-h264-v1",
            expected_plan_id="f" * 64,
            confirm_render=True,
        )


def test_start_rejects_live_job_identity_drift(tmp_path: Path) -> None:
    workflow, _, gateway = _workflow(tmp_path)
    preview = workflow.preview(
        qc_report_id=REPORT_ID,
        custom_name="Final",
        profile="youtube-1080p-h264-v1",
    )
    gateway.timeline_name = "Wrong timeline"

    with pytest.raises(TakeSequenceRenderError, match="accepted sequence policy"):
        workflow.start(
            qc_report_id=REPORT_ID,
            custom_name="Final",
            profile="youtube-1080p-h264-v1",
            expected_plan_id=preview["plan_id"],
            confirm_render=True,
        )


def test_start_recovers_after_ready_preflight_without_repeating_it(
    tmp_path: Path,
) -> None:
    workflow, _, gateway = _workflow(tmp_path)
    preview = workflow.preview(
        qc_report_id=REPORT_ID,
        custom_name="Final",
        profile="youtube-1080p-h264-v1",
    )
    gateway.fail_start_once = True

    with pytest.raises(TimeoutError, match="lost start response"):
        workflow.start(
            qc_report_id=REPORT_ID,
            custom_name="Final",
            profile="youtube-1080p-h264-v1",
            expected_plan_id=preview["plan_id"],
            confirm_render=True,
        )
    assert gateway.status_calls == 1

    recovered = workflow.start(
        qc_report_id=REPORT_ID,
        custom_name="Final",
        profile="youtube-1080p-h264-v1",
        expected_plan_id=preview["plan_id"],
        confirm_render=True,
    )

    assert recovered["status"] == "started"
    assert gateway.prepare_calls == 1
    assert gateway.status_calls == 1
    assert gateway.start_calls == 2
