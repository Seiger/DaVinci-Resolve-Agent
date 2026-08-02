"""Provider-neutral M54.4 sequence plans from approved take selections."""

from __future__ import annotations

import hashlib
import json
import math
from pathlib import Path
from typing import Any, Protocol

from agent.contracts import validate_contract
from agent.paths import take_sequences_directory
from transports.filesystem import atomic_write_json, read_json_object

SEQUENCE_VERSION = "1.0"
MAX_SELECTIONS = 100


class TakeSequenceError(ValueError):
    """Raised when an approved take sequence is invalid or inconsistent."""


class ReviewedTakeSelections(Protocol):
    """Read-only selection/review boundary consumed by M54.4."""

    def get(self, selection_id: str) -> dict[str, Any]: ...

    def get_review(self, selection_id: str) -> dict[str, Any]: ...


class TakeSequenceWorkflow:
    """Compose immutable ordered handoffs without editing a provider timeline."""

    def __init__(
        self,
        selections: ReviewedTakeSelections,
        sequences_root: Path | None = None,
    ) -> None:
        self._selections = selections
        self._sequences_root = sequences_root or take_sequences_directory()

    def compose(
        self,
        *,
        sequence_name: str,
        selection_ids: list[str],
    ) -> dict[str, Any]:
        """Create one deterministic sequence from approved selections."""
        name = _sequence_name(sequence_name)
        identifiers = _selection_ids(selection_ids)
        entries: list[dict[str, Any]] = []
        for order, selection_id in enumerate(identifiers, start=1):
            selection = self._selections.get(selection_id)
            review = self._selections.get_review(selection_id)
            if review.get("decision") != "approve":
                raise TakeSequenceError(
                    f"Take selection is not approved: {selection_id}"
                )
            selected_id = review.get("selected_candidate_id")
            candidates = selection.get("candidates")
            if not isinstance(selected_id, str) or not isinstance(candidates, list):
                raise TakeSequenceError("Approved take review is incomplete.")
            candidate = next(
                (
                    item
                    for item in candidates
                    if isinstance(item, dict)
                    and item.get("candidate_id") == selected_id
                ),
                None,
            )
            if candidate is None:
                raise TakeSequenceError(
                    "Approved candidate is not present in the take selection."
                )
            entries.append(
                _entry(order, selection, review, candidate)
            )
        payload = {
            "sequence_version": SEQUENCE_VERSION,
            "status": "approved_plan",
            "sequence_name": name,
            "entries": entries,
            "total_duration_seconds": round(
                sum(entry["duration_seconds"] for entry in entries),
                3,
            ),
            "timeline_modified": False,
            "apply_supported": False,
        }
        result = {**payload, "sequence_id": _canonical_sha256(payload)}
        validate_contract("take-sequence", result)
        self._sequences_root.mkdir(parents=True, exist_ok=True)
        path = self._sequences_root / f"{result['sequence_id']}.json"
        if path.is_file():
            existing = read_json_object(path)
            validate_contract("take-sequence", existing)
            if existing != result:
                raise TakeSequenceError(
                    "Stored take sequence does not match deterministic plan."
                )
            return existing
        atomic_write_json(path, result)
        return result

    def get(self, sequence_id: str) -> dict[str, Any]:
        """Return one canonical persisted take sequence."""
        identifier = _sha256(sequence_id, "sequence_id")
        path = self._sequences_root / f"{identifier}.json"
        if not path.is_file():
            raise TakeSequenceError("The take sequence was not found.")
        result = read_json_object(path)
        validate_contract("take-sequence", result)
        payload = dict(result)
        payload.pop("sequence_id", None)
        if (
            result.get("sequence_id") != identifier
            or _canonical_sha256(payload) != identifier
        ):
            raise TakeSequenceError("Stored take sequence integrity is invalid.")
        return result

    def list(self, limit: int = 20) -> dict[str, Any]:
        """List bounded sequence summaries without source paths."""
        if (
            isinstance(limit, bool)
            or not isinstance(limit, int)
            or not 1 <= limit <= 100
        ):
            raise TakeSequenceError("limit must be between 1 and 100.")
        if not self._sequences_root.is_dir():
            return {"sequences": [], "count": 0}
        sequences: list[dict[str, Any]] = []
        for path in sorted(
            self._sequences_root.glob("*.json"),
            key=lambda item: item.stat().st_mtime_ns,
            reverse=True,
        )[:limit]:
            sequence = self.get(path.stem)
            sequences.append(
                {
                    "sequence_id": sequence["sequence_id"],
                    "sequence_name": sequence["sequence_name"],
                    "status": sequence["status"],
                    "entry_count": len(sequence["entries"]),
                    "total_duration_seconds": sequence[
                        "total_duration_seconds"
                    ],
                }
            )
        return {"sequences": sequences, "count": len(sequences)}


def _entry(
    order: int,
    selection: dict[str, Any],
    review: dict[str, Any],
    candidate: dict[str, Any],
) -> dict[str, Any]:
    duration = candidate.get("duration_seconds")
    if (
        isinstance(duration, bool)
        or not isinstance(duration, (int, float))
        or not math.isfinite(float(duration))
        or float(duration) <= 0
    ):
        raise TakeSequenceError("Selected candidate duration is invalid.")
    entry = {
        "order": order,
        "selection_id": selection["selection_id"],
        "selection_sha256": _canonical_sha256(selection),
        "review_id": review["review_id"],
        "review_sha256": _canonical_sha256(review),
        "selected_candidate_id": candidate["candidate_id"],
        "display_name": candidate["display_name"],
        "fingerprint": candidate["fingerprint"],
        "size_bytes": candidate["size_bytes"],
        "duration_seconds": round(float(duration), 3),
        "technical_score": candidate["technical_score"],
    }
    source_range = candidate.get("source_range")
    if source_range is not None:
        entry["source_range"] = source_range
    selection_score = candidate.get("selection_score")
    if selection_score is not None:
        entry["selection_score"] = selection_score
    dialogue = candidate.get("dialogue")
    if isinstance(dialogue, dict):
        entry["dialogue"] = {
            "language": dialogue["language"],
            "transcript_sha256": dialogue["transcript_sha256"],
            "reference_f1": dialogue["reference_f1"],
            "speech_coverage": dialogue["speech_coverage"],
        }
    return entry


def _sequence_name(value: str) -> str:
    if not isinstance(value, str) or not 1 <= len(value.strip()) <= 128:
        raise TakeSequenceError(
            "sequence_name must contain between 1 and 128 characters."
        )
    return value.strip()


def _selection_ids(values: list[str]) -> list[str]:
    if not isinstance(values, list) or not 1 <= len(values) <= MAX_SELECTIONS:
        raise TakeSequenceError("selection_ids must contain between 1 and 100 IDs.")
    normalized = [_sha256(value, "selection_id") for value in values]
    if len(set(normalized)) != len(normalized):
        raise TakeSequenceError("selection_ids must be unique.")
    return normalized


def _sha256(value: str, name: str) -> str:
    if (
        not isinstance(value, str)
        or len(value) != 64
        or any(character not in "0123456789abcdef" for character in value)
    ):
        raise TakeSequenceError(f"{name} must be a lowercase SHA-256 ID.")
    return value


def _canonical_sha256(payload: dict[str, Any]) -> str:
    canonical = json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()
