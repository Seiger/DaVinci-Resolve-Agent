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
