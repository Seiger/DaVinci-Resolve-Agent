"""Provider-neutral structured command audit records."""

from __future__ import annotations

import re
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Literal

from agent.contracts import ContractValidationError, validate_contract
from agent.paths import logs_directory
from transports.filesystem import atomic_write_json_with_retry

AUDIT_VERSION = "1.0"
SAFE_COMMAND_ID_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")
SAFE_ERROR_CODE_PATTERN = re.compile(r"^[A-Z][A-Z0-9_]{0,63}$")

AuditStatus = Literal["submitting", "pending", "success", "error", "timeout"]
AuditEvent = Literal[
    "command_submission_started",
    "command_submitted",
    "command_completed",
    "command_failed",
    "command_timed_out",
]
AuditLevel = Literal["INFO", "WARNING", "ERROR"]


class AuditLogError(RuntimeError):
    """Raised when a command audit record cannot be handled safely."""


@dataclass
class CommandAuditRecord:
    """One atomically updated command lifecycle record."""

    path: Path
    command_id: str
    provider: str
    action: str
    allow_destructive: bool
    create_backup: bool
    submitted_at: datetime
    clock: Callable[[], datetime]
    _status: AuditStatus = "submitting"

    def mark_submitted(self) -> None:
        """Record that the validated command is present in the queue."""
        self._transition(
            status="pending",
            event="command_submitted",
            level="INFO",
        )

    def mark_success(self) -> None:
        """Record successful response validation."""
        self._transition(
            status="success",
            event="command_completed",
            level="INFO",
        )

    def mark_error(self, error_code: str, *, retryable: bool) -> None:
        """Record a safe error code without response payload or message."""
        if not SAFE_ERROR_CODE_PATTERN.fullmatch(error_code):
            raise AuditLogError(
                "Audit error_code must use uppercase letters, digits, and "
                "underscores only."
            )
        self._transition(
            status="error",
            event="command_failed",
            level="ERROR",
            error_code=error_code,
            retryable=retryable,
        )

    def mark_timeout(self) -> None:
        """Record an external wait timeout."""
        self._transition(
            status="timeout",
            event="command_timed_out",
            level="WARNING",
            error_code="COMMAND_TIMEOUT",
            retryable=True,
        )

    def _transition(
        self,
        *,
        status: AuditStatus,
        event: AuditEvent,
        level: AuditLevel,
        error_code: str | None = None,
        retryable: bool | None = None,
    ) -> None:
        if self._status in {"success", "error", "timeout"}:
            raise AuditLogError(
                "A completed command audit record cannot be changed."
            )
        finished = status in {"success", "error", "timeout"}
        now = _aware_utc(self.clock())
        duration_ms = (
            max(
                0,
                round((now - self.submitted_at).total_seconds() * 1000),
            )
            if finished
            else None
        )
        payload = self._payload(
            timestamp=now,
            status=status,
            event=event,
            level=level,
            finished_at=now if finished else None,
            duration_ms=duration_ms,
            error_code=error_code,
            retryable=retryable,
        )
        _write_record(self.path, payload)
        self._status = status

    def _payload(
        self,
        *,
        timestamp: datetime,
        status: AuditStatus,
        event: AuditEvent,
        level: AuditLevel,
        finished_at: datetime | None,
        duration_ms: int | None,
        error_code: str | None,
        retryable: bool | None,
    ) -> dict[str, Any]:
        return {
            "audit_version": AUDIT_VERSION,
            "timestamp": _isoformat(timestamp),
            "level": level,
            "component": "transport.filesystem",
            "event": event,
            "command_id": self.command_id,
            "provider": self.provider,
            "action": self.action,
            "status": status,
            "submitted_at": _isoformat(self.submitted_at),
            "finished_at": (
                None if finished_at is None else _isoformat(finished_at)
            ),
            "duration_ms": duration_ms,
            "error_code": error_code,
            "retryable": retryable,
            "safety": {
                "allow_destructive": self.allow_destructive,
                "create_backup": self.create_backup,
            },
        }


class CommandAuditLog:
    """Create safe lifecycle records before filesystem commands are queued."""

    def __init__(
        self,
        logs_root: Path | None = None,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        root = logs_directory() if logs_root is None else logs_root
        self._root = root / "audit"
        self._clock: Callable[[], datetime] = (
            (lambda: datetime.now(timezone.utc))
            if clock is None
            else clock
        )

    def start(
        self,
        *,
        command_id: str,
        provider: str,
        action: str,
        allow_destructive: bool,
        create_backup: bool,
    ) -> CommandAuditRecord:
        """Persist the initial record before command publication."""
        if not SAFE_COMMAND_ID_PATTERN.fullmatch(command_id):
            raise AuditLogError(
                "Audit command_id contains unsafe filename characters."
            )
        if self._root.parent.is_symlink() or self._root.is_symlink():
            raise AuditLogError(
                "Managed audit directory must not be a symbolic link."
            )
        try:
            self._root.mkdir(parents=True, exist_ok=True)
        except OSError as error:
            raise AuditLogError(
                f"Audit directory could not be created: {error}"
            ) from error
        if self._root.is_symlink():
            raise AuditLogError(
                "Managed audit directory must not be a symbolic link."
            )

        submitted_at = _aware_utc(self._clock())
        record = CommandAuditRecord(
            path=self._root / f"{command_id}.json",
            command_id=command_id,
            provider=provider,
            action=action,
            allow_destructive=allow_destructive,
            create_backup=create_backup,
            submitted_at=submitted_at,
            clock=self._clock,
        )
        payload = record._payload(
            timestamp=submitted_at,
            status="submitting",
            event="command_submission_started",
            level="INFO",
            finished_at=None,
            duration_ms=None,
            error_code=None,
            retryable=None,
        )
        _write_record(record.path, payload)
        return record


def _write_record(path: Path, payload: dict[str, Any]) -> None:
    try:
        validate_contract("audit-record", payload)
        atomic_write_json_with_retry(path, payload)
    except (OSError, ContractValidationError) as error:
        raise AuditLogError(
            f"Command audit record could not be written: {error}"
        ) from error


def _aware_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        raise AuditLogError("Audit timestamps must include a timezone.")
    return value.astimezone(timezone.utc)


def _isoformat(value: datetime) -> str:
    return value.isoformat().replace("+00:00", "Z")
