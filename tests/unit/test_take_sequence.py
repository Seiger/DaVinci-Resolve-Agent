"""M54.4 approved take-sequence planning tests."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from agent.contracts import validate_contract
from agent.media import MediaPolicy
from agent.take_selection import TakeSelectionWorkflow
from agent.take_sequence import TakeSequenceError, TakeSequenceWorkflow


def test_take_sequence_composes_approved_selections_deterministically(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    selections, candidates = _selection_workflow(tmp_path, monkeypatch)
    first_selection = selections.analyze(
        selection_name="First line",
        candidates=candidates,
    )
    selections.review(
        selection_id=first_selection["selection_id"],
        decision="approve",
        selected_candidate_id="take-b",
        note="Confirmed by the editor.",
    )
    sequence_workflow = TakeSequenceWorkflow(
        selections,
        tmp_path / "sequences",
    )

    first = sequence_workflow.compose(
        sequence_name="Approved intro",
        selection_ids=[first_selection["selection_id"]],
    )
    replay = sequence_workflow.compose(
        sequence_name="Approved intro",
        selection_ids=[first_selection["selection_id"]],
    )

    assert first == replay
    assert first["status"] == "approved_plan"
    assert first["timeline_modified"] is False
    assert first["apply_supported"] is False
    assert first["entries"][0]["selected_candidate_id"] == "take-b"
    assert first["entries"][0]["order"] == 1
    assert str(tmp_path) not in json.dumps(first)
    validate_contract("take-sequence", first)
    assert sequence_workflow.get(first["sequence_id"]) == first
    assert sequence_workflow.list() == {
        "sequences": [
            {
                "sequence_id": first["sequence_id"],
                "sequence_name": "Approved intro",
                "status": "approved_plan",
                "entry_count": 1,
                "total_duration_seconds": 10.0,
            }
        ],
        "count": 1,
    }


def test_take_sequence_rejects_unreviewed_or_rejected_selection(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    selections, candidates = _selection_workflow(tmp_path, monkeypatch)
    selection = selections.analyze(
        selection_name="Rejected line",
        candidates=candidates,
    )
    sequence_workflow = TakeSequenceWorkflow(
        selections,
        tmp_path / "sequences",
    )

    with pytest.raises(ValueError, match="has not been reviewed"):
        sequence_workflow.compose(
            sequence_name="Unsafe",
            selection_ids=[selection["selection_id"]],
        )

    selections.review(
        selection_id=selection["selection_id"],
        decision="reject",
        selected_candidate_id=None,
    )
    with pytest.raises(TakeSequenceError, match="not approved"):
        sequence_workflow.compose(
            sequence_name="Unsafe",
            selection_ids=[selection["selection_id"]],
        )


def test_take_sequence_get_rejects_tampered_content(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    selections, candidates = _selection_workflow(tmp_path, monkeypatch)
    selection = selections.analyze(
        selection_name="Integrity line",
        candidates=candidates,
    )
    selections.review(
        selection_id=selection["selection_id"],
        decision="approve",
        selected_candidate_id="take-a",
    )
    workflow = TakeSequenceWorkflow(selections, tmp_path / "sequences")
    sequence = workflow.compose(
        sequence_name="Integrity",
        selection_ids=[selection["selection_id"]],
    )
    artifact = tmp_path / "sequences" / f"{sequence['sequence_id']}.json"
    tampered = json.loads(artifact.read_text(encoding="utf-8"))
    tampered["total_duration_seconds"] = 1.0
    artifact.write_text(json.dumps(tampered), encoding="utf-8")

    with pytest.raises(TakeSequenceError, match="integrity"):
        workflow.get(sequence["sequence_id"])


def _selection_workflow(
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
        lambda path, candidate_id, source_range=None: _measurement(candidate_id),
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
