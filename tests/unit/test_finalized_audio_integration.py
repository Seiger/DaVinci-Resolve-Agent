"""Tests for guarded M46 cleaned-audio timeline integration."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from agent.finalized_audio_integration import FinalizedAudioIntegrator

EXTRACTION_ID = "a" * 64
REPORT_ID = "b" * 64
TIMELINE_ID = "timeline-final"


class FakeReportReader:
    def __init__(self, report: dict[str, Any]) -> None:
        self.report = report

    def get_report(self, report_id: str) -> dict[str, Any]:
        assert report_id == REPORT_ID
        return self.report


class FakeGateway:
    def __init__(self) -> None:
        self.calls: list[str] = []

    def import_media(self, paths: list[str], **kwargs: Any) -> dict[str, Any]:
        self.calls.append("import")
        assert kwargs["idempotency_key"] == f"m46:{REPORT_ID[:16]}:import"
        return {"items": [{"asset_id": "clean-asset", "name": Path(paths[0]).name}]}

    def ensure_timeline_tracks(self, *args: Any, **kwargs: Any) -> dict[str, Any]:
        self.calls.append("ensure")
        assert args[:3] == (TIMELINE_ID, 2, 2)
        return {
            "timeline_id": TIMELINE_ID,
            "video_track_count": 2,
            "audio_track_count": 2,
        }

    def insert_clip(self, *args: Any, **kwargs: Any) -> dict[str, Any]:
        self.calls.append("insert")
        assert args[:7] == (TIMELINE_ID, "clean-asset", 0, 240, 0, "audio", 2)
        return {
            "item": {
                "timeline_item_id": "clean-item",
                "timeline_start_frame": 86400,
                "timeline_end_frame": 86640,
                "source_start_frame": 0,
                "source_end_frame": 240,
                "track_type": "audio",
                "track_index": 2,
            }
        }

    def set_clip_enabled(self, *args: Any, **kwargs: Any) -> dict[str, Any]:
        action = "enable" if args[2] else "disable"
        self.calls.append(f"{action}:{args[1]}")
        return {
            "timeline_id": TIMELINE_ID,
            "timeline_item_id": args[1],
            "enabled": args[2],
        }

    def timeline_items(self, *args: Any, **kwargs: Any) -> dict[str, Any]:
        self.calls.append("readback")
        return {
            "timeline_id": TIMELINE_ID,
            "items": [
                {
                    "timeline_item_id": "video-a",
                    "track_type": "video",
                    "track_index": 1,
                },
                {
                    "timeline_item_id": "video-b",
                    "track_type": "video",
                    "track_index": 1,
                },
                {
                    "timeline_item_id": "source-a",
                    "track_type": "audio",
                    "track_index": 1,
                },
                {
                    "timeline_item_id": "source-b",
                    "track_type": "audio",
                    "track_index": 1,
                },
                {
                    "timeline_item_id": "clean-item",
                    "track_type": "audio",
                    "track_index": 2,
                },
            ],
        }


def test_integration_applies_exact_audio_once_and_replays_receipt(
    tmp_path: Path,
) -> None:
    source = tmp_path / "source.wav"
    derived = tmp_path / "derived.wav"
    source.touch()
    derived.touch()
    finalizations = tmp_path / "finalizations"
    finalizations.mkdir()
    (finalizations / f"{'c' * 64}.json").write_text(
        json.dumps(_finalization()), encoding="utf-8"
    )
    gateway = FakeGateway()
    integrator = FinalizedAudioIntegrator(
        gateway=gateway,
        extraction_status=lambda *args, **kwargs: _extraction(source),
        report_reader=FakeReportReader(_report(source, derived)),
        finalizations_root=finalizations,
        receipts_root=tmp_path / "receipts",
    )

    first = integrator.apply(
        extraction_receipt_id=EXTRACTION_ID,
        audio_report_id=REPORT_ID,
        confirm_apply=True,
    )
    second = integrator.apply(
        extraction_receipt_id=EXTRACTION_ID,
        audio_report_id=REPORT_ID,
        confirm_apply=True,
    )

    assert first == second
    assert first["status"] == "applied"
    assert first["source_audio_item_ids"] == ["source-a", "source-b"]
    assert first["source_video_item_ids"] == ["video-a", "video-b"]
    assert gateway.calls == [
        "import",
        "ensure",
        "insert",
        "disable:source-a",
        "disable:source-b",
        "enable:video-a",
        "enable:video-b",
        "readback",
    ]


def _extraction(source: Path) -> dict[str, Any]:
    return {
        "receipt": {
            "inputs": {"finalization_receipt_id": "c" * 64},
            "target": {"timeline_id": TIMELINE_ID, "timeline_name": "Final"},
        },
        "live": {"job": {"MarkIn": 86400, "MarkOut": 86639, "FrameRate": "24"}},
        "output": {
            "output": {"path": str(source)},
            "validation": {"passed": True},
        },
    }


def _report(source: Path, derived: Path) -> dict[str, Any]:
    return {
        "status": "completed",
        "preset": {"name": "pcm-dialogue-limit-v2"},
        "source": {"path": str(source)},
        "derived": {"path": str(derived)},
        "before": {"duration_ms": 10_000},
        "validation": {"target_met": True},
    }


def _finalization() -> dict[str, Any]:
    return {
        "status": "applied",
        "link_groups": [
            ["video-a", "source-a"],
            ["video-b", "source-b"],
        ],
        "readback": {
            "items": [
                {
                    "timeline_item_id": "video-a",
                    "track_type": "video",
                    "track_index": 1,
                },
                {
                    "timeline_item_id": "video-b",
                    "track_type": "video",
                    "track_index": 2,
                },
                {
                    "timeline_item_id": "source-a",
                    "track_type": "audio",
                    "track_index": 1,
                },
                {
                    "timeline_item_id": "source-b",
                    "track_type": "audio",
                    "track_index": 1,
                },
            ]
        },
    }
