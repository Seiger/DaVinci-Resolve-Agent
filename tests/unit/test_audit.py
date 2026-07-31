"""Provider-neutral structured command audit tests."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from agent.audit import AuditLogError, CommandAuditLog
from agent.contracts import validate_contract
from transports.filesystem import read_json_object


class FixedClock:
    def __init__(self) -> None:
        self.current = datetime(2026, 7, 31, 12, 0, tzinfo=timezone.utc)

    def __call__(self) -> datetime:
        value = self.current
        self.current += timedelta(milliseconds=25)
        return value


def test_audit_record_transitions_to_success_without_payloads(
    tmp_path: Path,
) -> None:
    record = CommandAuditLog(tmp_path, FixedClock()).start(
        command_id="command-1",
        provider="resolve",
        action="import_media",
        allow_destructive=False,
        create_backup=True,
    )

    record.mark_submitted()
    record.mark_success()
    payload = read_json_object(record.path)

    validate_contract("audit-record", payload)
    assert payload["status"] == "success"
    assert payload["event"] == "command_completed"
    assert payload["duration_ms"] == 50
    assert payload["safety"]["create_backup"] is True
    assert "arguments" not in payload
    assert "idempotency_key" not in payload
    assert "result" not in payload


def test_audit_record_stores_only_safe_error_fields(tmp_path: Path) -> None:
    record = CommandAuditLog(tmp_path, FixedClock()).start(
        command_id="command-2",
        provider="resolve",
        action="ping",
        allow_destructive=False,
        create_backup=False,
    )

    record.mark_submitted()
    record.mark_error("UNSUPPORTED_CAPABILITY", retryable=False)
    payload = read_json_object(record.path)

    assert payload["status"] == "error"
    assert payload["error_code"] == "UNSUPPORTED_CAPABILITY"
    assert payload["retryable"] is False
    assert "message" not in payload


def test_audit_record_rejects_unsafe_id_and_terminal_rewrite(
    tmp_path: Path,
) -> None:
    audit = CommandAuditLog(tmp_path, FixedClock())

    with pytest.raises(AuditLogError, match="command_id"):
        audit.start(
            command_id="../command",
            provider="resolve",
            action="ping",
            allow_destructive=False,
            create_backup=False,
        )

    record = audit.start(
        command_id="command-3",
        provider="resolve",
        action="ping",
        allow_destructive=False,
        create_backup=False,
    )
    record.mark_timeout()
    with pytest.raises(AuditLogError, match="completed"):
        record.mark_success()


def test_audit_record_rejects_unsafe_error_code(tmp_path: Path) -> None:
    record = CommandAuditLog(tmp_path, FixedClock()).start(
        command_id="command-4",
        provider="resolve",
        action="ping",
        allow_destructive=False,
        create_backup=False,
    )
    record.mark_submitted()

    with pytest.raises(AuditLogError, match="error_code"):
        record.mark_error(r"C:\private\secret", retryable=False)

    payload = read_json_object(record.path)
    assert payload["status"] == "pending"
    assert "private" not in str(payload)
