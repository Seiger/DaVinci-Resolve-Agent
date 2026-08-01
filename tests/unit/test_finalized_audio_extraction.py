"""M46 finalized timeline audio extraction tests."""

from __future__ import annotations

import json
import wave
from pathlib import Path
from typing import Any

import pytest

from agent.finalized_audio_extraction import (
    FinalizedAudioExtractionError,
    FinalizedAudioExtractor,
)

FINALIZATION_ID = "a" * 64


class StubGateway:
    def __init__(self, output_directory: Path) -> None:
        self.output_directory = output_directory
        self.prepares = 0
        self.starts = 0
        self.rendering = False
        self.completed = False

    def prepare_render_job(
        self,
        custom_name: str,
        *,
        timeline_id: str,
        profile: str,
        timeout_seconds: float,
        idempotency_key: str,
    ) -> dict[str, Any]:
        self.prepares += 1
        return {
            "job_id": "job-audio",
            "timeline_id": timeline_id,
            "timeline_name": "M42 Final",
            "preset": profile,
            "resolve_preset": "Audio Only",
            "format": "wav",
            "codec": "LinearPCM",
            "audio_bit_depth": 16,
            "audio_sample_rate": 48_000,
            "export_video": False,
            "export_audio": True,
            "target_directory": str(self.output_directory),
            "custom_name": custom_name,
            "started": False,
        }

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
                "OutputFilename": "M46 Dialogue Source.wav",
                "PresetName": "Audio Only",
                "IsExportVideo": False,
                "IsExportAudio": True,
                "AudioBitDepth": 16,
                "AudioSampleRate": 48_000,
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


def _write_finalization(root: Path) -> None:
    root.mkdir(parents=True)
    receipt = {
        "finalization_version": "1.0",
        "receipt_id": FINALIZATION_ID,
        "status": "applied",
        "inputs": {
            "pause_compaction_receipt_id": "b" * 64,
            "picture_in_picture_receipt_id": "c" * 64,
            "synchronized_link_receipt_id": "d" * 64,
        },
        "target": {
            "synchronized_pair_receipt_id": "e" * 64,
            "timeline_id": "timeline-final",
            "timeline_name": "M42 Final",
        },
        "link_groups": [["video", "audio"]],
        "webcam_item_ids": ["webcam"],
        "transform": {"position_x": 1.0, "position_y": 2.0, "zoom": 0.25},
        "operations": [
            {
                "operation": "set_clip_link_groups",
                "status": "applied",
                "result": {},
            },
            {
                "operation": "set_clip_transforms",
                "status": "applied",
                "result": {},
            },
        ],
        "readback": {},
    }
    (root / f"{FINALIZATION_ID}.json").write_text(
        json.dumps(receipt), encoding="utf-8"
    )


def _extractor(
    tmp_path: Path,
    gateway: StubGateway,
    *,
    capabilities: dict[str, Any] | None = None,
) -> FinalizedAudioExtractor:
    finalizations = tmp_path / "finalizations"
    _write_finalization(finalizations)
    return FinalizedAudioExtractor(
        gateway=gateway,
        capabilities=lambda: capabilities
        or {
            "render.configure": True,
            "render.discovery": True,
            "render.start": True,
        },
        finalizations_root=finalizations,
        receipts_root=tmp_path / "receipts",
        expected_output_directory=gateway.output_directory,
    )


def _write_pcm_wav(path: Path) -> None:
    with wave.open(str(path), "wb") as output:
        output.setnchannels(2)
        output.setsampwidth(2)
        output.setframerate(48_000)
        output.writeframes(b"\x00\x00" * 2 * 480)


def test_prepares_starts_once_and_verifies_pcm_wav(tmp_path: Path) -> None:
    output_directory = tmp_path / "audio-sources"
    output_directory.mkdir()
    gateway = StubGateway(output_directory)
    extractor = _extractor(tmp_path, gateway)

    prepared = extractor.prepare(
        finalization_receipt_id=FINALIZATION_ID,
        custom_name="M46 Dialogue Source",
        confirm_prepare=True,
    )
    prepare_replay = extractor.prepare(
        finalization_receipt_id=FINALIZATION_ID,
        custom_name="M46 Dialogue Source",
        confirm_prepare=True,
    )
    started = extractor.start(prepared["receipt_id"], confirm_render=True)
    start_replay = extractor.start(prepared["receipt_id"], confirm_render=True)

    assert prepared == prepare_replay
    assert started == start_replay
    assert gateway.prepares == 1
    assert gateway.starts == 1

    gateway.rendering = False
    gateway.completed = True
    _write_pcm_wav(output_directory / "M46 Dialogue Source.wav")
    status = extractor.status(prepared["receipt_id"])

    assert status["output"]["validation"]["passed"] is True
    assert status["output"]["output"]["pcm"] == {
        "channels": 2,
        "sample_width_bits": 16,
        "sample_rate_hz": 48_000,
        "frame_count": 480,
        "compression_type": "NONE",
    }


def test_requires_confirmation_and_capabilities(tmp_path: Path) -> None:
    output_directory = tmp_path / "audio-sources"
    output_directory.mkdir()
    gateway = StubGateway(output_directory)
    extractor = _extractor(tmp_path / "confirmation", gateway)

    with pytest.raises(FinalizedAudioExtractionError, match="confirm_prepare"):
        extractor.prepare(
            finalization_receipt_id=FINALIZATION_ID,
            custom_name="M46 Dialogue Source",
            confirm_prepare=False,
        )

    blocked = _extractor(
        tmp_path / "capability",
        gateway,
        capabilities={"render.configure": False},
    )
    with pytest.raises(FinalizedAudioExtractionError, match="render.configure"):
        blocked.prepare(
            finalization_receipt_id=FINALIZATION_ID,
            custom_name="M46 Dialogue Source",
            confirm_prepare=True,
        )


def test_rejects_existing_or_non_pcm_output(tmp_path: Path) -> None:
    output_directory = tmp_path / "audio-sources"
    output_directory.mkdir()
    gateway = StubGateway(output_directory)
    extractor = _extractor(tmp_path, gateway)
    prepared = extractor.prepare(
        finalization_receipt_id=FINALIZATION_ID,
        custom_name="M46 Dialogue Source",
        confirm_prepare=True,
    )
    output_path = output_directory / "M46 Dialogue Source.wav"
    output_path.write_bytes(b"not-wave")

    with pytest.raises(FinalizedAudioExtractionError, match="already exists"):
        extractor.start(prepared["receipt_id"], confirm_render=True)

    output_path.unlink()
    extractor.start(prepared["receipt_id"], confirm_render=True)
    gateway.rendering = False
    gateway.completed = True
    output_path.write_bytes(b"not-wave")
    status = extractor.status(prepared["receipt_id"])
    assert status["output"]["validation"]["passed"] is False
