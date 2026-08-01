"""Local transcription adapter and SRT artifact tests."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from agent.subtitles import (
    SubtitleArtifactError,
    SubtitleGenerator,
    render_srt,
    write_srt,
)
from providers.transcription import faster_whisper


class FakeModel:
    def __init__(self, model: str, **options: Any) -> None:
        assert model == "small"
        assert options["device"] == "cpu"
        assert options["compute_type"] == "int8"

    def transcribe(self, source: str, **options: Any) -> tuple[list[Any], Any]:
        assert Path(source).is_file()
        assert options["language"] == "uk"
        return (
            [SimpleNamespace(start=0.0, end=1.25, text="  Привіт   світе ")],
            SimpleNamespace(language="uk", language_probability=0.99, duration=1.25),
        )


def test_faster_whisper_adapter_normalizes_bounded_segments(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source = tmp_path / "dialogue.wav"
    source.write_bytes(b"fixture")
    monkeypatch.setattr(
        faster_whisper,
        "import_module",
        lambda _: SimpleNamespace(WhisperModel=FakeModel),
    )

    result = faster_whisper.FasterWhisperTranscriber(
        tmp_path / "models"
    ).transcribe(source)

    assert result["model"] == "small"
    assert result["segments"] == [
        {"start_ms": 0, "end_ms": 1250, "text": "Привіт світе"}
    ]


def test_srt_render_and_atomic_write_are_deterministic(tmp_path: Path) -> None:
    transcript = {
        "segments": [
            {"start_ms": 0, "end_ms": 1250, "text": "Привіт світе"},
            {"start_ms": 1500, "end_ms": 3723004, "text": "Другий рядок"},
        ]
    }
    expected = (
        "1\n00:00:00,000 --> 00:00:01,250\nПривіт світе\n\n"
        "2\n00:00:01,500 --> 01:02:03,004\nДругий рядок\n"
    )

    assert render_srt(transcript) == expected
    output = write_srt(tmp_path / "captions" / "result.srt", transcript)
    assert output.read_text(encoding="utf-8") == expected
    assert list(output.parent.glob("*.tmp")) == []


def test_srt_rejects_overlapping_segments() -> None:
    with pytest.raises(SubtitleArtifactError, match="overlap"):
        render_srt(
            {
                "segments": [
                    {"start_ms": 0, "end_ms": 1000, "text": "One"},
                    {"start_ms": 999, "end_ms": 2000, "text": "Two"},
                ]
            }
        )


class StubTranscriber:
    def transcribe(self, source_path: Path) -> dict[str, Any]:
        return {
            "backend": "stub",
            "model": "test",
            "language": "uk",
            "segments": [
                {"start_ms": 0, "end_ms": 1000, "text": "Тест"}
            ],
        }


class StubPolicy:
    def validate_files(self, paths: list[str]) -> list[str]:
        assert Path(paths[0]).is_file()
        return [str(Path(paths[0]).resolve())]

    def prepare_import(self, paths: list[str]) -> list[str]:
        assert Path(paths[0]).suffix == ".srt"
        return [str(Path(paths[0]).resolve())]


class StubGateway:
    def __init__(self) -> None:
        self.read_count = 0

    def subtitle_environment(
        self, timeline_id: str, *, timeout_seconds: float = 30
    ) -> dict[str, Any]:
        self.read_count += 1
        items = [] if self.read_count == 1 else [
            {
                "timeline_item_id": "subtitle-1",
                "text": "Тест",
                "timeline_start_frame": 86400,
            }
        ]
        return {
            "timeline_id": timeline_id,
            "subtitle_item_count": len(items),
            "tracks": [{"items": items}] if items else [],
        }

    def import_media(
        self,
        paths: list[str],
        *,
        timeout_seconds: float = 30,
        idempotency_key: str | None = None,
    ) -> dict[str, Any]:
        return {"items": [{"asset_id": "subtitle-asset"}]}

    def append_subtitle_file(
        self,
        timeline_id: str,
        asset_id: str,
        subtitle_path: str,
        import_idempotency_key: str,
        *,
        confirm_apply: bool,
        timeout_seconds: float = 30,
        idempotency_key: str | None = None,
    ) -> dict[str, Any]:
        return {
            "items": [{"timeline_item_id": "subtitle-1"}],
            "timeline_start_frame": 86400,
            "append_frame": 86400,
            "timeline_frame_rate": 24.0,
        }


class RecoveredStubGateway(StubGateway):
    def subtitle_environment(
        self, timeline_id: str, *, timeout_seconds: float = 30
    ) -> dict[str, Any]:
        item = {
            "timeline_item_id": "subtitle-1",
            "text": "Тест",
            "timeline_start_frame": 86400,
        }
        return {
            "timeline_id": timeline_id,
            "subtitle_item_count": 1,
            "tracks": [{"items": [item]}],
        }

    def append_subtitle_file(
        self,
        timeline_id: str,
        asset_id: str,
        subtitle_path: str,
        import_idempotency_key: str,
        *,
        confirm_apply: bool,
        timeout_seconds: float = 30,
        idempotency_key: str | None = None,
    ) -> dict[str, Any]:
        result = super().append_subtitle_file(
            timeline_id,
            asset_id,
            subtitle_path,
            import_idempotency_key,
            confirm_apply=confirm_apply,
            timeout_seconds=timeout_seconds,
            idempotency_key=idempotency_key,
        )
        result.pop("append_frame")
        return result


def test_subtitle_generator_applies_srt_and_persists_replay_receipt(
    tmp_path: Path,
) -> None:
    source = tmp_path / "source.wav"
    source.write_bytes(b"audio")
    gateway = StubGateway()
    generator = SubtitleGenerator(
        StubTranscriber(),
        gateway,
        StubPolicy(),
        tmp_path / "outputs",
        tmp_path / "receipts",
    )

    first = generator.generate(
        str(source),
        "timeline-1",
        confirm_apply=True,
    )
    replay = generator.generate(
        str(source),
        "timeline-1",
        confirm_apply=True,
    )

    assert first == replay
    assert first["status"] == "applied"
    assert first["timeline_item_ids"] == ["subtitle-1"]
    assert Path(first["subtitle_file"]).read_text(encoding="utf-8").endswith(
        "Тест\n"
    )
    assert gateway.read_count == 2


def test_subtitle_generator_recovers_from_provider_receipts(
    tmp_path: Path,
) -> None:
    source = tmp_path / "source.wav"
    source.write_bytes(b"audio")
    generator = SubtitleGenerator(
        StubTranscriber(),
        RecoveredStubGateway(),
        StubPolicy(),
        tmp_path / "outputs",
        tmp_path / "receipts",
    )

    result = generator.generate(
        str(source),
        "timeline-1",
        confirm_apply=True,
    )

    assert result["status"] == "applied"
    assert result["previous_subtitle_item_count"] == 1
    assert result["subtitle_item_count"] == 1
    assert result["timeline_item_ids"] == ["subtitle-1"]
    assert result["placement"]["append_frame_source"] == (
        "recovered_provider_receipt"
    )
