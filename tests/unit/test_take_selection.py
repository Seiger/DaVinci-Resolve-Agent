"""M54 bounded take-analysis and human-review tests."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from agent.contracts import validate_contract
from agent.media import MediaPolicy
from agent.take_selection import (
    TakeSelectionError,
    TakeSelectionWorkflow,
)


def test_take_analysis_ranks_deterministically_and_redacts_paths(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    workflow, candidates = _workflow(tmp_path, monkeypatch)

    first = workflow.analyze(
        selection_name="Tutorial intro",
        candidates=candidates,
    )
    second = workflow.analyze(
        selection_name="Tutorial intro",
        candidates=candidates,
    )

    assert first == second
    assert first["status"] == "pending_review"
    assert first["review_required"] is True
    assert first["recommendation"] == {
        "candidate_id": "take-b",
        "confidence": "medium",
        "score_gap": 7.0,
        "basis": "bounded technical measurements only",
        "limitations": [
            "No semantic, performance, or story-quality judgment.",
            "Video is sampled at fixed positions rather than fully decoded.",
            "A human must approve or reject the recommendation.",
        ],
    }
    assert [item["candidate_id"] for item in first["candidates"]] == [
        "take-b",
        "take-a",
    ]
    assert str(tmp_path) not in json.dumps(first)
    validate_contract("take-selection", first)


def test_take_review_is_immutable_and_never_modifies_timeline(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    workflow, candidates = _workflow(tmp_path, monkeypatch)
    selection = workflow.analyze(
        selection_name="Tutorial intro",
        candidates=candidates,
    )

    first = workflow.review(
        selection_id=selection["selection_id"],
        decision="approve",
        selected_candidate_id="take-b",
        note="Use the cleaner take.",
    )
    second = workflow.review(
        selection_id=selection["selection_id"],
        decision="approve",
        selected_candidate_id="take-b",
        note="Use the cleaner take.",
    )

    assert first == second
    assert first["timeline_modified"] is False
    assert first["selected_candidate_id"] == "take-b"
    validate_contract("take-selection-review", first)
    with pytest.raises(TakeSelectionError, match="different review"):
        workflow.review(
            selection_id=selection["selection_id"],
            decision="reject",
            selected_candidate_id=None,
        )


def test_take_selection_get_rejects_tampered_persisted_content(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    workflow, candidates = _workflow(tmp_path, monkeypatch)
    selection = workflow.analyze(
        selection_name="Integrity test",
        candidates=candidates,
    )
    artifact = tmp_path / "selections" / f"{selection['selection_id']}.json"
    tampered = json.loads(artifact.read_text(encoding="utf-8"))
    tampered["candidates"][0]["technical_score"] = 1.0
    artifact.write_text(json.dumps(tampered), encoding="utf-8")

    with pytest.raises(TakeSelectionError, match="content is invalid"):
        workflow.get(selection["selection_id"])


def test_take_analysis_rejects_files_outside_allowed_root(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    allowed = tmp_path / "allowed"
    outside = tmp_path / "outside"
    allowed.mkdir()
    outside.mkdir()
    first = allowed / "first.mkv"
    second = outside / "second.mkv"
    first.write_bytes(b"one")
    second.write_bytes(b"two")
    monkeypatch.setattr(
        "agent.take_selection._analyze_file",
        lambda path, candidate_id, source_range=None: _measurement(
            candidate_id, source_range
        ),
    )
    workflow = TakeSelectionWorkflow(
        media_policy=MediaPolicy([allowed]),
        selections_root=tmp_path / "selections",
        reviews_root=tmp_path / "reviews",
    )

    with pytest.raises(ValueError, match="outside configured allowed roots"):
        workflow.analyze(
            selection_name="Unsafe",
            candidates=[
                {"candidate_id": "take-a", "path": str(first)},
                {"candidate_id": "take-b", "path": str(second)},
            ],
        )


def test_take_analysis_supports_multiple_bounded_segments_from_one_file(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    media = tmp_path / "media"
    media.mkdir()
    source = media / "source.mkv"
    source.write_bytes(b"shared source")
    monkeypatch.setattr(
        "agent.take_selection._analyze_file",
        lambda path, candidate_id, source_range=None: _measurement(
            candidate_id, source_range
        ),
    )
    workflow = TakeSelectionWorkflow(
        media_policy=MediaPolicy([media]),
        selections_root=tmp_path / "selections",
        reviews_root=tmp_path / "reviews",
    )
    candidates: list[dict[str, str | float]] = [
        {
            "candidate_id": "segment-a",
            "path": str(source),
            "start_seconds": 10.0,
            "end_seconds": 20.0,
        },
        {
            "candidate_id": "segment-b",
            "path": str(source),
            "start_seconds": 30.0,
            "end_seconds": 40.0,
        },
    ]

    first = workflow.analyze(selection_name="Shared source", candidates=candidates)
    second = workflow.analyze(selection_name="Shared source", candidates=candidates)

    assert first == second
    assert first["selection_version"] == "1.1"
    ranges = {
        item["candidate_id"]: item["source_range"] for item in first["candidates"]
    }
    assert ranges == {
        "segment-a": {"start_seconds": 10.0, "end_seconds": 20.0},
        "segment-b": {"start_seconds": 30.0, "end_seconds": 40.0},
    }
    assert first["policy"]["sampling"]["max_segment_seconds"] == 300.0
    assert str(media) not in json.dumps(first)
    validate_contract("take-selection", first)


class StubDialogueTranscriber:
    def __init__(self) -> None:
        self.call_count = 0

    def transcribe(
        self,
        source_path: Path,
        *,
        start_seconds: float | None = None,
        end_seconds: float | None = None,
    ) -> dict[str, object]:
        self.call_count += 1
        assert start_seconds is not None
        assert end_seconds is not None
        text = (
            "Це точний текст сценарію"
            if start_seconds == 10.0
            else "Це неточний варіант"
        )
        return {
            "backend": "stub",
            "model": "test",
            "language": "uk",
            "language_probability": 0.99,
            "segments": [
                {"start_ms": 0, "end_ms": 8_000, "text": text},
            ],
        }


def test_scripted_take_analysis_prioritizes_reference_match_without_storing_text(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    media = tmp_path / "media"
    media.mkdir()
    source = media / "source.mkv"
    source.write_bytes(b"shared source")
    monkeypatch.setattr(
        "agent.take_selection._analyze_file",
        lambda path, candidate_id, source_range=None: _measurement(
            candidate_id, source_range
        ),
    )
    transcriber = StubDialogueTranscriber()
    workflow = TakeSelectionWorkflow(
        media_policy=MediaPolicy([media]),
        transcriber=transcriber,
        selections_root=tmp_path / "selections",
        reviews_root=tmp_path / "reviews",
    )
    candidates: list[dict[str, str | float]] = [
        {
            "candidate_id": "exact",
            "path": str(source),
            "start_seconds": 10.0,
            "end_seconds": 20.0,
        },
        {
            "candidate_id": "variant",
            "path": str(source),
            "start_seconds": 30.0,
            "end_seconds": 40.0,
        },
    ]

    first = workflow.analyze_scripted(
        selection_name="Scripted intro",
        candidates=candidates,
        reference_text="Це точний текст сценарію",
    )
    replay = workflow.analyze_scripted(
        selection_name="Scripted intro",
        candidates=candidates,
        reference_text="Це точний текст сценарію",
    )

    assert first == replay
    assert transcriber.call_count == 2
    assert first["selection_version"] == "1.2"
    assert first["recommendation"]["candidate_id"] == "exact"
    assert first["candidates"][0]["dialogue"]["reference_f1"] == 1.0
    serialized = json.dumps(first, ensure_ascii=False)
    assert "Це точний текст сценарію" not in serialized
    assert str(media) not in serialized
    validate_contract("take-selection", first)


def test_scripted_take_analysis_requires_segments_and_local_transcriber(
    tmp_path: Path,
) -> None:
    source_a = tmp_path / "a.mkv"
    source_b = tmp_path / "b.mkv"
    source_a.write_bytes(b"a")
    source_b.write_bytes(b"b")
    workflow = TakeSelectionWorkflow(
        media_policy=MediaPolicy([tmp_path]),
        selections_root=tmp_path / "selections",
        reviews_root=tmp_path / "reviews",
    )

    with pytest.raises(TakeSelectionError, match="local transcriber"):
        workflow.analyze_scripted(
            selection_name="Scripted",
            candidates=[
                {"candidate_id": "a", "path": str(source_a)},
                {"candidate_id": "b", "path": str(source_b)},
            ],
            reference_text="Текст",
        )


@pytest.mark.parametrize(
    ("candidates", "message"),
    [
        (
            [
                {"candidate_id": "a", "path": "one.mkv"},
                {
                    "candidate_id": "b",
                    "path": "two.mkv",
                    "start_seconds": 0.0,
                    "end_seconds": 10.0,
                },
            ],
            "all use full files or all use bounded source ranges",
        ),
        (
            [
                {
                    "candidate_id": "a",
                    "path": "one.mkv",
                    "start_seconds": 0.0,
                    "end_seconds": 301.0,
                },
                {
                    "candidate_id": "b",
                    "path": "two.mkv",
                    "start_seconds": 0.0,
                    "end_seconds": 10.0,
                },
            ],
            "must not exceed 300 seconds",
        ),
    ],
)
def test_take_analysis_rejects_invalid_segment_sets(
    tmp_path: Path,
    candidates: list[dict[str, str | float]],
    message: str,
) -> None:
    workflow = TakeSelectionWorkflow(
        media_policy=MediaPolicy([tmp_path]),
        selections_root=tmp_path / "selections",
        reviews_root=tmp_path / "reviews",
    )

    with pytest.raises(TakeSelectionError, match=message):
        workflow.analyze(selection_name="Invalid segments", candidates=candidates)


def _workflow(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> tuple[TakeSelectionWorkflow, list[dict[str, str | float]]]:
    media = tmp_path / "media"
    media.mkdir()
    first = media / "first.mkv"
    second = media / "second.mkv"
    first.write_bytes(b"first")
    second.write_bytes(b"second")
    monkeypatch.setattr(
        "agent.take_selection._analyze_file",
        lambda path, candidate_id, source_range=None: _measurement(
            candidate_id, source_range
        ),
    )
    workflow = TakeSelectionWorkflow(
        media_policy=MediaPolicy([media]),
        selections_root=tmp_path / "selections",
        reviews_root=tmp_path / "reviews",
    )
    return workflow, [
        {"candidate_id": "take-a", "path": str(first)},
        {"candidate_id": "take-b", "path": str(second)},
    ]


def _measurement(
    candidate_id: str,
    source_range: dict[str, float] | None = None,
) -> dict[str, object]:
    score = 82.0 if candidate_id == "take-b" else 75.0
    result: dict[str, object] = {
        "candidate_id": candidate_id,
        "display_name": f"{candidate_id}.mkv",
        "fingerprint": ("b" if candidate_id == "take-b" else "a") * 64,
        "size_bytes": 100,
        "duration_seconds": 10.0,
        "video": {"sample_count": 7},
        "audio": {"present": True, "sample_count": 480000},
        "technical_score": score,
        "rank": 1,
        "strengths": ["Technically clean."],
        "warnings": [],
    }
    if source_range is not None:
        result["source_range"] = source_range
    return result
