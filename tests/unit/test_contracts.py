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


def test_valid_subtitle_generation_receipt_contract() -> None:
    validate_contract(
        "subtitle-generation",
        {
            "receipt_id": "a" * 64,
            "status": "applied",
            "timeline_id": "timeline-1",
            "source_file": "C:/Videos/source.wav",
            "subtitle_file": "C:/Videos/subtitles/result.srt",
            "backend": "faster-whisper",
            "model": "small",
            "language": "uk",
            "segment_count": 1,
            "previous_subtitle_item_count": 0,
            "subtitle_item_count": 1,
            "timeline_item_ids": ["subtitle-1"],
            "import_result": {"items": [{"asset_id": "asset-1"}]},
            "append_result": {"items": [{"timeline_item_id": "subtitle-1"}]},
        },
    )


def test_valid_rough_cut_approval_contract() -> None:
    validate_contract(
        "rough-cut-approval",
        {
            "approval_version": "1.0",
            "plan_id": "a" * 64,
            "plan_sha256": "b" * 64,
            "approved_at": datetime.now(timezone.utc).isoformat(),
            "status": "approved",
            "confirm_review": True,
            "apply_supported": False,
        },
    )


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


def test_set_current_timeline_requires_one_bounded_id_and_backup() -> None:
    command = _valid_command()
    command["action"] = "set_current_timeline"
    command["arguments"] = {"timeline_id": "timeline-1"}
    command["safety"] = {
        "allow_destructive": False,
        "create_backup": True,
    }
    validate_contract("command", command)

    command["arguments"] = {"timeline_id": ""}
    with pytest.raises(ContractValidationError, match="timeline_id"):
        validate_contract("command", command)


def test_duplicate_timeline_requires_source_id_name_and_backup() -> None:
    command = _valid_command()
    command["action"] = "duplicate_timeline"
    command["arguments"] = {
        "timeline_id": "timeline-1",
        "name": "Agent Draft",
    }
    command["safety"] = {
        "allow_destructive": False,
        "create_backup": True,
    }
    validate_contract("command", command)

    command["arguments"] = {"timeline_id": "timeline-1"}
    with pytest.raises(ContractValidationError, match="arguments"):
        validate_contract("command", command)


def test_ensure_timeline_tracks_requires_bounded_counts_and_backup() -> None:
    command = _valid_command()
    command["action"] = "ensure_timeline_tracks"
    command["arguments"] = {
        "timeline_id": "timeline-1",
        "video_track_count": 2,
        "audio_track_count": 1,
    }
    command["safety"] = {
        "allow_destructive": False,
        "create_backup": True,
    }
    validate_contract("command", command)

    command["arguments"] = {
        "timeline_id": "timeline-1",
        "video_track_count": 9,
        "audio_track_count": 1,
    }
    with pytest.raises(ContractValidationError, match="video_track_count"):
        validate_contract("command", command)

    command["arguments"] = {
        "timeline_id": "timeline-1",
        "video_track_count": 2,
        "audio_track_count": 1,
    }
    command["safety"] = {
        "allow_destructive": False,
        "create_backup": False,
    }
    with pytest.raises(ContractValidationError, match="create_backup"):
        validate_contract("command", command)


def test_list_timeline_items_requires_one_timeline_id() -> None:
    command = _valid_command()
    command["action"] = "list_timeline_items"
    command["arguments"] = {"timeline_id": "timeline-1"}
    validate_contract("command", command)

    command["arguments"] = {"timeline_id": "", "track_type": "video"}
    with pytest.raises(ContractValidationError, match="arguments"):
        validate_contract("command", command)


def test_list_media_pool_items_accepts_no_arguments() -> None:
    command = _valid_command()
    command["action"] = "list_media_pool_items"
    validate_contract("command", command)

    command["arguments"] = {"property_name": "File Path"}
    with pytest.raises(ContractValidationError, match="arguments"):
        validate_contract("command", command)


def test_workspace_snapshot_accepts_no_arguments() -> None:
    command = _valid_command()
    command["action"] = "get_workspace_snapshot"
    validate_contract("command", command)

    command["arguments"] = {"actions": ["execute_python"]}
    with pytest.raises(ContractValidationError, match="arguments"):
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
        "timeline_id": "timeline-final",
        "profile": "youtube-2160p-h264-v1",
    }
    validate_contract("command", command)

    command["arguments"] = {
        "custom_name": "M9 Test",
        "profile": "custom-8k",
    }
    with pytest.raises(ContractValidationError, match="profile"):
        validate_contract("command", command)

    command["arguments"] = {
        "custom_name": "M44 Final",
        "timeline_id": "",
    }
    with pytest.raises(ContractValidationError, match="timeline_id"):
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


def test_insert_clips_requires_bounded_placement_batch_and_backup() -> None:
    command = _valid_command()
    command["action"] = "insert_clips"
    command["arguments"] = {
        "timeline_id": "timeline-1",
        "placements": [
            {
                "asset_id": "asset-1",
                "source_start_frame": 10,
                "source_end_frame": 240,
                "position_frames": 0,
                "track_type": "video",
                "track_index": 1,
            }
        ],
    }
    command["safety"] = {
        "allow_destructive": False,
        "create_backup": True,
    }
    validate_contract("command", command)

    arguments = command["arguments"]
    assert isinstance(arguments, dict)
    arguments["placements"] = []
    with pytest.raises(ContractValidationError, match="placements"):
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


def test_set_clips_linked_requires_unique_bounded_ids_and_backup() -> None:
    command = _valid_command()
    command["action"] = "set_clips_linked"
    command["arguments"] = {
        "timeline_id": "timeline-1",
        "timeline_item_ids": ["video-1", "audio-1"],
        "linked": True,
    }
    command["safety"] = {
        "allow_destructive": False,
        "create_backup": True,
    }
    validate_contract("command", command)

    command["arguments"] = {
        "timeline_id": "timeline-1",
        "timeline_item_ids": ["video-1", "video-1"],
        "linked": True,
    }
    with pytest.raises(ContractValidationError, match="timeline_item_ids"):
        validate_contract("command", command)


def test_set_clip_transform_requires_allowlisted_bounded_values() -> None:
    command = _valid_command()
    command["action"] = "set_clip_transform"
    command["arguments"] = {
        "timeline_id": "timeline-1",
        "timeline_item_id": "item-1",
        "position_x": 320.0,
        "zoom": 0.5,
        "opacity_percent": 80.0,
    }
    command["safety"] = {
        "allow_destructive": False,
        "create_backup": True,
    }
    validate_contract("command", command)

    command["arguments"] = {
        "timeline_id": "timeline-1",
        "timeline_item_id": "item-1",
        "property_name": "Pan",
    }
    with pytest.raises(ContractValidationError, match="arguments"):
        validate_contract("command", command)


def test_insert_title_requires_exact_timecode_confirmation_and_backup() -> None:
    command = _valid_command()
    command["action"] = "insert_title"
    command["arguments"] = {
        "timeline_id": "timeline-1",
        "title_name": "Text",
        "timecode": "01:00:05:00",
        "confirm_insert": True,
    }
    command["safety"] = {
        "allow_destructive": False,
        "create_backup": True,
    }
    validate_contract("command", command)

    command["arguments"]["timecode"] = "five seconds"
    with pytest.raises(ContractValidationError, match="timecode"):
        validate_contract("command", command)


def test_batch_link_and_transform_commands_are_bounded() -> None:
    command = _valid_command()
    command["action"] = "set_clip_link_groups"
    command["arguments"] = {
        "timeline_id": "timeline-1",
        "groups": [["video-1", "audio-1"]],
        "linked": True,
    }
    command["safety"] = {
        "allow_destructive": False,
        "create_backup": True,
    }
    validate_contract("command", command)

    command["action"] = "set_clip_transforms"
    command["arguments"] = {
        "timeline_id": "timeline-1",
        "items": [{"timeline_item_id": "webcam-1", "zoom": 0.25}],
    }
    validate_contract("command", command)

    command["arguments"] = {
        "timeline_id": "timeline-1",
        "items": [{"timeline_item_id": "webcam-1", "command": "unsafe"}],
    }
    with pytest.raises(ContractValidationError, match="arguments"):
        validate_contract("command", command)


def test_delete_clip_requires_confirmation_destructive_flag_and_backup() -> None:
    command = _valid_command()
    command["action"] = "delete_clip"
    command["arguments"] = {
        "timeline_id": "timeline-1",
        "timeline_item_id": "item-1",
        "confirm_delete": True,
    }
    command["safety"] = {
        "allow_destructive": True,
        "create_backup": True,
    }
    validate_contract("command", command)

    command["safety"] = {
        "allow_destructive": False,
        "create_backup": True,
    }
    with pytest.raises(ContractValidationError, match="allow_destructive"):
        validate_contract("command", command)

    command["safety"] = {
        "allow_destructive": True,
        "create_backup": True,
    }
    command["arguments"] = {
        "timeline_id": "timeline-1",
        "timeline_item_id": "item-1",
        "confirm_delete": False,
    }
    with pytest.raises(ContractValidationError, match="confirm_delete"):
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
