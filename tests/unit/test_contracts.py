"""Canonical protocol-contract tests."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from agent.contracts import ContractValidationError, validate_contract


def _valid_command() -> dict[str, object]:
    now = datetime.now(timezone.utc)
    return {
        "protocol_version": "1.0",
        "command_id": "command-1",
        "idempotency_key": "command-1",
        "created_at": now.isoformat(),
        "expires_at": (now + timedelta(minutes=1)).isoformat(),
        "provider": "resolve",
        "action": "ping",
        "arguments": {},
        "safety": {
            "allow_destructive": False,
            "create_backup": False,
        },
    }


def test_valid_command_contract() -> None:
    validate_contract("command", _valid_command())


def test_write_command_requires_backup_and_action_arguments() -> None:
    command = _valid_command()
    command["action"] = "create_timeline"
    command["arguments"] = {"name": "M4 Timeline"}
    command["safety"] = {
        "allow_destructive": False,
        "create_backup": True,
    }

    validate_contract("command", command)

    command["safety"] = {
        "allow_destructive": False,
        "create_backup": False,
    }
    with pytest.raises(ContractValidationError, match="create_backup"):
        validate_contract("command", command)


def test_unknown_action_violates_command_contract() -> None:
    command = _valid_command()
    command["action"] = "execute_python"

    with pytest.raises(ContractValidationError, match="action"):
        validate_contract("command", command)


def test_prepare_render_job_requires_backup_and_safe_arguments() -> None:
    command = _valid_command()
    command["action"] = "prepare_render_job"
    command["arguments"] = {"custom_name": "M7 Test"}
    command["safety"] = {
        "allow_destructive": False,
        "create_backup": True,
    }

    validate_contract("command", command)

    command["arguments"] = {
        "custom_name": "M9 4K Test",
        "profile": "youtube-2160p-h264-v1",
    }
    validate_contract("command", command)

    command["arguments"] = {
        "custom_name": "M9 Test",
        "profile": "custom-8k",
    }
    with pytest.raises(ContractValidationError, match="profile"):
        validate_contract("command", command)

    command["arguments"] = {"custom_name": ""}
    with pytest.raises(ContractValidationError, match="custom_name"):
        validate_contract("command", command)


def test_render_start_and_status_require_safe_job_id() -> None:
    command = _valid_command()
    command["action"] = "get_render_job_status"
    command["arguments"] = {"job_id": "job-1"}
    validate_contract("command", command)

    command["action"] = "start_render_job"
    command["safety"] = {
        "allow_destructive": False,
        "create_backup": True,
    }
    validate_contract("command", command)

    command["arguments"] = {"job_id": "../job"}
    with pytest.raises(ContractValidationError, match="job_id"):
        validate_contract("command", command)


def test_insert_clip_requires_bounded_track_and_frame_arguments() -> None:
    command = _valid_command()
    command["action"] = "insert_clip"
    command["arguments"] = {
        "timeline_id": "timeline-1",
        "asset_id": "asset-1",
        "source_start_frame": 0,
        "source_end_frame": 240,
        "position_frames": 0,
        "track_type": "video",
        "track_index": 1,
    }
    command["safety"] = {
        "allow_destructive": False,
        "create_backup": True,
    }
    validate_contract("command", command)

    command["arguments"] = {
        "timeline_id": "timeline-1",
        "asset_id": "asset-1",
        "source_start_frame": 0,
        "source_end_frame": 240,
        "position_frames": 0,
        "track_type": "subtitle",
        "track_index": 1,
    }
    with pytest.raises(ContractValidationError, match="track_type"):
        validate_contract("command", command)


def test_set_clip_enabled_requires_ids_boolean_and_backup() -> None:
    command = _valid_command()
    command["action"] = "set_clip_enabled"
    command["arguments"] = {
        "timeline_id": "timeline-1",
        "timeline_item_id": "item-1",
        "enabled": False,
    }
    command["safety"] = {
        "allow_destructive": False,
        "create_backup": True,
    }
    validate_contract("command", command)

    command["arguments"] = {
        "timeline_id": "timeline-1",
        "timeline_item_id": "item-1",
        "enabled": "false",
    }
    with pytest.raises(ContractValidationError, match="enabled"):
        validate_contract("command", command)


def test_success_response_cannot_contain_an_error() -> None:
    response = {
        "protocol_version": "1.0",
        "command_id": "command-1",
        "status": "success",
        "started_at": "2026-07-30T12:00:00Z",
        "finished_at": "2026-07-30T12:00:01Z",
        "result": {"message": "pong"},
        "error": {
            "code": "IMPOSSIBLE",
            "message": "Should not be present",
            "details": {},
            "retryable": False,
        },
        "warnings": [],
    }

    with pytest.raises(ContractValidationError, match="error"):
        validate_contract("response", response)
