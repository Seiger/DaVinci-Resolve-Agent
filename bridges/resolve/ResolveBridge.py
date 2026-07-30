"""One-shot allowlisted bridge executed inside DaVinci Resolve."""

from __future__ import annotations

import hashlib
import importlib
import json
import os
import re
from collections.abc import Mapping
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, cast

BRIDGE_VERSION = "0.1.0"
PROTOCOL_VERSION = "1.0"
APPLICATION_DIRECTORY_NAME = "DaVinciResolveAgent"
DEFAULT_RENDER_PROFILE = "youtube-1080p-h264-v1"
RENDER_PROFILES = {
    "youtube-1080p-h264-v1": {
        "resolve_preset": "YouTube - 1080p",
        "width": 1920,
        "height": 1080,
    },
    "youtube-2160p-h264-v1": {
        "resolve_preset": "YouTube - 2160p",
        "width": 3840,
        "height": 2160,
    },
}
ALLOWED_ACTIONS = {
    "ping",
    "get_bridge_info",
    "get_capabilities",
    "get_current_project",
    "list_timelines",
    "get_current_timeline",
    "get_render_environment",
    "get_render_job_status",
    "import_media",
    "create_timeline",
    "set_current_timeline",
    "append_clip",
    "insert_clip",
    "set_clip_enabled",
    "add_marker",
    "prepare_render_job",
    "start_render_job",
}
WRITE_ACTIONS = {
    "import_media",
    "create_timeline",
    "set_current_timeline",
    "append_clip",
    "insert_clip",
    "set_clip_enabled",
    "add_marker",
    "prepare_render_job",
    "start_render_job",
}
CAPABILITY_BY_ACTION = {
    "import_media": "media.import",
    "create_timeline": "timeline.create",
    "set_current_timeline": "timeline.select",
    "append_clip": "clip.insert",
    "insert_clip": "clip.range_insert",
    "set_clip_enabled": "clip.enable",
    "add_marker": "marker.create",
    "prepare_render_job": "render.configure",
    "start_render_job": "render.start",
}


class BridgeOperationError(RuntimeError):
    """A safe error returned for an allowlisted Resolve operation."""

    def __init__(
        self,
        code: str,
        message: str,
        *,
        retryable: bool = False,
        details: dict[str, Any] | None = None,
    ) -> None:
        self.code = code
        self.retryable = retryable
        self.details = {} if details is None else details
        super().__init__(message)


def utc_now() -> str:
    """Return a UTC timestamp suitable for protocol files."""
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def runtime_root(environment: Mapping[str, str] | None = None) -> Path:
    """Resolve the shared runtime root from LOCALAPPDATA."""
    source = os.environ if environment is None else environment
    local_app_data = source.get("LOCALAPPDATA")
    if not local_app_data:
        raise RuntimeError("LOCALAPPDATA is not set inside Resolve.")
    return Path(local_app_data) / APPLICATION_DIRECTORY_NAME / "runtime"


def runtime_directories(root: Path) -> dict[str, Path]:
    """Return the fixed filesystem transport layout."""
    return {
        name: root / name
        for name in (
            "commands",
            "processing",
            "responses",
            "failed",
            "state",
            "logs",
            "backups",
        )
    }


def ensure_runtime_directories(root: Path) -> dict[str, Path]:
    """Create the fixed filesystem transport layout."""
    directories = runtime_directories(root)
    for directory in directories.values():
        directory.mkdir(parents=True, exist_ok=True)
    return directories


def atomic_write_json(path: Path, payload: dict[str, Any]) -> None:
    """Write a JSON object atomically."""
    temporary_path = path.with_name(f"{path.name}.tmp")
    with temporary_path.open("w", encoding="utf-8", newline="\n") as output:
        json.dump(payload, output, ensure_ascii=False, indent=2, sort_keys=True)
        output.write("\n")
        output.flush()
        os.fsync(output.fileno())
    temporary_path.replace(path)


def append_log(log_path: Path, level: str, event: str, **fields: Any) -> None:
    """Append one structured bridge log record."""
    record = {
        "timestamp": utc_now(),
        "level": level,
        "component": "bridge.resolve",
        "event": event,
        **fields,
    }
    with log_path.open("a", encoding="utf-8", newline="\n") as log_file:
        log_file.write(json.dumps(record, ensure_ascii=False, sort_keys=True))
        log_file.write("\n")


def _is_resolve_application(candidate: Any) -> bool:
    return candidate is not None and callable(
        getattr(candidate, "GetProjectManager", None)
    )


def get_resolve_application(context: Mapping[str, Any] | None = None) -> Any:
    """Return Resolve from the internal host context or documented module."""
    internal_context = globals() if context is None else context

    for name in ("resolve", "app"):
        candidate = internal_context.get(name)
        if _is_resolve_application(candidate):
            return candidate

    for name in ("app", "fusion", "fu"):
        host = internal_context.get(name)
        get_resolve = getattr(host, "GetResolve", None)
        if callable(get_resolve):
            candidate = get_resolve()
            if _is_resolve_application(candidate):
                return candidate

    try:
        scripting_module = importlib.import_module("DaVinciResolveScript")
    except ModuleNotFoundError as error:
        available = [
            name
            for name in ("resolve", "app", "fusion", "fu")
            if internal_context.get(name) is not None
        ]
        context_names = ", ".join(available) if available else "none"
        raise RuntimeError(
            "Resolve context was unavailable. "
            f"Detected internal context objects: {context_names}."
        ) from error

    candidate = scripting_module.scriptapp("Resolve")
    if not _is_resolve_application(candidate):
        message = "DaVinciResolveScript.scriptapp('Resolve') returned no object."
        raise RuntimeError(message)
    return candidate


def collect_bridge_state(
    resolve: Any,
    *,
    heartbeat: str | None = None,
) -> dict[str, Any]:
    """Collect only documented read-only Resolve information."""
    product_name = resolve.GetProductName()
    resolve_version = resolve.GetVersionString()
    version_fields = resolve.GetVersion()
    project_manager = resolve.GetProjectManager()
    if project_manager is None:
        raise RuntimeError("Resolve.GetProjectManager() returned no object.")

    project = project_manager.GetCurrentProject()
    project_name: str | None = None
    current_timeline_id: str | None = None
    current_timeline_name: str | None = None
    timelines: list[dict[str, Any]] = []
    timeline_read_capability: bool | str = "unknown"

    if project is not None:
        project_name = project.GetName()
        timeline_count = int(project.GetTimelineCount())
        for index in range(1, timeline_count + 1):
            timeline = project.GetTimelineByIndex(index)
            if timeline is not None:
                timelines.append(
                    {
                        "timeline_id": str(timeline.GetUniqueId()),
                        "index": index,
                        "name": timeline.GetName(),
                    }
                )
        current_timeline = project.GetCurrentTimeline()
        if current_timeline is not None:
            current_timeline_id = str(current_timeline.GetUniqueId())
            current_timeline_name = current_timeline.GetName()
        timeline_read_capability = True

    capabilities: dict[str, bool | str] = {
        "bridge.ping": True,
        "project.read": True,
        "timeline.read": timeline_read_capability,
        "timeline.create": "unknown",
        "timeline.select": "unknown",
        "media.import": "unknown",
        "clip.insert": "unknown",
        "clip.range_insert": "unknown",
        "clip.enable": "unknown",
        "marker.create": "unknown",
        "render.configure": "unknown",
        "render.discovery": "unknown",
        "render.start": "unknown",
    }
    return {
        "protocol_version": PROTOCOL_VERSION,
        "bridge_version": BRIDGE_VERSION,
        "status": "ready",
        "last_heartbeat": heartbeat or utc_now(),
        "provider": "resolve",
        "product_name": product_name,
        "resolve_version": resolve_version,
        "resolve_version_fields": version_fields,
        "edition": "unknown",
        "project_open": project is not None,
        "project_name": project_name,
        "current_timeline_id": current_timeline_id,
        "current_timeline_name": current_timeline_name,
        "timelines": timelines,
        "capabilities": capabilities,
        "error": None,
    }


def _parse_timestamp(value: Any, field_name: str) -> datetime:
    if not isinstance(value, str):
        raise ValueError(f"{field_name} must be an ISO-8601 string.")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as error:
        raise ValueError(f"{field_name} must be a valid ISO-8601 string.") from error
    if parsed.tzinfo is None:
        raise ValueError(f"{field_name} must include a timezone.")
    return parsed


def validate_command(command: Any) -> dict[str, Any]:
    """Validate the fixed command envelope and action-specific arguments."""
    if not isinstance(command, dict):
        raise ValueError("Command must be a JSON object.")

    expected_fields = {
        "protocol_version",
        "command_id",
        "idempotency_key",
        "created_at",
        "expires_at",
        "provider",
        "action",
        "arguments",
        "safety",
    }
    if set(command) != expected_fields:
        raise ValueError("Command fields do not match the protocol contract.")

    required_string_fields = (
        "command_id",
        "idempotency_key",
        "created_at",
        "expires_at",
        "provider",
        "action",
    )
    for field in required_string_fields:
        if not isinstance(command.get(field), str) or not command[field]:
            raise ValueError(f"{field} must be a non-empty string.")
    if command.get("protocol_version") != PROTOCOL_VERSION:
        raise ValueError("Unsupported protocol_version.")
    if command["provider"] != "resolve":
        raise ValueError("ResolveBridge only accepts provider 'resolve'.")
    if command["action"] not in ALLOWED_ACTIONS:
        raise ValueError("Unsupported or unsafe bridge action.")
    if not isinstance(command.get("arguments"), dict):
        raise ValueError("arguments must be a JSON object.")
    if not isinstance(command.get("safety"), dict):
        raise ValueError("safety must be a JSON object.")
    if set(command["safety"]) != {"allow_destructive", "create_backup"}:
        raise ValueError("safety fields do not match the protocol contract.")
    if command["safety"].get("allow_destructive") is not False:
        raise ValueError("Commands must set allow_destructive to false.")
    if not isinstance(command["safety"].get("create_backup"), bool):
        raise ValueError("safety.create_backup must be a boolean.")
    if command["action"] in WRITE_ACTIONS:
        if command["safety"]["create_backup"] is not True:
            raise ValueError("Write commands must request a project backup.")
        _validate_write_arguments(command["action"], command["arguments"])
    elif command["action"] == "get_render_job_status":
        _validate_render_job_arguments(
            command["action"],
            command["arguments"],
        )
    elif command["arguments"] != {}:
        raise ValueError("This read-only action does not accept arguments.")

    _parse_timestamp(command["created_at"], "created_at")
    expires_at = _parse_timestamp(command["expires_at"], "expires_at")
    if expires_at <= datetime.now(timezone.utc):
        raise ValueError("Command has expired.")
    return command


def _validate_write_arguments(action: str, arguments: dict[str, Any]) -> None:
    """Validate bridge-side write arguments without trusting the agent."""
    if action == "import_media":
        if set(arguments) != {"paths"}:
            raise ValueError("import_media requires only paths.")
        paths = arguments["paths"]
        if not isinstance(paths, list) or not 1 <= len(paths) <= 100:
            raise ValueError("paths must contain between 1 and 100 items.")
        if not all(isinstance(path, str) and path for path in paths):
            raise ValueError("Every media path must be a non-empty string.")
        return
    if action == "create_timeline":
        if set(arguments) != {"name"}:
            raise ValueError("create_timeline requires only name.")
        name = arguments["name"]
        if not isinstance(name, str) or not name.strip() or len(name) > 128:
            raise ValueError("Timeline name must contain 1 to 128 characters.")
        return
    if action == "set_current_timeline":
        if set(arguments) != {"timeline_id"}:
            raise ValueError(
                "set_current_timeline requires only timeline_id."
            )
        timeline_id = arguments["timeline_id"]
        if (
            not isinstance(timeline_id, str)
            or not timeline_id
            or len(timeline_id) > 128
        ):
            raise ValueError(
                "timeline_id must contain 1 to 128 characters."
            )
        return
    if action == "append_clip":
        if set(arguments) != {"timeline_id", "asset_id"}:
            raise ValueError("append_clip requires timeline_id and asset_id.")
        for field in ("timeline_id", "asset_id"):
            if not isinstance(arguments[field], str) or not arguments[field]:
                raise ValueError(f"{field} must be a non-empty string.")
        return
    if action == "insert_clip":
        expected = {
            "timeline_id",
            "asset_id",
            "source_start_frame",
            "source_end_frame",
            "position_frames",
            "track_type",
            "track_index",
        }
        if set(arguments) != expected:
            raise ValueError("insert_clip fields do not match the contract.")
        for field in ("timeline_id", "asset_id"):
            if not isinstance(arguments[field], str) or not arguments[field]:
                raise ValueError(f"{field} must be a non-empty string.")
        source_start = arguments["source_start_frame"]
        source_end = arguments["source_end_frame"]
        position = arguments["position_frames"]
        track_index = arguments["track_index"]
        if (
            not isinstance(source_start, int)
            or isinstance(source_start, bool)
            or not isinstance(source_end, int)
            or isinstance(source_end, bool)
            or not 0 <= source_start < source_end <= 2_147_483_647
        ):
            raise ValueError(
                "source frames must be ordered within the supported range."
            )
        if (
            not isinstance(position, int)
            or isinstance(position, bool)
            or not 0 <= position <= 2_147_483_647
        ):
            raise ValueError("position_frames must be a non-negative integer.")
        if arguments["track_type"] not in {"video", "audio"}:
            raise ValueError("track_type must be video or audio.")
        if (
            not isinstance(track_index, int)
            or isinstance(track_index, bool)
            or not 1 <= track_index <= 128
        ):
            raise ValueError("track_index must be between 1 and 128.")
        return
    if action == "set_clip_enabled":
        if set(arguments) != {"timeline_id", "timeline_item_id", "enabled"}:
            raise ValueError(
                "set_clip_enabled fields do not match the contract."
            )
        for field in ("timeline_id", "timeline_item_id"):
            value = arguments[field]
            if (
                not isinstance(value, str)
                or not value
                or len(value) > 128
            ):
                raise ValueError(
                    f"{field} must contain 1 to 128 characters."
                )
        if not isinstance(arguments["enabled"], bool):
            raise ValueError("enabled must be a boolean.")
        return
    if action == "add_marker":
        expected = {
            "timeline_id",
            "frame",
            "color",
            "name",
            "note",
            "duration",
        }
        if set(arguments) != expected:
            raise ValueError("add_marker fields do not match the contract.")
        if not isinstance(arguments["timeline_id"], str) or not arguments[
            "timeline_id"
        ]:
            raise ValueError("timeline_id must be a non-empty string.")
        if (
            not isinstance(arguments["frame"], int)
            or arguments["frame"] < 0
        ):
            raise ValueError("frame must be a non-negative integer.")
        if not isinstance(arguments["color"], str) or not arguments["color"]:
            raise ValueError("color must be a non-empty string.")
        if not isinstance(arguments["name"], str):
            raise ValueError("name must be a string.")
        if not isinstance(arguments["note"], str):
            raise ValueError("note must be a string.")
        if (
            not isinstance(arguments["duration"], int)
            or arguments["duration"] < 1
        ):
            raise ValueError("duration must be a positive integer.")
        return
    if action == "prepare_render_job":
        if set(arguments) not in (
            {"custom_name"},
            {"custom_name", "profile"},
        ):
            raise ValueError(
                "prepare_render_job requires custom_name and optional profile."
            )
        _validate_render_name(arguments["custom_name"])
        _validate_render_profile(
            arguments.get("profile", DEFAULT_RENDER_PROFILE)
        )
        return
    if action == "start_render_job":
        _validate_render_job_arguments(action, arguments)
        return
    raise ValueError("Unsupported write action.")


def _validate_render_name(value: Any) -> str:
    if not isinstance(value, str):
        raise ValueError("custom_name must be a string.")
    normalized = value.strip()
    if not normalized or len(normalized) > 128:
        raise ValueError("custom_name must contain 1 to 128 characters.")
    if normalized in {".", ".."}:
        raise ValueError("custom_name must be a filename stem.")
    forbidden = set('<>:"/\\|?*')
    if any(character in forbidden or ord(character) < 32 for character in normalized):
        raise ValueError("custom_name contains an invalid filename character.")
    if normalized.endswith((".", " ")):
        raise ValueError("custom_name must not end with a dot or space.")
    return normalized


def _validate_render_job_arguments(
    action: str,
    arguments: dict[str, Any],
) -> str:
    if set(arguments) != {"job_id"}:
        raise ValueError(f"{action} requires only job_id.")
    job_id = arguments["job_id"]
    if (
        not isinstance(job_id, str)
        or re.fullmatch(r"[A-Za-z0-9._:-]{1,128}", job_id) is None
    ):
        raise ValueError(
            "job_id must contain 1 to 128 safe identifier characters."
        )
    return job_id


def _validate_render_profile(value: Any) -> dict[str, Any]:
    if not isinstance(value, str) or value not in RENDER_PROFILES:
        raise ValueError(
            "profile must be one of: "
            + ", ".join(sorted(RENDER_PROFILES))
            + "."
        )
    return RENDER_PROFILES[value]


def _render_output_directory() -> Path:
    user_profile = os.environ.get("USERPROFILE")
    if not user_profile:
        raise BridgeOperationError(
            "PATH_CONFIGURATION_ERROR",
            "The USERPROFILE environment variable is not set.",
        )
    output = (
        Path(user_profile)
        / "Videos"
        / APPLICATION_DIRECTORY_NAME
        / "renders"
    ).resolve()
    output.mkdir(parents=True, exist_ok=True)
    return output


def command_result(
    action: str,
    state: dict[str, Any],
    resolve: Any | None = None,
    arguments: dict[str, Any] | None = None,
) -> Any:
    """Return a read-only result from the collected snapshot."""
    if action == "ping":
        return {"message": "pong"}
    if action == "get_bridge_info":
        return {
            key: state[key]
            for key in (
                "bridge_version",
                "protocol_version",
                "product_name",
                "resolve_version",
                "edition",
                "last_heartbeat",
            )
        }
    if action == "get_capabilities":
        return state["capabilities"]
    if action == "get_current_project":
        name = state["project_name"]
        return None if name is None else {"name": name}
    if action == "list_timelines":
        return state["timelines"]
    if action == "get_current_timeline":
        timeline_id = state["current_timeline_id"]
        name = state["current_timeline_name"]
        return (
            None
            if name is None or timeline_id is None
            else {"timeline_id": timeline_id, "name": name}
        )
    if action == "get_render_environment":
        if resolve is None:
            raise BridgeOperationError(
                "RESOLVE_CONTEXT_REQUIRED",
                "A live Resolve context is required for render discovery.",
                retryable=True,
            )
        return _render_environment(resolve)
    if action == "get_render_job_status":
        if resolve is None:
            raise BridgeOperationError(
                "RESOLVE_CONTEXT_REQUIRED",
                "A live Resolve context is required for render status.",
                retryable=True,
            )
        job_id = _validate_render_job_arguments(action, arguments or {})
        return _render_job_status(resolve, job_id)
    raise ValueError("Unsupported or unsafe bridge action.")


def _render_environment(resolve: Any) -> dict[str, Any]:
    project_manager = resolve.GetProjectManager()
    if project_manager is None:
        raise BridgeOperationError(
            "PROJECT_MANAGER_UNAVAILABLE",
            "Resolve.GetProjectManager() returned no object.",
            retryable=True,
        )
    project = project_manager.GetCurrentProject()
    if project is None:
        raise BridgeOperationError(
            "PROJECT_NOT_OPEN",
            "Open a Resolve project before discovering render options.",
            retryable=True,
        )

    required_methods = (
        "GetRenderFormats",
        "GetRenderCodecs",
        "GetRenderResolutions",
        "GetCurrentRenderFormatAndCodec",
        "GetRenderPresetList",
        "GetRenderJobList",
    )
    missing = [
        name
        for name in required_methods
        if not callable(getattr(project, name, None))
    ]
    if missing:
        raise BridgeOperationError(
            "UNSUPPORTED_CAPABILITY",
            "The current Resolve project does not expose render discovery.",
            details={"missing_methods": missing},
        )

    raw_formats = project.GetRenderFormats()
    if not isinstance(raw_formats, Mapping):
        raise BridgeOperationError(
            "INVALID_RESOLVE_RESPONSE",
            "Resolve.GetRenderFormats() returned an invalid value.",
        )
    formats: list[dict[str, Any]] = []
    for format_name, extension in sorted(
        raw_formats.items(),
        key=lambda item: str(item[0]),
    ):
        raw_codecs = project.GetRenderCodecs(str(format_name))
        if not isinstance(raw_codecs, Mapping):
            raise BridgeOperationError(
                "INVALID_RESOLVE_RESPONSE",
                "Resolve.GetRenderCodecs() returned an invalid value.",
                details={"format": str(format_name)},
            )
        formats.append(
            {
                "format": str(format_name),
                "extension": str(extension),
                "codecs": [
                    {
                        "description": str(description),
                        "codec": str(codec),
                    }
                    for description, codec in sorted(
                        raw_codecs.items(),
                        key=lambda item: str(item[0]),
                    )
                ],
            }
        )

    current = project.GetCurrentRenderFormatAndCodec()
    if not isinstance(current, Mapping):
        raise BridgeOperationError(
            "INVALID_RESOLVE_RESPONSE",
            "Resolve.GetCurrentRenderFormatAndCodec() returned an invalid value.",
        )
    presets = project.GetRenderPresetList()
    jobs = project.GetRenderJobList()
    if not isinstance(presets, list) or not isinstance(jobs, list):
        raise BridgeOperationError(
            "INVALID_RESOLVE_RESPONSE",
            "Resolve returned an invalid render preset or job list.",
        )
    raw_resolutions = project.GetRenderResolutions("MP4", "H264")
    if not isinstance(raw_resolutions, list) or not all(
        isinstance(item, Mapping)
        and isinstance(item.get("Width"), int)
        and isinstance(item.get("Height"), int)
        for item in raw_resolutions
    ):
        raise BridgeOperationError(
            "INVALID_RESOLVE_RESPONSE",
            "Resolve.GetRenderResolutions() returned an invalid value.",
            details={"format": "MP4", "codec": "H264"},
        )
    mp4_h264_resolutions = sorted(
        [
            {
                "width": int(item["Width"]),
                "height": int(item["Height"]),
            }
            for item in raw_resolutions
        ],
        key=lambda item: (item["width"], item["height"]),
    )
    timeline = project.GetCurrentTimeline()
    timeline_summary: dict[str, Any] | None = None
    if timeline is not None:
        if not callable(getattr(timeline, "GetTrackCount", None)) or not callable(
            getattr(timeline, "GetItemListInTrack", None)
        ):
            raise BridgeOperationError(
                "UNSUPPORTED_CAPABILITY",
                "The current timeline does not expose documented track inspection.",
                details={
                    "missing_methods": [
                        "GetTrackCount",
                        "GetItemListInTrack",
                    ]
                },
            )
        video_track_count = int(timeline.GetTrackCount("video"))
        audio_track_count = int(timeline.GetTrackCount("audio"))
        timeline_summary = {
            "name": str(timeline.GetName()),
            "video_track_count": video_track_count,
            "audio_track_count": audio_track_count,
            "video_item_count": sum(
                len(timeline.GetItemListInTrack("video", index) or [])
                for index in range(1, video_track_count + 1)
            ),
            "audio_item_count": sum(
                len(timeline.GetItemListInTrack("audio", index) or [])
                for index in range(1, audio_track_count + 1)
            ),
        }
    return {
        "formats": formats,
        "current": {
            "format": _optional_string(current.get("format")),
            "codec": _optional_string(current.get("codec")),
        },
        "presets": _json_safe(presets),
        "jobs": _json_safe(jobs),
        "mp4_h264_resolutions": mp4_h264_resolutions,
        "timeline": timeline_summary,
    }


def _render_job_status(resolve: Any, job_id: str) -> dict[str, Any]:
    project_manager = resolve.GetProjectManager()
    if project_manager is None:
        raise BridgeOperationError(
            "PROJECT_MANAGER_UNAVAILABLE",
            "Resolve.GetProjectManager() returned no object.",
            retryable=True,
        )
    project = project_manager.GetCurrentProject()
    if project is None:
        raise BridgeOperationError(
            "PROJECT_NOT_OPEN",
            "Open a Resolve project before reading render status.",
            retryable=True,
        )
    required_methods = (
        "GetRenderJobList",
        "GetRenderJobStatus",
        "IsRenderingInProgress",
    )
    missing = [
        name
        for name in required_methods
        if not callable(getattr(project, name, None))
    ]
    if missing:
        raise BridgeOperationError(
            "UNSUPPORTED_CAPABILITY",
            "The current Resolve project cannot report render status.",
            details={"missing_methods": missing},
        )
    job = _find_render_job(project, job_id)
    status = project.GetRenderJobStatus(job_id)
    if not isinstance(status, Mapping):
        raise BridgeOperationError(
            "INVALID_RESOLVE_RESPONSE",
            "Resolve.GetRenderJobStatus() returned an invalid value.",
            details={"job_id": job_id},
        )
    return {
        "job_id": job_id,
        "rendering_in_progress": bool(project.IsRenderingInProgress()),
        "status": _json_safe(status),
        "job": _json_safe(job),
    }


def _optional_string(value: Any) -> str | None:
    return None if value is None else str(value)


def _json_safe(value: Any) -> Any:
    if value is None or isinstance(value, (bool, int, float, str)):
        return value
    if isinstance(value, Mapping):
        return {
            str(key): _json_safe(item)
            for key, item in value.items()
        }
    if isinstance(value, (list, tuple)):
        return [_json_safe(item) for item in value]
    return str(value)


def _require_project(resolve: Any) -> tuple[Any, Any, Any]:
    project_manager = resolve.GetProjectManager()
    if project_manager is None:
        raise BridgeOperationError(
            "PROJECT_MANAGER_UNAVAILABLE",
            "Resolve.GetProjectManager() returned no object.",
            retryable=True,
        )
    project = project_manager.GetCurrentProject()
    if project is None:
        raise BridgeOperationError(
            "PROJECT_NOT_OPEN",
            "Open a Resolve project before running this command.",
            retryable=True,
        )
    media_pool = project.GetMediaPool()
    if media_pool is None:
        raise BridgeOperationError(
            "MEDIA_POOL_UNAVAILABLE",
            "The current project returned no MediaPool object.",
            retryable=True,
        )
    return project_manager, project, media_pool


def _safe_backup_stem(project_name: str) -> str:
    normalized = re.sub(r"[^A-Za-z0-9._-]+", "-", project_name).strip("-._")
    return normalized[:80] or "resolve-project"


def _create_project_backup(
    project_manager: Any,
    project: Any,
    backups_directory: Path,
    command_id: str,
) -> str:
    if project_manager.SaveProject() is not True:
        raise BridgeOperationError(
            "PROJECT_SAVE_FAILED",
            "Resolve could not save the current project before modification.",
            retryable=True,
        )
    project_name = str(project.GetName())
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    backup_path = backups_directory / (
        f"{_safe_backup_stem(project_name)}-{timestamp}-"
        f"{_safe_backup_stem(command_id)}.drp"
    )
    exported = project_manager.ExportProject(
        project_name,
        str(backup_path),
        False,
    )
    if exported is not True or not backup_path.is_file():
        raise BridgeOperationError(
            "PROJECT_BACKUP_FAILED",
            "Resolve could not export a project backup; no edit was attempted.",
            retryable=True,
            details={"backup_path": str(backup_path)},
        )
    return str(backup_path)


def _load_media_roots(state_directory: Path) -> tuple[Path, ...]:
    policy_path = state_directory / "media-policy.json"
    try:
        with policy_path.open("r", encoding="utf-8") as policy_file:
            policy = json.load(policy_file)
    except (OSError, json.JSONDecodeError) as error:
        raise BridgeOperationError(
            "MEDIA_POLICY_UNAVAILABLE",
            "Resolved media policy is missing or unreadable.",
            retryable=True,
        ) from error
    if (
        not isinstance(policy, dict)
        or policy.get("policy_version") != "1.0"
        or not isinstance(policy.get("allowed_roots"), list)
        or not policy["allowed_roots"]
    ):
        raise BridgeOperationError(
            "MEDIA_POLICY_INVALID",
            "Resolved media policy does not match version 1.0.",
        )
    roots: list[Path] = []
    for raw_root in policy["allowed_roots"]:
        if not isinstance(raw_root, str):
            raise BridgeOperationError(
                "MEDIA_POLICY_INVALID",
                "Every resolved media root must be a string.",
            )
        root = Path(raw_root)
        if not root.is_absolute():
            raise BridgeOperationError(
                "MEDIA_POLICY_INVALID",
                "Every resolved media root must be absolute.",
            )
        roots.append(root.resolve())
    return tuple(roots)


def _validate_bridge_media_paths(
    raw_paths: list[str],
    state_directory: Path,
) -> list[str]:
    roots = _load_media_roots(state_directory)
    validated: list[str] = []
    for raw_path in raw_paths:
        candidate = Path(raw_path)
        if not candidate.is_absolute():
            raise BridgeOperationError(
                "MEDIA_PATH_NOT_ABSOLUTE",
                f"Media path must be absolute: {raw_path}",
            )
        resolved = candidate.resolve()
        if not resolved.is_file():
            raise BridgeOperationError(
                "MEDIA_FILE_NOT_FOUND",
                f"Media file does not exist: {resolved}",
            )
        if not any(resolved.is_relative_to(root) for root in roots):
            raise BridgeOperationError(
                "MEDIA_PATH_NOT_ALLOWED",
                f"Media path is outside configured allowed roots: {resolved}",
            )
        validated.append(str(resolved))
    return validated


def _find_timeline(project: Any, timeline_id: str) -> Any:
    for index in range(1, int(project.GetTimelineCount()) + 1):
        timeline = project.GetTimelineByIndex(index)
        if timeline is not None and str(timeline.GetUniqueId()) == timeline_id:
            return timeline
    raise BridgeOperationError(
        "TIMELINE_NOT_FOUND",
        f"Resolve timeline was not found: {timeline_id}",
    )


def _find_timeline_item(timeline: Any, timeline_item_id: str) -> Any:
    required_methods = ("GetTrackCount", "GetItemListInTrack")
    missing = [
        name
        for name in required_methods
        if not callable(getattr(timeline, name, None))
    ]
    if missing:
        raise BridgeOperationError(
            "UNSUPPORTED_CAPABILITY",
            "The timeline cannot enumerate video and audio items.",
            details={"missing_methods": missing},
        )
    for track_type in ("video", "audio"):
        track_count = timeline.GetTrackCount(track_type)
        if not isinstance(track_count, int) or track_count < 0:
            raise BridgeOperationError(
                "INVALID_RESOLVE_RESPONSE",
                "Timeline.GetTrackCount() returned an invalid value.",
                details={"track_type": track_type},
            )
        for track_index in range(1, track_count + 1):
            items = timeline.GetItemListInTrack(track_type, track_index)
            if not isinstance(items, list):
                raise BridgeOperationError(
                    "INVALID_RESOLVE_RESPONSE",
                    "Timeline.GetItemListInTrack() returned an invalid value.",
                    details={
                        "track_type": track_type,
                        "track_index": track_index,
                    },
                )
            for item in items:
                get_unique_id = getattr(item, "GetUniqueId", None)
                if callable(get_unique_id) and str(
                    get_unique_id()
                ) == timeline_item_id:
                    return item
    raise BridgeOperationError(
        "TIMELINE_ITEM_NOT_FOUND",
        f"Resolve timeline item was not found: {timeline_item_id}",
    )


def _find_media_item(folder: Any, asset_id: str) -> Any:
    for item in folder.GetClipList() or []:
        if str(item.GetMediaId()) == asset_id:
            return item
    for child in folder.GetSubFolderList() or []:
        found = _find_media_item_or_none(child, asset_id)
        if found is not None:
            return found
    raise BridgeOperationError(
        "MEDIA_ASSET_NOT_FOUND",
        f"Resolve media asset was not found: {asset_id}",
    )


def _find_media_item_or_none(folder: Any, asset_id: str) -> Any:
    try:
        return _find_media_item(folder, asset_id)
    except BridgeOperationError as error:
        if error.code == "MEDIA_ASSET_NOT_FOUND":
            return None
        raise


def _request_fingerprint(command: dict[str, Any]) -> str:
    canonical = json.dumps(
        {
            "provider": command["provider"],
            "action": command["action"],
            "arguments": command["arguments"],
        },
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _receipt_path(state_directory: Path, idempotency_key: str) -> Path:
    key_hash = hashlib.sha256(idempotency_key.encode("utf-8")).hexdigest()
    return state_directory / "receipts" / f"{key_hash}.json"


def _read_receipt(
    command: dict[str, Any],
    state_directory: Path,
) -> dict[str, Any] | None:
    path = _receipt_path(state_directory, command["idempotency_key"])
    if not path.is_file():
        return None
    try:
        with path.open("r", encoding="utf-8") as receipt_file:
            receipt = json.load(receipt_file)
    except (OSError, json.JSONDecodeError) as error:
        raise BridgeOperationError(
            "IDEMPOTENCY_RECEIPT_INVALID",
            "The stored idempotency receipt is unreadable.",
        ) from error
    if (
        not isinstance(receipt, dict)
        or receipt.get("fingerprint") != _request_fingerprint(command)
        or not isinstance(receipt.get("result"), dict)
    ):
        raise BridgeOperationError(
            "IDEMPOTENCY_CONFLICT",
            "The idempotency key was already used for a different command.",
        )
    return cast(dict[str, Any], receipt["result"])


def _write_receipt(
    command: dict[str, Any],
    state_directory: Path,
    result: dict[str, Any],
) -> None:
    path = _receipt_path(state_directory, command["idempotency_key"])
    path.parent.mkdir(parents=True, exist_ok=True)
    atomic_write_json(
        path,
        {
            "idempotency_key": command["idempotency_key"],
            "action": command["action"],
            "fingerprint": _request_fingerprint(command),
            "created_at": utc_now(),
            "result": result,
        },
    )


def _find_render_job(project: Any, job_id: str) -> dict[str, Any]:
    jobs = project.GetRenderJobList()
    if not isinstance(jobs, list):
        raise BridgeOperationError(
            "INVALID_RESOLVE_RESPONSE",
            "Resolve.GetRenderJobList() returned an invalid value.",
        )
    for item in jobs:
        if isinstance(item, Mapping) and str(item.get("JobId", "")) == job_id:
            return {str(key): value for key, value in item.items()}
    raise BridgeOperationError(
        "RENDER_JOB_NOT_FOUND",
        f"Resolve render job was not found: {job_id}",
    )


def _find_prepared_render_result(
    state_directory: Path,
    job_id: str,
) -> dict[str, Any]:
    receipts_directory = state_directory / "receipts"
    for path in receipts_directory.glob("*.json"):
        try:
            with path.open("r", encoding="utf-8") as receipt_file:
                receipt = json.load(receipt_file)
        except (OSError, json.JSONDecodeError):
            continue
        if not isinstance(receipt, dict) or receipt.get("action") != (
            "prepare_render_job"
        ):
            continue
        result = receipt.get("result")
        if isinstance(result, dict) and result.get("job_id") == job_id:
            return cast(dict[str, Any], result)
    raise BridgeOperationError(
        "RENDER_JOB_NOT_AGENT_PREPARED",
        "The render job was not prepared by DaVinci Resolve Agent.",
        details={"job_id": job_id},
    )


def _verify_agent_prepared_render_job(
    project: Any,
    state_directory: Path,
    job_id: str,
) -> tuple[dict[str, Any], dict[str, Any]]:
    prepared = _find_prepared_render_result(state_directory, job_id)
    job = _find_render_job(project, job_id)
    profile_name = prepared.get("preset")
    profile = (
        RENDER_PROFILES.get(profile_name)
        if isinstance(profile_name, str)
        else None
    )
    expected_directory = _render_output_directory()
    expected_name = f"{prepared.get('custom_name', '')}.mp4"
    prepared_directory = Path(str(prepared.get("target_directory", ""))).resolve()
    live_directory = Path(str(job.get("TargetDir", ""))).resolve()
    valid = (
        profile is not None
        and prepared.get("resolve_preset") == profile["resolve_preset"]
        and prepared.get("format") == "MP4"
        and prepared.get("codec") == "H264"
        and prepared.get("started") is False
        and prepared_directory == expected_directory
        and live_directory == expected_directory
        and job.get("PresetName") == profile["resolve_preset"]
        and job.get("VideoFormat") == "MP4"
        and job.get("VideoCodec") in {"H.264", "H264"}
        and job.get("FormatWidth") == profile["width"]
        and job.get("FormatHeight") == profile["height"]
        and job.get("OutputFilename") == expected_name
    )
    if not valid:
        raise BridgeOperationError(
            "RENDER_JOB_POLICY_MISMATCH",
            "The render job no longer matches the fixed safe render policy.",
            details={"job_id": job_id},
        )
    return prepared, job


def _render_start_path(state_directory: Path, job_id: str) -> Path:
    job_hash = hashlib.sha256(job_id.encode("utf-8")).hexdigest()
    return state_directory / "render-starts" / f"{job_hash}.json"


def _reserve_render_start(
    state_directory: Path,
    command: dict[str, Any],
    job_id: str,
) -> Path:
    path = _render_start_path(state_directory, job_id)
    if path.is_file():
        raise BridgeOperationError(
            "RENDER_JOB_ALREADY_STARTED",
            "This agent-prepared render job already has a start record.",
            details={"job_id": job_id},
        )
    path.parent.mkdir(parents=True, exist_ok=True)
    atomic_write_json(
        path,
        {
            "job_id": job_id,
            "command_id": command["command_id"],
            "idempotency_key": command["idempotency_key"],
            "status": "starting",
            "created_at": utc_now(),
        },
    )
    return path


def _verified_capabilities_path(state_directory: Path) -> Path:
    return state_directory / "verified-capabilities.json"


def _record_verified_capability(
    state_directory: Path,
    capability: str,
) -> None:
    path = _verified_capabilities_path(state_directory)
    verified: dict[str, Any] = {}
    if path.is_file():
        try:
            with path.open("r", encoding="utf-8") as capability_file:
                loaded = json.load(capability_file)
            if isinstance(loaded, dict):
                verified = loaded
        except (OSError, json.JSONDecodeError):
            verified = {}
    verified[capability] = True
    atomic_write_json(path, verified)


def _apply_verified_capabilities(
    state: dict[str, Any],
    state_directory: Path,
) -> None:
    path = _verified_capabilities_path(state_directory)
    if not path.is_file():
        return
    try:
        with path.open("r", encoding="utf-8") as capability_file:
            verified = json.load(capability_file)
    except (OSError, json.JSONDecodeError):
        return
    if not isinstance(verified, dict):
        return
    capabilities = state["capabilities"]
    for capability, value in verified.items():
        supported = set(CAPABILITY_BY_ACTION.values()) | {"render.discovery"}
        if capability in supported and value is True:
            capabilities[capability] = True


def _execute_write_command(
    resolve: Any,
    command: dict[str, Any],
    directories: dict[str, Path],
) -> tuple[dict[str, Any], list[str]]:
    receipt = _read_receipt(command, directories["state"])
    if receipt is not None:
        return receipt, ["Returned the stored idempotent result."]

    project_manager, project, media_pool = _require_project(resolve)
    action = command["action"]
    arguments = command["arguments"]

    if action == "import_media":
        arguments = {
            "paths": _validate_bridge_media_paths(
                arguments["paths"],
                directories["state"],
            )
        }
    elif action == "set_current_timeline":
        timeline = _find_timeline(project, arguments["timeline_id"])
        required_project_methods = (
            "GetCurrentTimeline",
            "SetCurrentTimeline",
        )
        missing = [
            name
            for name in required_project_methods
            if not callable(getattr(project, name, None))
        ]
        if missing:
            raise BridgeOperationError(
                "UNSUPPORTED_CAPABILITY",
                "The current project cannot select a timeline.",
                details={"missing_methods": missing},
            )
        previous_timeline = project.GetCurrentTimeline()
    elif action in {
        "append_clip",
        "insert_clip",
        "set_clip_enabled",
        "add_marker",
    }:
        timeline = _find_timeline(project, arguments["timeline_id"])
        if action in {"append_clip", "insert_clip"}:
            root_folder = media_pool.GetRootFolder()
            if root_folder is None:
                raise BridgeOperationError(
                    "MEDIA_POOL_ROOT_UNAVAILABLE",
                    "Resolve MediaPool returned no root folder.",
                    retryable=True,
                )
            media_item = _find_media_item(root_folder, arguments["asset_id"])
        if action == "insert_clip":
            required_timeline_methods = (
                "GetStartFrame",
                "GetTrackCount",
                "GetIsTrackLocked",
            )
            missing = [
                name
                for name in required_timeline_methods
                if not callable(getattr(timeline, name, None))
            ]
            if missing:
                raise BridgeOperationError(
                    "UNSUPPORTED_CAPABILITY",
                    "The timeline cannot validate ranged clip insertion.",
                    details={"missing_methods": missing},
                )
            track_type = arguments["track_type"]
            track_index = arguments["track_index"]
            track_count = timeline.GetTrackCount(track_type)
            if not isinstance(track_count, int) or track_index > track_count:
                raise BridgeOperationError(
                    "TIMELINE_TRACK_NOT_FOUND",
                    "The requested timeline track does not exist.",
                    details={
                        "track_type": track_type,
                        "track_index": track_index,
                    },
                )
            if timeline.GetIsTrackLocked(track_type, track_index) is True:
                raise BridgeOperationError(
                    "TIMELINE_TRACK_LOCKED",
                    "The requested timeline track is locked.",
                    details={
                        "track_type": track_type,
                        "track_index": track_index,
                    },
                )
            timeline_start = timeline.GetStartFrame()
            if not isinstance(timeline_start, int):
                raise BridgeOperationError(
                    "INVALID_RESOLVE_RESPONSE",
                    "Timeline.GetStartFrame() returned an invalid value.",
                )
            record_frame = timeline_start + arguments["position_frames"]
            if record_frame > 2_147_483_647:
                raise BridgeOperationError(
                    "FRAME_RANGE_INVALID",
                    "The requested timeline position exceeds the supported range.",
                )
        elif action == "set_clip_enabled":
            item = _find_timeline_item(
                timeline,
                arguments["timeline_item_id"],
            )
            enable_item_methods = (
                "GetUniqueId",
                "GetName",
                "GetTrackTypeAndIndex",
                "GetClipEnabled",
                "SetClipEnabled",
            )
            missing = [
                name
                for name in enable_item_methods
                if not callable(getattr(item, name, None))
            ]
            if missing:
                raise BridgeOperationError(
                    "UNSUPPORTED_CAPABILITY",
                    "The timeline item cannot change enabled state.",
                    details={"missing_methods": missing},
                )
            actual_track = item.GetTrackTypeAndIndex()
            if (
                not isinstance(actual_track, (list, tuple))
                or len(actual_track) != 2
                or actual_track[0] not in {"video", "audio"}
                or not isinstance(actual_track[1], int)
            ):
                raise BridgeOperationError(
                    "INVALID_RESOLVE_RESPONSE",
                    "TimelineItem track readback is invalid.",
                )
            get_locked = getattr(timeline, "GetIsTrackLocked", None)
            if not callable(get_locked):
                raise BridgeOperationError(
                    "UNSUPPORTED_CAPABILITY",
                    "The timeline cannot report track lock state.",
                    details={"missing_methods": ["GetIsTrackLocked"]},
                )
            if get_locked(actual_track[0], actual_track[1]) is True:
                raise BridgeOperationError(
                    "TIMELINE_TRACK_LOCKED",
                    "The timeline item track is locked.",
                    details={
                        "track_type": actual_track[0],
                        "track_index": actual_track[1],
                    },
                )
            previous_enabled = item.GetClipEnabled()
            if not isinstance(previous_enabled, bool):
                raise BridgeOperationError(
                    "INVALID_RESOLVE_RESPONSE",
                    "TimelineItem.GetClipEnabled() returned an invalid value.",
                )
    elif action == "start_render_job":
        job_id = _validate_render_job_arguments(action, arguments)
        required_methods = (
            "GetRenderJobList",
            "GetRenderJobStatus",
            "IsRenderingInProgress",
            "StartRendering",
        )
        missing = [
            name
            for name in required_methods
            if not callable(getattr(project, name, None))
        ]
        if missing:
            raise BridgeOperationError(
                "UNSUPPORTED_CAPABILITY",
                "The current Resolve project cannot start render jobs.",
                details={"missing_methods": missing},
            )
        _verify_agent_prepared_render_job(
            project,
            directories["state"],
            job_id,
        )
        if _render_start_path(directories["state"], job_id).is_file():
            raise BridgeOperationError(
                "RENDER_JOB_ALREADY_STARTED",
                "This agent-prepared render job already has a start record.",
                details={"job_id": job_id},
            )
        if project.IsRenderingInProgress() is True:
            raise BridgeOperationError(
                "RENDER_ALREADY_IN_PROGRESS",
                "Resolve is already rendering a job.",
                retryable=True,
            )

    backup_path = _create_project_backup(
        project_manager,
        project,
        directories["backups"],
        command["command_id"],
    )

    try:
        result: dict[str, Any]
        if action == "import_media":
            imported = media_pool.ImportMedia(arguments["paths"])
            if not imported:
                raise BridgeOperationError(
                    "MEDIA_IMPORT_FAILED",
                    "Resolve did not import any media items.",
                    retryable=True,
                )
            result = {
                "items": [
                    {
                        "asset_id": str(item.GetMediaId()),
                        "name": str(item.GetName()),
                    }
                    for item in imported
                ],
                "backup_path": backup_path,
            }
        elif action == "create_timeline":
            timeline = media_pool.CreateEmptyTimeline(arguments["name"])
            if timeline is None:
                raise BridgeOperationError(
                    "TIMELINE_CREATE_FAILED",
                    "Resolve did not create the requested timeline.",
                    retryable=True,
                )
            result = {
                "timeline": {
                    "timeline_id": str(timeline.GetUniqueId()),
                    "name": str(timeline.GetName()),
                },
                "backup_path": backup_path,
            }
        elif action == "set_current_timeline":
            if project.SetCurrentTimeline(timeline) is not True:
                raise BridgeOperationError(
                    "TIMELINE_SELECT_FAILED",
                    "Resolve could not select the requested timeline.",
                    retryable=True,
                )
            current_timeline = project.GetCurrentTimeline()
            if (
                current_timeline is None
                or str(current_timeline.GetUniqueId())
                != arguments["timeline_id"]
            ):
                raise BridgeOperationError(
                    "TIMELINE_SELECT_READBACK_FAILED",
                    "Resolve did not report the requested current timeline.",
                    details={"timeline_id": arguments["timeline_id"]},
                )
            result = {
                "timeline": {
                    "timeline_id": str(current_timeline.GetUniqueId()),
                    "name": str(current_timeline.GetName()),
                },
                "previous_timeline": (
                    None
                    if previous_timeline is None
                    else {
                        "timeline_id": str(previous_timeline.GetUniqueId()),
                        "name": str(previous_timeline.GetName()),
                    }
                ),
                "backup_path": backup_path,
            }
        elif action == "append_clip":
            if project.SetCurrentTimeline(timeline) is not True:
                raise BridgeOperationError(
                    "TIMELINE_SELECT_FAILED",
                    "Resolve could not select the requested timeline.",
                    retryable=True,
                )
            appended = media_pool.AppendToTimeline([media_item])
            if not appended:
                raise BridgeOperationError(
                    "CLIP_APPEND_FAILED",
                    "Resolve did not append the requested media item.",
                    retryable=True,
                )
            result = {
                "timeline_id": arguments["timeline_id"],
                "asset_id": arguments["asset_id"],
                "items": [
                    {
                        "timeline_item_id": str(item.GetUniqueId()),
                        "name": str(item.GetName()),
                    }
                    for item in appended
                ],
                "backup_path": backup_path,
            }
        elif action == "insert_clip":
            if project.SetCurrentTimeline(timeline) is not True:
                raise BridgeOperationError(
                    "TIMELINE_SELECT_FAILED",
                    "Resolve could not select the requested timeline.",
                    retryable=True,
                )
            clip_info = {
                "mediaPoolItem": media_item,
                "startFrame": arguments["source_start_frame"],
                "endFrame": arguments["source_end_frame"],
                "mediaType": 1 if arguments["track_type"] == "video" else 2,
                "trackIndex": arguments["track_index"],
                "recordFrame": record_frame,
            }
            inserted = media_pool.AppendToTimeline([clip_info])
            if not inserted or len(inserted) != 1:
                raise BridgeOperationError(
                    "CLIP_INSERT_FAILED",
                    "Resolve did not insert the requested source range.",
                    retryable=True,
                )
            item = inserted[0]
            required_item_methods = (
                "GetUniqueId",
                "GetName",
                "GetStart",
                "GetEnd",
                "GetSourceStartFrame",
                "GetSourceEndFrame",
                "GetTrackTypeAndIndex",
            )
            missing = [
                name
                for name in required_item_methods
                if not callable(getattr(item, name, None))
            ]
            if missing:
                raise BridgeOperationError(
                    "INVALID_RESOLVE_RESPONSE",
                    "The inserted TimelineItem lacks documented readback methods.",
                    details={"missing_methods": missing},
                )
            actual_track = item.GetTrackTypeAndIndex()
            if (
                not isinstance(actual_track, (list, tuple))
                or len(actual_track) != 2
            ):
                raise BridgeOperationError(
                    "INVALID_RESOLVE_RESPONSE",
                    "TimelineItem track readback is invalid.",
                )
            result = {
                "timeline_id": arguments["timeline_id"],
                "asset_id": arguments["asset_id"],
                "item": {
                    "timeline_item_id": str(item.GetUniqueId()),
                    "name": str(item.GetName()),
                    "timeline_start_frame": int(item.GetStart(False)),
                    "timeline_end_frame": int(item.GetEnd(False)),
                    "source_start_frame": int(item.GetSourceStartFrame()),
                    "source_end_frame": int(item.GetSourceEndFrame()),
                    "track_type": str(actual_track[0]),
                    "track_index": int(actual_track[1]),
                },
                "backup_path": backup_path,
            }
        elif action == "set_clip_enabled":
            if project.SetCurrentTimeline(timeline) is not True:
                raise BridgeOperationError(
                    "TIMELINE_SELECT_FAILED",
                    "Resolve could not select the requested timeline.",
                    retryable=True,
                )
            if item.SetClipEnabled(arguments["enabled"]) is not True:
                raise BridgeOperationError(
                    "CLIP_ENABLE_FAILED",
                    "Resolve did not change the timeline item enabled state.",
                    retryable=True,
                )
            actual_enabled = item.GetClipEnabled()
            if (
                not isinstance(actual_enabled, bool)
                or actual_enabled is not arguments["enabled"]
            ):
                raise BridgeOperationError(
                    "CLIP_ENABLE_READBACK_FAILED",
                    "Resolve did not report the requested enabled state.",
                    details={
                        "requested_enabled": arguments["enabled"],
                        "actual_enabled": actual_enabled,
                    },
                )
            result = {
                "timeline_id": arguments["timeline_id"],
                "timeline_item_id": arguments["timeline_item_id"],
                "name": str(item.GetName()),
                "track_type": str(actual_track[0]),
                "track_index": int(actual_track[1]),
                "previous_enabled": previous_enabled,
                "enabled": actual_enabled,
                "backup_path": backup_path,
            }
        elif action == "add_marker":
            custom_data = f"davinci-agent:{command['idempotency_key']}"
            added = timeline.AddMarker(
                arguments["frame"],
                arguments["color"],
                arguments["name"],
                arguments["note"],
                arguments["duration"],
                custom_data,
            )
            if added is not True:
                raise BridgeOperationError(
                    "MARKER_CREATE_FAILED",
                    "Resolve did not create the requested timeline marker.",
                    retryable=True,
                )
            result = {
                "timeline_id": arguments["timeline_id"],
                "frame": arguments["frame"],
                "color": arguments["color"],
                "name": arguments["name"],
                "custom_data": custom_data,
                "backup_path": backup_path,
            }
        elif action == "prepare_render_job":
            custom_name = _validate_render_name(arguments["custom_name"])
            profile_name = arguments.get(
                "profile",
                DEFAULT_RENDER_PROFILE,
            )
            profile = _validate_render_profile(profile_name)
            preset_name = profile["resolve_preset"]
            if not callable(getattr(resolve, "OpenPage", None)) or not callable(
                getattr(resolve, "GetCurrentPage", None)
            ):
                raise BridgeOperationError(
                    "UNSUPPORTED_CAPABILITY",
                    "Resolve does not expose documented page navigation.",
                    details={
                        "missing_methods": ["GetCurrentPage", "OpenPage"],
                    },
                )
            prepare_required_methods = (
                "GetCurrentTimeline",
                "GetRenderPresetList",
                "GetRenderResolutions",
                "LoadRenderPreset",
                "SetCurrentRenderFormatAndCodec",
                "SetCurrentRenderMode",
                "SetRenderSettings",
                "AddRenderJob",
            )
            missing = [
                name
                for name in prepare_required_methods
                if not callable(getattr(project, name, None))
            ]
            if missing:
                raise BridgeOperationError(
                    "UNSUPPORTED_CAPABILITY",
                    "The current Resolve project cannot prepare render jobs.",
                    details={"missing_methods": missing},
                )
            if project.GetCurrentTimeline() is None:
                raise BridgeOperationError(
                    "TIMELINE_NOT_OPEN",
                    "Open a timeline before preparing a render job.",
                    retryable=True,
                )
            previous_page = resolve.GetCurrentPage()
            if resolve.OpenPage("deliver") is not True:
                raise BridgeOperationError(
                    "DELIVER_PAGE_OPEN_FAILED",
                    "Resolve could not open the Deliver page.",
                    retryable=True,
                )
            try:
                presets = project.GetRenderPresetList()
                if not isinstance(presets, list) or preset_name not in presets:
                    raise BridgeOperationError(
                        "RENDER_PRESET_UNAVAILABLE",
                        f"Resolve render preset is unavailable: {preset_name}",
                    )
                resolutions = project.GetRenderResolutions("MP4", "H264")
                expected_resolution = {
                    "Width": profile["width"],
                    "Height": profile["height"],
                }
                if (
                    not isinstance(resolutions, list)
                    or expected_resolution not in resolutions
                ):
                    raise BridgeOperationError(
                        "RENDER_RESOLUTION_UNAVAILABLE",
                        "Resolve does not expose the fixed profile resolution.",
                        details={
                            "profile": profile_name,
                            "width": profile["width"],
                            "height": profile["height"],
                        },
                    )
                if project.LoadRenderPreset(preset_name) is not True:
                    raise BridgeOperationError(
                        "RENDER_PRESET_LOAD_FAILED",
                        f"Resolve could not load render preset: {preset_name}",
                        retryable=True,
                    )
                if (
                    project.SetCurrentRenderFormatAndCodec("MP4", "H264")
                    is not True
                ):
                    raise BridgeOperationError(
                        "RENDER_FORMAT_FAILED",
                        "Resolve could not select MP4/H264 rendering.",
                        retryable=True,
                    )
                if project.SetCurrentRenderMode(1) is not True:
                    raise BridgeOperationError(
                        "RENDER_MODE_FAILED",
                        "Resolve could not select single-clip render mode.",
                        retryable=True,
                    )
                target_directory = _render_output_directory()
                settings = {
                    "SelectAllFrames": True,
                    "TargetDir": str(target_directory),
                    "CustomName": custom_name,
                    "ExportVideo": True,
                    "ExportAudio": True,
                    "FormatWidth": profile["width"],
                    "FormatHeight": profile["height"],
                }
                if project.SetRenderSettings(settings) is not True:
                    raise BridgeOperationError(
                        "RENDER_SETTINGS_FAILED",
                        "Resolve could not apply the fixed render settings.",
                        retryable=True,
                    )
                job_id = project.AddRenderJob()
                if not isinstance(job_id, str) or not job_id:
                    raise BridgeOperationError(
                        "RENDER_JOB_CREATE_FAILED",
                        "Resolve did not add the render job.",
                        retryable=True,
                    )
            finally:
                if (
                    isinstance(previous_page, str)
                    and previous_page
                    and previous_page != "deliver"
                ):
                    resolve.OpenPage(previous_page)
            result = {
                "job_id": job_id,
                "preset": profile_name,
                "resolve_preset": preset_name,
                "format": "MP4",
                "codec": "H264",
                "width": profile["width"],
                "height": profile["height"],
                "target_directory": str(target_directory),
                "custom_name": custom_name,
                "started": False,
                "backup_path": backup_path,
            }
        elif action == "start_render_job":
            job_id = _validate_render_job_arguments(action, arguments)
            start_path = _reserve_render_start(
                directories["state"],
                command,
                job_id,
            )
            if project.StartRendering([job_id], False) is not True:
                raise BridgeOperationError(
                    "RENDER_START_FAILED",
                    "Resolve did not start the requested render job.",
                    retryable=False,
                    details={"job_id": job_id},
                )
            status = _render_job_status(resolve, job_id)
            atomic_write_json(
                start_path,
                {
                    "job_id": job_id,
                    "command_id": command["command_id"],
                    "idempotency_key": command["idempotency_key"],
                    "status": "accepted",
                    "created_at": utc_now(),
                },
            )
            result = {
                "job_id": job_id,
                "started": True,
                "rendering_in_progress": status["rendering_in_progress"],
                "status": status["status"],
                "backup_path": backup_path,
            }
        else:
            raise BridgeOperationError(
                "UNSUPPORTED_WRITE_ACTION",
                f"Unsupported write action: {action}",
            )
    except BridgeOperationError as error:
        error.details.setdefault("backup_path", backup_path)
        raise
    except Exception as error:
        raise BridgeOperationError(
            "RESOLVE_OPERATION_FAILED",
            f"Resolve operation failed: {error}",
            retryable=True,
            details={"backup_path": backup_path},
        ) from error

    _write_receipt(command, directories["state"], result)
    return result, []


def process_command_file(
    processing_path: Path,
    response_path: Path,
    failed_path: Path,
    state: dict[str, Any],
    resolve: Any | None = None,
    directories: dict[str, Path] | None = None,
) -> None:
    """Process one claimed command and write a structured response."""
    started_at = utc_now()
    command_id = processing_path.stem
    try:
        with processing_path.open("r", encoding="utf-8") as command_file:
            command = validate_command(json.load(command_file))
        command_id = command["command_id"]
        warnings: list[str] = []
        if command["action"] in WRITE_ACTIONS:
            if resolve is None or directories is None:
                raise BridgeOperationError(
                    "RESOLVE_CONTEXT_REQUIRED",
                    "A live Resolve context is required for write commands.",
                    retryable=True,
                )
            result, warnings = _execute_write_command(
                resolve,
                command,
                directories,
            )
            capability = CAPABILITY_BY_ACTION[command["action"]]
            state["capabilities"][capability] = True
            _record_verified_capability(directories["state"], capability)
            refreshed_state = collect_bridge_state(resolve)
            _apply_verified_capabilities(
                refreshed_state,
                directories["state"],
            )
            state.clear()
            state.update(refreshed_state)
        else:
            result = command_result(
                command["action"],
                state,
                resolve,
                command["arguments"],
            )
            if (
                command["action"] == "get_render_environment"
                and directories is not None
            ):
                state["capabilities"]["render.discovery"] = True
                _record_verified_capability(
                    directories["state"],
                    "render.discovery",
                )
        response = {
            "protocol_version": PROTOCOL_VERSION,
            "command_id": command_id,
            "status": "success",
            "started_at": started_at,
            "finished_at": utc_now(),
            "result": result,
            "error": None,
            "warnings": warnings,
        }
        atomic_write_json(response_path, response)
        processing_path.unlink()
    except BridgeOperationError as error:
        response = {
            "protocol_version": PROTOCOL_VERSION,
            "command_id": command_id,
            "status": "error",
            "started_at": started_at,
            "finished_at": utc_now(),
            "result": None,
            "error": {
                "code": error.code,
                "message": str(error),
                "details": error.details,
                "retryable": error.retryable,
            },
            "warnings": [],
        }
        atomic_write_json(response_path, response)
        processing_path.replace(failed_path)
    except (OSError, ValueError, json.JSONDecodeError) as error:
        response = {
            "protocol_version": PROTOCOL_VERSION,
            "command_id": command_id,
            "status": "error",
            "started_at": started_at,
            "finished_at": utc_now(),
            "result": None,
            "error": {
                "code": "INVALID_OR_UNSUPPORTED_COMMAND",
                "message": str(error),
                "details": {},
                "retryable": False,
            },
            "warnings": [],
        }
        atomic_write_json(response_path, response)
        processing_path.replace(failed_path)


def process_pending_commands(
    directories: dict[str, Path],
    state: dict[str, Any],
    resolve: Any | None = None,
) -> int:
    """Claim and process every complete command currently in the queue."""
    processed = 0
    for command_path in sorted(directories["commands"].glob("*.json")):
        processing_path = directories["processing"] / command_path.name
        try:
            command_path.replace(processing_path)
        except FileNotFoundError:
            continue
        process_command_file(
            processing_path,
            directories["responses"] / command_path.name,
            directories["failed"] / command_path.name,
            state,
            resolve,
            directories,
        )
        processed += 1
    return processed


def error_state(error: Exception) -> dict[str, Any]:
    """Create a safe, machine-readable bridge failure state."""
    return {
        "protocol_version": PROTOCOL_VERSION,
        "bridge_version": BRIDGE_VERSION,
        "status": "error",
        "last_heartbeat": utc_now(),
        "provider": "resolve",
        "product_name": None,
        "resolve_version": None,
        "resolve_version_fields": [],
        "edition": "unknown",
        "project_open": False,
        "project_name": None,
        "current_timeline_id": None,
        "current_timeline_name": None,
        "timelines": [],
        "capabilities": {
            "bridge.ping": False,
            "project.read": "unknown",
            "timeline.read": "unknown",
        },
        "error": {
            "code": "BRIDGE_INITIALIZATION_FAILED",
            "message": str(error),
            "details": {},
            "retryable": True,
        },
    }


def main() -> int:
    """Execute one safe bridge observation and command-processing pass."""
    root = runtime_root()
    directories = ensure_runtime_directories(root)
    log_path = directories["logs"] / "bridge.jsonl"
    state_path = directories["state"] / "bridge.json"

    try:
        resolve = get_resolve_application()
        state = collect_bridge_state(resolve)
        _apply_verified_capabilities(state, directories["state"])
        atomic_write_json(state_path, state)
        processed = process_pending_commands(directories, state, resolve)
        atomic_write_json(state_path, state)
        append_log(log_path, "INFO", "bridge_run_completed", commands=processed)
        print(
            "DaVinci Resolve Agent bridge ready: "
            f"project={state['project_name']!r}, "
            f"timeline={state['current_timeline_name']!r}, "
            f"commands={processed}"
        )
        return 0
    except Exception as error:
        state = error_state(error)
        atomic_write_json(state_path, state)
        append_log(
            log_path,
            "ERROR",
            "bridge_run_failed",
            error_code=state["error"]["code"],
            message=state["error"]["message"],
        )
        print(f"DaVinci Resolve Agent bridge failed: {error}")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
