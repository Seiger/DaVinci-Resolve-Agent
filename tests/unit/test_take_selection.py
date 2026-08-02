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
        lambda path, candidate_id: _measurement(candidate_id),
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


def _workflow(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> tuple[TakeSelectionWorkflow, list[dict[str, str]]]:
    media = tmp_path / "media"
    media.mkdir()
    first = media / "first.mkv"
    second = media / "second.mkv"
    first.write_bytes(b"first")
    second.write_bytes(b"second")
    monkeypatch.setattr(
        "agent.take_selection._analyze_file",
        lambda path, candidate_id: _measurement(candidate_id),
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


def _measurement(candidate_id: str) -> dict[str, object]:
    score = 82.0 if candidate_id == "take-b" else 75.0
    return {
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
