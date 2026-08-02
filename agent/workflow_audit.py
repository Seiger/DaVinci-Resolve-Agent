"""Structured audit records for local provider-neutral workflows."""

from __future__ import annotations

from collections.abc import Callable
from contextlib import suppress
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, TypeVar
from uuid import uuid4

from agent.contracts import ContractValidationError, validate_contract
from agent.paths import logs_directory
from transports.filesystem import atomic_write_json_with_retry

WORKFLOW_AUDIT_VERSION = "1.0"
WORKFLOW_CATEGORIES = {
    "create_rough_cut": "rough_cut",
    "approve_rough_cut": "rough_cut",
    "get_rough_cut_plan": "rough_cut",
    "list_rough_cut_plans": "rough_cut",
    "preview_synchronized_pause_compaction": "rough_cut",
    "apply_synchronized_pause_compaction": "rough_cut",
    "finalize_synchronized_pause_compaction": "rough_cut",
    "prepare_finalized_timeline_render": "delivery",
    "start_finalized_timeline_render": "delivery",
    "get_finalized_timeline_render_status": "delivery",
    "prepare_finalized_timeline_audio": "audio",
    "start_finalized_timeline_audio": "audio",
    "get_finalized_timeline_audio_status": "audio",
    "apply_finalized_timeline_audio": "audio",
    "sync_screen_and_webcam": "editing",
    "compose_webcam_picture_in_picture": "editing",
    "link_synchronized_screen_pair": "editing",
    "list_editing_recipes": "editing",
    "get_editing_recipe": "editing",
    "preview_editing_recipe": "editing",
    "run_editing_recipe": "editing",
    "preview_visual_treatment": "editing",
    "apply_visual_treatment": "editing",
    "preview_baseline_edit": "delivery",
    "start_baseline_render": "delivery",
    "get_baseline_render_status": "delivery",
    "preview_broll_plan": "editing",
    "apply_broll_plan": "editing",
    "get_broll_status": "editing",
    "list_animation_templates": "editing",
    "get_animation_template": "editing",
    "preview_animation_template": "editing",
    "apply_animation_template": "editing",
    "list_color_presets": "editing",
    "get_color_preset": "editing",
    "preview_color_treatment": "editing",
    "apply_color_treatment": "editing",
    "analyze_take_candidates": "editing",
    "analyze_scripted_take_candidates": "editing",
    "get_take_selection": "editing",
    "list_take_selections": "editing",
    "review_take_selection": "editing",
    "get_take_selection_review": "editing",
    "compose_take_sequence": "editing",
    "get_take_sequence": "editing",
    "list_take_sequences": "editing",
    "bind_take_sequence_sources": "editing",
    "get_take_sequence_binding": "editing",
    "preview_take_sequence_assembly": "editing",
    "preview_take_sequence_timeline_mapping": "editing",
    "clean_dialogue_audio": "audio",
    "get_audio_report": "audio",
    "list_audio_reports": "audio",
}

ResultT = TypeVar("ResultT")


class WorkflowAuditError(RuntimeError):
    """Raised when local workflow audit cannot be handled safely."""


class WorkflowAuditLog:
    """Audit bounded local workflow execution without recording inputs."""

    def __init__(
        self,
        logs_root: Path | None = None,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        root = logs_directory() if logs_root is None else logs_root
        self._root = root / "workflow"
        self._clock: Callable[[], datetime] = (
            (lambda: datetime.now(timezone.utc))
            if clock is None
            else clock
        )

    def run(
        self,
        operation: str,
        callback: Callable[[], ResultT],
    ) -> ResultT:
        """Run one allowlisted operation with an atomic lifecycle record."""
        category = WORKFLOW_CATEGORIES.get(operation)
        if category is None:
            raise WorkflowAuditError(
                f"Unsupported workflow audit operation: {operation}"
            )
        self._ensure_root()
        operation_id = uuid4().hex
        path = self._root / f"{operation_id}.json"
        started_at = _aware_utc(self._clock())
        self._write(
            path,
            _payload(
                operation_id=operation_id,
                operation=operation,
                category=category,
                timestamp=started_at,
                status="running",
                event="workflow_started",
                level="INFO",
                started_at=started_at,
                finished_at=None,
                duration_ms=None,
                error_code=None,
                retryable=None,
            ),
        )

        try:
            result = callback()
        except Exception as error:
            finished_at = _aware_utc(self._clock())
            error_code, retryable = _classify_error(error)
            with suppress(WorkflowAuditError):
                self._write(
                    path,
                    _payload(
                        operation_id=operation_id,
                        operation=operation,
                        category=category,
                        timestamp=finished_at,
                        status="error",
                        event="workflow_failed",
                        level="ERROR",
                        started_at=started_at,
                        finished_at=finished_at,
                        duration_ms=_duration_ms(
                            started_at,
                            finished_at,
                        ),
                        error_code=error_code,
                        retryable=retryable,
                    ),
                )
            raise

        finished_at = _aware_utc(self._clock())
        with suppress(WorkflowAuditError):
            self._write(
                path,
                _payload(
                    operation_id=operation_id,
                    operation=operation,
                    category=category,
                    timestamp=finished_at,
                    status="success",
                    event="workflow_completed",
                    level="INFO",
                    started_at=started_at,
                    finished_at=finished_at,
                    duration_ms=_duration_ms(started_at, finished_at),
                    error_code=None,
                    retryable=None,
                ),
            )
        return result

    def _ensure_root(self) -> None:
        if self._root.parent.is_symlink() or self._root.is_symlink():
            raise WorkflowAuditError(
                "Managed workflow audit directory must not be a symbolic link."
            )
        try:
            self._root.mkdir(parents=True, exist_ok=True)
        except OSError as error:
            raise WorkflowAuditError(
                f"Workflow audit directory could not be created: {error}"
            ) from error
        if self._root.is_symlink():
            raise WorkflowAuditError(
                "Managed workflow audit directory must not be a symbolic link."
            )

    @staticmethod
    def _write(path: Path, payload: dict[str, Any]) -> None:
        try:
            validate_contract("workflow-audit-record", payload)
            atomic_write_json_with_retry(path, payload)
        except (OSError, ContractValidationError) as error:
            raise WorkflowAuditError(
                f"Workflow audit record could not be written: {error}"
            ) from error


def _payload(
    *,
    operation_id: str,
    operation: str,
    category: str,
    timestamp: datetime,
    status: str,
    event: str,
    level: str,
    started_at: datetime,
    finished_at: datetime | None,
    duration_ms: int | None,
    error_code: str | None,
    retryable: bool | None,
) -> dict[str, Any]:
    return {
        "audit_version": WORKFLOW_AUDIT_VERSION,
        "timestamp": _isoformat(timestamp),
        "level": level,
        "component": "workflow",
        "event": event,
        "operation_id": operation_id,
        "operation": operation,
        "category": category,
        "status": status,
        "started_at": _isoformat(started_at),
        "finished_at": (
            None if finished_at is None else _isoformat(finished_at)
        ),
        "duration_ms": duration_ms,
        "error_code": error_code,
        "retryable": retryable,
    }


def _classify_error(error: Exception) -> tuple[str, bool]:
    if isinstance(error, OSError):
        return "FILESYSTEM_ERROR", True
    if isinstance(error, ValueError):
        return "VALIDATION_ERROR", False
    return "WORKFLOW_ERROR", False


def _duration_ms(started_at: datetime, finished_at: datetime) -> int:
    return max(
        0,
        round((finished_at - started_at).total_seconds() * 1000),
    )


def _aware_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        raise WorkflowAuditError(
            "Workflow audit timestamps must include a timezone."
        )
    return value.astimezone(timezone.utc)


def _isoformat(value: datetime) -> str:
    return value.isoformat().replace("+00:00", "Z")
