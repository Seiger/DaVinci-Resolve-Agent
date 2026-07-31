"""M6 audio workflow and canonical report tests."""

from __future__ import annotations

import math
import wave
from pathlib import Path

import pytest

from agent.audio_workflow import (
    AudioReportInspector,
    AudioWorkflowError,
    DialogueAudioWorkflow,
)
from agent.contracts import validate_contract

SAMPLE_RATE = 8_000


def _write_tone(path: Path, amplitude: int) -> None:
    frames = bytearray()
    for index in range(SAMPLE_RATE):
        sample = round(
            amplitude * math.sin(2 * math.pi * 220 * index / SAMPLE_RATE)
        )
        frames.extend(sample.to_bytes(2, "little", signed=True))
    with wave.open(str(path), "wb") as output:
        output.setnchannels(1)
        output.setsampwidth(2)
        output.setframerate(SAMPLE_RATE)
        output.writeframes(frames)


def test_workflow_returns_idempotent_before_after_report(tmp_path: Path) -> None:
    source = tmp_path / "dialogue.wav"
    _write_tone(source, 2_000)
    workflow = DialogueAudioWorkflow(
        output_root=tmp_path / "processed",
        reports_root=tmp_path / "reports",
    )

    first = workflow.process(str(source))
    second = workflow.process(str(source))

    validate_contract("audio-report", first)
    assert first == second
    assert first["source"]["preserved"] is True
    assert first["source"]["sha256"] != first["derived"]["sha256"]
    assert first["validation"]["target_met"] is True
    assert Path(first["derived"]["path"]).is_file()
    assert (
        tmp_path / "reports" / f"{first['report_id']}.json"
    ).is_file()


def test_workflow_distinguishes_equal_content_at_different_paths(
    tmp_path: Path,
) -> None:
    first_source = tmp_path / "first.wav"
    second_source = tmp_path / "second.wav"
    _write_tone(first_source, 2_000)
    second_source.write_bytes(first_source.read_bytes())
    workflow = DialogueAudioWorkflow(
        output_root=tmp_path / "processed",
        reports_root=tmp_path / "reports",
    )

    first = workflow.process(str(first_source))
    second = workflow.process(str(second_source))

    assert first["source"]["sha256"] == second["source"]["sha256"]
    assert first["report_id"] != second["report_id"]
    assert first["derived"]["path"] != second["derived"]["path"]


def test_inspector_reads_and_lists_reports_without_paths(
    tmp_path: Path,
) -> None:
    reports_root = tmp_path / "reports"
    source = tmp_path / "dialogue.wav"
    _write_tone(source, 2_000)
    report = DialogueAudioWorkflow(
        output_root=tmp_path / "processed",
        reports_root=reports_root,
    ).process(str(source))
    inspector = AudioReportInspector(reports_root)

    detail = inspector.get_report(report["report_id"])
    listing = inspector.list_reports(limit=1)

    assert detail == report
    assert listing["count"] == 1
    assert listing["truncated"] is False
    assert listing["reports"][0]["report_id"] == report["report_id"]
    assert listing["reports"][0]["target_met"] is True
    assert "source" not in listing["reports"][0]
    assert "derived" not in listing["reports"][0]


@pytest.mark.parametrize("report_id", ["", "A" * 64, "../report", "a" * 63])
def test_inspector_rejects_noncanonical_report_id(
    tmp_path: Path,
    report_id: str,
) -> None:
    inspector = AudioReportInspector(tmp_path)

    with pytest.raises(AudioWorkflowError, match="report_id"):
        inspector.get_report(report_id)


@pytest.mark.parametrize("limit", [0, 101, True])
def test_inspector_rejects_unbounded_limit(
    tmp_path: Path,
    limit: int,
) -> None:
    inspector = AudioReportInspector(tmp_path)

    with pytest.raises(AudioWorkflowError, match="limit"):
        inspector.list_reports(limit)
