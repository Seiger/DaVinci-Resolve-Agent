"""One-shot read-only bridge executed inside DaVinci Resolve."""

from __future__ import annotations

import importlib
import json
import os
from collections.abc import Mapping
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

BRIDGE_VERSION = "0.1.0"
PROTOCOL_VERSION = "1.0"
APPLICATION_DIRECTORY_NAME = "DaVinciResolveAgent"
ALLOWED_ACTIONS = {
    "ping",
    "get_bridge_info",
    "get_capabilities",
    "get_current_project",
    "list_timelines",
    "get_current_timeline",
}


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
    current_timeline_name: str | None = None
    timelines: list[dict[str, Any]] = []
    timeline_read_capability: bool | str = "unknown"

    if project is not None:
        project_name = project.GetName()
        timeline_count = int(project.GetTimelineCount())
        for index in range(1, timeline_count + 1):
            timeline = project.GetTimelineByIndex(index)
            if timeline is not None:
                timelines.append({"index": index, "name": timeline.GetName()})
        current_timeline = project.GetCurrentTimeline()
        if current_timeline is not None:
            current_timeline_name = current_timeline.GetName()
        timeline_read_capability = True

    capabilities: dict[str, bool | str] = {
        "bridge.ping": True,
        "project.read": True,
        "timeline.read": timeline_read_capability,
        "timeline.create": "unknown",
        "media.import": "unknown",
        "clip.insert": "unknown",
        "marker.create": "unknown",
        "render.configure": "unknown",
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
    """Validate the minimal M1 command envelope and allowlist."""
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
        raise ValueError("M1 bridge only accepts provider 'resolve'.")
    if command["action"] not in ALLOWED_ACTIONS:
        raise ValueError("Unsupported or unsafe bridge action.")
    if command.get("arguments") != {}:
        raise ValueError("M1 read-only actions do not accept arguments.")
    if not isinstance(command.get("safety"), dict):
        raise ValueError("safety must be a JSON object.")
    if set(command["safety"]) != {"allow_destructive", "create_backup"}:
        raise ValueError("safety fields do not match the protocol contract.")
    if command["safety"].get("allow_destructive") is not False:
        raise ValueError("M1 commands must set allow_destructive to false.")
    if not isinstance(command["safety"].get("create_backup"), bool):
        raise ValueError("safety.create_backup must be a boolean.")

    _parse_timestamp(command["created_at"], "created_at")
    expires_at = _parse_timestamp(command["expires_at"], "expires_at")
    if expires_at <= datetime.now(timezone.utc):
        raise ValueError("Command has expired.")
    return command


def command_result(action: str, state: dict[str, Any]) -> Any:
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
        name = state["current_timeline_name"]
        return None if name is None else {"name": name}
    raise ValueError("Unsupported or unsafe bridge action.")


def process_command_file(
    processing_path: Path,
    response_path: Path,
    failed_path: Path,
    state: dict[str, Any],
) -> None:
    """Process one claimed command and write a structured response."""
    started_at = utc_now()
    command_id = processing_path.stem
    try:
        with processing_path.open("r", encoding="utf-8") as command_file:
            command = validate_command(json.load(command_file))
        command_id = command["command_id"]
        result = command_result(command["action"], state)
        response = {
            "protocol_version": PROTOCOL_VERSION,
            "command_id": command_id,
            "status": "success",
            "started_at": started_at,
            "finished_at": utc_now(),
            "result": result,
            "error": None,
            "warnings": [],
        }
        atomic_write_json(response_path, response)
        processing_path.unlink()
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
        atomic_write_json(state_path, state)
        processed = process_pending_commands(directories, state)
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
