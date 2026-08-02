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


def test_workflow_audit_records_compaction_finalize_as_rough_cut(
    tmp_path: Path,
) -> None:
    audit = WorkflowAuditLog(tmp_path, FixedClock())

    audit.run(
        "finalize_synchronized_pause_compaction",
        lambda: {"timeline_id": "private"},
    )
    record = read_json_object(
        next((tmp_path / "workflow").glob("*.json"))
    )

    assert record["operation"] == "finalize_synchronized_pause_compaction"
    assert record["category"] == "rough_cut"
    assert "timeline_id" not in str(record)


def test_workflow_audit_records_finalized_render_as_delivery(
    tmp_path: Path,
) -> None:
    audit = WorkflowAuditLog(tmp_path, FixedClock())

    audit.run(
        "prepare_finalized_timeline_render",
        lambda: {"job_id": "private"},
    )
    record = read_json_object(
        next((tmp_path / "workflow").glob("*.json"))
    )

    assert record["operation"] == "prepare_finalized_timeline_render"
    assert record["category"] == "delivery"
    assert "job_id" not in str(record)


@pytest.mark.parametrize(
    "operation",
    [
        "list_editing_recipes",
        "get_editing_recipe",
        "preview_editing_recipe",
        "run_editing_recipe",
    ],
)
def test_workflow_audit_records_m48_recipe_operations_as_editing(
    tmp_path: Path,
    operation: str,
) -> None:
    audit = WorkflowAuditLog(tmp_path, FixedClock())

    audit.run(operation, lambda: {"receipt_id": "private"})
    record = read_json_object(next((tmp_path / "workflow").glob("*.json")))

    assert record["operation"] == operation
    assert record["category"] == "editing"
    assert "receipt_id" not in str(record)


def test_workflow_audit_records_m55_assembly_preview_as_editing(
    tmp_path: Path,
) -> None:
    audit = WorkflowAuditLog(tmp_path, FixedClock())

    audit.run(
        "preview_take_sequence_assembly",
        lambda: {"plan_id": "private"},
    )
    records = [
        read_json_object(path)
        for path in (tmp_path / "workflow").glob("*.json")
    ]
    completed = [record for record in records if record["status"] == "success"]

    assert completed[0]["operation"] == "preview_take_sequence_assembly"
    assert completed[0]["category"] == "editing"
    assert "plan_id" not in str(completed[0])


def test_workflow_audit_records_m55_timeline_mapping_as_editing(
    tmp_path: Path,
) -> None:
    audit = WorkflowAuditLog(tmp_path, FixedClock())

    audit.run(
        "preview_take_sequence_timeline_mapping",
        lambda: {"plan_id": "private"},
    )
    records = [
        read_json_object(path)
        for path in (tmp_path / "workflow").glob("*.json")
    ]
    completed = [record for record in records if record["status"] == "success"]

    assert completed[0]["operation"] == (
        "preview_take_sequence_timeline_mapping"
    )
    assert completed[0]["category"] == "editing"
    assert "plan_id" not in str(completed[0])


@pytest.mark.parametrize(
    "operation",
    [
        "preview_take_sequence_media_import",
        "apply_take_sequence_media_import",
        "get_take_sequence_media_import",
    ],
)
def test_workflow_audit_records_m55_media_import_as_editing(
    tmp_path: Path,
    operation: str,
) -> None:
    audit = WorkflowAuditLog(tmp_path, FixedClock())

    audit.run(
        operation,
        lambda: {"plan_id": "private"},
    )
    records = [
        read_json_object(path)
        for path in (tmp_path / "workflow").glob("*.json")
    ]
    completed = [record for record in records if record["status"] == "success"]

    assert completed[0]["operation"] == operation
    assert completed[0]["category"] == "editing"
    assert "plan_id" not in str(completed[0])


@pytest.mark.parametrize(
    "operation",
    [
        "start_finalized_timeline_render",
        "get_finalized_timeline_render_status",
    ],
)
def test_workflow_audit_records_m45_as_delivery(
    tmp_path: Path,
    operation: str,
) -> None:
    audit = WorkflowAuditLog(tmp_path, FixedClock())

    audit.run(operation, lambda: {"job_id": "private"})
    records = list((tmp_path / "workflow").glob("*.json"))
    completed = [
        read_json_object(path)
        for path in records
        if read_json_object(path)["status"] == "success"
    ]

    assert completed[0]["operation"] == operation
    assert completed[0]["category"] == "delivery"
    assert "job_id" not in str(completed[0])


@pytest.mark.parametrize(
    "operation",
    [
        "prepare_finalized_timeline_audio",
        "start_finalized_timeline_audio",
        "get_finalized_timeline_audio_status",
    ],
)
def test_workflow_audit_records_m46_extraction_as_audio(
    tmp_path: Path,
    operation: str,
) -> None:
    audit = WorkflowAuditLog(tmp_path, FixedClock())

    audit.run(operation, lambda: {"job_id": "private"})
    records = list((tmp_path / "workflow").glob("*.json"))
    completed = [
        read_json_object(path)
        for path in records
        if read_json_object(path)["status"] == "success"
    ]

    assert completed[0]["operation"] == operation
    assert completed[0]["category"] == "audio"
    assert "job_id" not in str(completed[0])


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
