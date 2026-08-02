"""M55.2 take-sequence assembly preview tests."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from agent.contracts import validate_contract
from agent.take_sequence_assembly import (
    TakeSequenceAssemblyError,
    TakeSequenceAssemblyWorkflow,
)


class StubBindings:
    def __init__(self, sources: list[dict[str, Any]]) -> None:
        self.sources = sources
        self.binding: dict[str, Any] = {
            "binding_id": "a" * 64,
            "sources": [
                {key: value for key, value in source.items() if key != "path"}
                for source in sources
            ],
        }

    def get(self, binding_id: str) -> dict[str, Any]:
        assert binding_id == self.binding["binding_id"]
        return self.binding

    def resolve_sources(self, binding_id: str) -> list[dict[str, Any]]:
        assert binding_id == self.binding["binding_id"]
        return self.sources


class StubMetadata:
    def __init__(self, values: dict[str, dict[str, int | float]]) -> None:
        self.values = values

    def inspect(self, path: Path) -> dict[str, int | float]:
        return self.values[path.name]


def test_preview_calculates_sequential_ranges_and_redacts_paths(
    tmp_path: Path,
) -> None:
    first = _source(tmp_path / "first.mkv", 1, "take-a")
    first["source_range"] = {"start_seconds": 2.0, "end_seconds": 5.5}
    second = _source(tmp_path / "second.mkv", 2, "take-b")
    workflow = TakeSequenceAssemblyWorkflow(
        StubBindings([first, second]),
        StubMetadata(
            {
                "first.mkv": _metadata(10.0, 60.0, 2560, 1440),
                "second.mkv": _metadata(4.0, 60.0, 2560, 1440),
            }
        ),
    )

    result = workflow.preview(
        binding_id="a" * 64,
        assembly_name="Approved assembly",
    )

    assert result["status"] == "preview"
    assert result["entries"][0]["output_range"] == {
        "start_seconds": 0.0,
        "end_seconds": 3.5,
    }
    assert result["entries"][1]["source_range"] == {
        "start_seconds": 0.0,
        "end_seconds": 4.0,
    }
    assert result["entries"][1]["output_range"] == {
        "start_seconds": 3.5,
        "end_seconds": 7.5,
    }
    assert result["total_duration_seconds"] == 7.5
    assert result["uniform_frame_rate"] is True
    assert result["uniform_resolution"] is True
    assert result["warnings"] == []
    assert result["timeline_modified"] is False
    assert result["apply_supported"] is False
    assert str(tmp_path) not in json.dumps(result)
    validate_contract("take-sequence-assembly-preview", result)


def test_preview_warns_about_mixed_source_video_formats(tmp_path: Path) -> None:
    first = _source(tmp_path / "first.mkv", 1, "take-a")
    second = _source(tmp_path / "second.mkv", 2, "take-b")
    workflow = TakeSequenceAssemblyWorkflow(
        StubBindings([first, second]),
        StubMetadata(
            {
                "first.mkv": _metadata(5.0, 60.0, 2560, 1440),
                "second.mkv": _metadata(5.0, 30.0, 1920, 1080),
            }
        ),
    )

    result = workflow.preview(binding_id="a" * 64, assembly_name="Mixed")

    assert result["uniform_frame_rate"] is False
    assert result["uniform_resolution"] is False
    assert len(result["warnings"]) == 2


def test_preview_rejects_range_past_media_duration(tmp_path: Path) -> None:
    source = _source(tmp_path / "first.mkv", 1, "take-a")
    source["source_range"] = {"start_seconds": 4.0, "end_seconds": 8.0}
    workflow = TakeSequenceAssemblyWorkflow(
        StubBindings([source]),
        StubMetadata({"first.mkv": _metadata(5.0, 60.0, 1920, 1080)}),
    )

    with pytest.raises(TakeSequenceAssemblyError, match="exceeds"):
        workflow.preview(binding_id="a" * 64, assembly_name="Invalid")


def test_preview_rejects_private_public_binding_mismatch(tmp_path: Path) -> None:
    source = _source(tmp_path / "first.mkv", 1, "take-a")
    bindings = StubBindings([source])
    bindings.binding["sources"][0]["fingerprint"] = "f" * 64
    workflow = TakeSequenceAssemblyWorkflow(
        bindings,
        StubMetadata({"first.mkv": _metadata(5.0, 60.0, 1920, 1080)}),
    )

    with pytest.raises(TakeSequenceAssemblyError, match="does not match"):
        workflow.preview(binding_id="a" * 64, assembly_name="Invalid")


def _source(path: Path, order: int, candidate_id: str) -> dict[str, Any]:
    return {
        "order": order,
        "selected_candidate_id": candidate_id,
        "display_name": path.name,
        "fingerprint": str(order) * 64,
        "size_bytes": 100,
        "path": str(path.resolve()),
    }


def _metadata(
    duration: float,
    frame_rate: float,
    width: int,
    height: int,
) -> dict[str, int | float]:
    return {
        "duration_seconds": duration,
        "frame_rate": frame_rate,
        "width": width,
        "height": height,
    }
