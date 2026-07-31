"""M34 safe application tests."""

from __future__ import annotations

from pathlib import Path

import pytest

from agent.rough_cut_apply import RoughCutApplier, RoughCutApplyError, _canonical_sha256


class StubInspector:
    def __init__(self, plan: dict[str, object]) -> None:
        self.plan = plan
        self.approval = {
            "status": "approved",
            "plan_sha256": _canonical_sha256(plan),
        }

    def get_plan(self, plan_id: str) -> dict[str, object]:
        return {
            "plan": self.plan,
            "approval": self.approval,
            "effective_status": "approved",
        }


def _plan(
    required_capabilities: list[str],
    operations: list[dict[str, str]] | None = None,
) -> dict[str, object]:
    return {
        "plan_id": "a" * 64,
        "required_capabilities": required_capabilities,
        "proposed_operations": (
            [{"operation": "remove_pauses"}]
            if operations is None
            else operations
        ),
    }


def test_preview_blocks_unverified_capabilities_without_write(tmp_path: Path) -> None:
    calls: list[tuple[str, str, str]] = []

    def duplicate(
        source: str,
        name: str,
        key: str,
        timeout_seconds: float,
    ) -> dict[str, str]:
        calls.append((source, name, key))
        return {}

    applier = RoughCutApplier(
        inspector=StubInspector(_plan(["clip.move", "clip.trim"])),  # type: ignore[arg-type]
        capabilities=lambda: {"timeline.duplicate": "unknown", "clip.move": False},
        duplicate_timeline=duplicate,
        receipts_root=tmp_path,
    )

    preview = applier.preview("a" * 64, "source", "Rough Cut Copy")
    applied = applier.apply("a" * 64, "source", "Rough Cut Copy", confirm_apply=True)

    assert preview["status"] == "blocked"
    assert preview["unsupported_capabilities"] == [
        "clip.move",
        "clip.trim",
        "timeline.duplicate",
    ]
    assert preview["unsupported_operations"] == ["remove_pauses"]
    assert applied == preview
    assert calls == []
    assert list(tmp_path.glob("*.json")) == []


def test_apply_duplicates_only_a_verified_copy_and_replays_receipt(
    tmp_path: Path,
) -> None:
    calls: list[tuple[str, str, str]] = []

    def duplicate(
        source: str,
        name: str,
        key: str,
        timeout_seconds: float,
    ) -> dict[str, str]:
        calls.append((source, name, key))
        return {"timeline_id": "copy"}

    applier = RoughCutApplier(
        inspector=StubInspector(_plan([], [])),  # type: ignore[arg-type]
        capabilities=lambda: {"timeline.duplicate": True},
        duplicate_timeline=duplicate,
        receipts_root=tmp_path,
    )

    result = applier.apply("a" * 64, "source", "Rough Cut Copy", confirm_apply=True)
    replay = applier.apply("a" * 64, "source", "Rough Cut Copy", confirm_apply=True)

    assert result["status"] == "applied"
    assert result["preview"] is False
    assert result["operations"][0]["result"] == {"timeline_id": "copy"}
    assert replay == result
    assert len(calls) == 1
    assert len(list(tmp_path.glob("*.json"))) == 1


def test_apply_requires_current_approval_and_explicit_confirmation(
    tmp_path: Path,
) -> None:
    plan = _plan([])
    inspector = StubInspector(plan)
    inspector.approval["plan_sha256"] = "b" * 64
    applier = RoughCutApplier(
        inspector=inspector,  # type: ignore[arg-type]
        capabilities=lambda: {"timeline.duplicate": True},
        duplicate_timeline=lambda source, name, key, timeout_seconds: {},
        receipts_root=tmp_path,
    )

    with pytest.raises(RoughCutApplyError, match="confirm_apply"):
        applier.apply("a" * 64, "source", "copy", confirm_apply=False)
    with pytest.raises(RoughCutApplyError, match="SHA-256"):
        applier.preview("a" * 64, "source", "copy")
