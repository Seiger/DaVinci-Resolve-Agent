"""M6 provider-neutral dialogue analysis and processing workflow."""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from agent.contracts import validate_contract
from agent.paths import audio_reports_directory, processed_audio_directory
from providers.audio import PcmWavAudioProvider
from transports.filesystem import atomic_write_json, read_json_object

REPORT_VERSION = "1.0"
PRESET_NAME = "pcm-dialogue-level-v1"
TARGET_RMS_DBFS = -20.0
MAX_PEAK_DBFS = -1.0
RMS_TOLERANCE_DB = 0.5


class AudioWorkflowError(ValueError):
    """Raised when an M6 audio report cannot be produced safely."""


class DialogueAudioWorkflow:
    """Create derived dialogue audio and a deterministic before/after report."""

    def __init__(
        self,
        provider: PcmWavAudioProvider | None = None,
        output_root: Path | None = None,
        reports_root: Path | None = None,
    ) -> None:
        self._provider = PcmWavAudioProvider() if provider is None else provider
        self._output_root = (
            processed_audio_directory()
            if output_root is None
            else output_root
        )
        self._reports_root = (
            audio_reports_directory()
            if reports_root is None
            else reports_root
        )

    def process(
        self,
        source_file: str,
        *,
        preset: str = PRESET_NAME,
    ) -> dict[str, Any]:
        """Apply the fixed M6 preset without modifying the original WAV."""
        if preset != PRESET_NAME:
            raise AudioWorkflowError(
                f"Unsupported audio preset: {preset}. Expected {PRESET_NAME}."
            )
        source = Path(source_file).resolve()
        before = self._provider.analyze(source)
        report_basis = {
            "report_version": REPORT_VERSION,
            "source_path": str(source),
            "source_sha256": before.sha256,
            "preset": preset,
            "target_rms_dbfs": TARGET_RMS_DBFS,
            "max_peak_dbfs": MAX_PEAK_DBFS,
            "rms_tolerance_db": RMS_TOLERANCE_DB,
        }
        report_id = hashlib.sha256(
            json.dumps(
                report_basis,
                sort_keys=True,
                separators=(",", ":"),
            ).encode("utf-8")
        ).hexdigest()
        output = (
            self._output_root
            / f"{source.stem}.{report_id[:12]}.dialogue.wav"
        ).resolve()
        report_path = self._reports_root / f"{report_id}.json"
        if report_path.is_file() and output.is_file():
            existing_report = read_json_object(report_path)
            validate_contract("audio-report", existing_report)
            return existing_report

        processing = self._provider.apply_dialogue_level_preset(
            source,
            output,
            target_rms_dbfs=TARGET_RMS_DBFS,
            max_peak_dbfs=MAX_PEAK_DBFS,
        )
        after = processing["after"]
        after_rms = after["rms_dbfs"]
        after_peak = after["peak_dbfs"]
        if not isinstance(after_rms, (int, float)) or not isinstance(
            after_peak,
            (int, float),
        ):
            raise AudioWorkflowError(
                "Processed audio did not produce numeric level measurements."
            )
        rms_error_db = abs(float(after_rms) - TARGET_RMS_DBFS)
        validation = {
            "target_met": (
                rms_error_db <= RMS_TOLERANCE_DB
                and float(after_peak) <= MAX_PEAK_DBFS + 0.01
            ),
            "rms_error_db": round(rms_error_db, 3),
            "peak_within_limit": (
                float(after_peak) <= MAX_PEAK_DBFS + 0.01
            ),
        }
        warnings = [
            (
                "RMS dBFS is not LUFS/EBU R128; use a verified loudness backend "
                "before delivery."
            )
        ]
        if bool(processing["peak_guard_limited"]):
            warnings.append(
                "Peak guard limited gain, so the RMS target may not be reached."
            )

        report: dict[str, Any] = {
            "report_version": REPORT_VERSION,
            "report_id": report_id,
            "created_at": _utc_now(),
            "status": "completed",
            "preset": {
                "name": PRESET_NAME,
                "target_rms_dbfs": TARGET_RMS_DBFS,
                "max_peak_dbfs": MAX_PEAK_DBFS,
                "rms_tolerance_db": RMS_TOLERANCE_DB,
            },
            "source": {
                "path": str(source),
                "preserved": True,
                "sha256": before.sha256,
            },
            "derived": {
                "path": str(output),
                "sha256": after["sha256"],
            },
            "before": processing["before"],
            "after": after,
            "processing": {
                "requested_gain_db": processing["requested_gain_db"],
                "applied_gain_db": processing["applied_gain_db"],
                "peak_guard_limited": processing["peak_guard_limited"],
            },
            "validation": validation,
            "warnings": warnings,
        }
        validate_contract("audio-report", report)
        atomic_write_json(report_path, report)
        return report


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
