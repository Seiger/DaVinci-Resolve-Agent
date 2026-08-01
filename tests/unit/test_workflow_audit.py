"""Structured local workflow audit tests."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from agent.contracts import ContractValidationError, validate_contract
from agent.workflow_audit import WorkflowAuditError, WorkflowAuditLog
from transports.filesystem import read_json_object


class FixedClock:
    def __init__(self) -> None:
        self.current = datetime(2026, 7, 31, 12, 0, tzinfo=timezone.utc)

    def __call__(self) -> datetime:
        value = self.current
        self.current += timedelta(milliseconds=40)
        return value


def test_workflow_audit_records_success_without_inputs_or_result(
    tmp_path: Path,
) -> None:
    audit = WorkflowAuditLog(tmp_path, FixedClock())

    result = audit.run("get_audio_report", lambda: {"private": "result"})
    record = read_json_object(
        next((tmp_path / "workflow").glob("*.json"))
    )

    assert result == {"private": "result"}
    validate_contract("workflow-audit-record", record)
    assert record["status"] == "success"
    assert record["duration_ms"] == 40
    assert record["operation"] == "get_audio_report"
    assert "inputs" not in record
    assert "arguments" not in record
    assert "result" not in record
    assert "private" not in str(record)


def test_workflow_audit_classifies_error_without_message(
    tmp_path: Path,
) -> None:
    audit = WorkflowAuditLog(tmp_path, FixedClock())

    def fail() -> None:
        raise ValueError(r"Private file C:\Users\name\video.wav")

    with pytest.raises(ValueError, match="Private file"):
        audit.run("clean_dialogue_audio", fail)
    record = read_json_object(
        next((tmp_path / "workflow").glob("*.json"))
    )

    assert record["status"] == "error"
    assert record["error_code"] == "VALIDATION_ERROR"
    assert record["retryable"] is False
    assert "Private file" not in str(record)
    assert "video.wav" not in str(record)


def test_workflow_audit_records_sync_without_asset_ids(
    tmp_path: Path,
) -> None:
    audit = WorkflowAuditLog(tmp_path, FixedClock())

    audit.run("sync_screen_and_webcam", lambda: {"asset_id": "private"})
    record = read_json_object(
        next((tmp_path / "workflow").glob("*.json"))
    )

    assert record["operation"] == "sync_screen_and_webcam"
    assert record["category"] == "editing"
    assert "asset_id" not in str(record)
    assert "private" not in str(record)


def test_workflow_audit_records_synchronized_link_as_editing(
    tmp_path: Path,
) -> None:
    audit = WorkflowAuditLog(tmp_path, FixedClock())

    audit.run(
        "link_synchronized_screen_pair",
        lambda: {"timeline_item_id": "private"},
    )
    record = read_json_object(
        next((tmp_path / "workflow").glob("*.json"))
    )

    assert record["operation"] == "link_synchronized_screen_pair"
    assert record["category"] == "editing"
    assert "timeline_item_id" not in str(record)


def test_workflow_audit_records_compaction_preview_as_rough_cut(
    tmp_path: Path,
) -> None:
    audit = WorkflowAuditLog(tmp_path, FixedClock())

    audit.run(
        "preview_synchronized_pause_compaction",
        lambda: {"asset_id": "private"},
    )
    record = read_json_object(
        next((tmp_path / "workflow").glob("*.json"))
    )

    assert record["operation"] == "preview_synchronized_pause_compaction"
    assert record["category"] == "rough_cut"
    assert "asset_id" not in str(record)


def test_workflow_audit_records_compaction_apply_as_rough_cut(
    tmp_path: Path,
) -> None:
    audit = WorkflowAuditLog(tmp_path, FixedClock())

    audit.run(
        "apply_synchronized_pause_compaction",
        lambda: {"timeline_id": "private"},
    )
    record = read_json_object(
        next((tmp_path / "workflow").glob("*.json"))
    )

    assert record["operation"] == "apply_synchronized_pause_compaction"
    assert record["category"] == "rough_cut"
    assert "timeline_id" not in str(record)


def test_workflow_audit_rejects_unknown_operation_before_callback(
    tmp_path: Path,
) -> None:
    called = False

    def callback() -> None:
        nonlocal called
        called = True

    with pytest.raises(WorkflowAuditError, match="Unsupported"):
        WorkflowAuditLog(tmp_path, FixedClock()).run(
            "execute_python",
            callback,
        )

    assert called is False
    assert not (tmp_path / "workflow").exists()


def test_workflow_audit_contract_rejects_mismatched_category(
    tmp_path: Path,
) -> None:
    audit = WorkflowAuditLog(tmp_path, FixedClock())
    audit.run("list_audio_reports", lambda: None)
    record = read_json_object(
        next((tmp_path / "workflow").glob("*.json"))
    )
    record["category"] = "rough_cut"

    with pytest.raises(ContractValidationError, match="category"):
        validate_contract("workflow-audit-record", record)
