"""Read-only access to the latest Resolve bridge state."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from agent.paths import runtime_directory

DEFAULT_HEARTBEAT_MAX_AGE_SECONDS = 120


class BridgeStateError(RuntimeError):
    """Raised when the bridge state cannot be read or validated."""


def bridge_state_file(runtime_root: Path | None = None) -> Path:
    """Return the bridge state file for a runtime root."""
    root = runtime_directory() if runtime_root is None else runtime_root
    return root / "state" / "bridge.json"


def load_bridge_state(runtime_root: Path | None = None) -> dict[str, Any]:
    """Load the latest bridge state from disk."""
    path = bridge_state_file(runtime_root)
    try:
        with path.open("r", encoding="utf-8") as state_file:
            loaded = json.load(state_file)
    except FileNotFoundError as error:
        raise BridgeStateError(
            "Resolve bridge state was not found. Launch "
            "Workspace > Scripts > Edit > ResolveBridge inside Resolve."
        ) from error
    except (OSError, json.JSONDecodeError) as error:
        message = f"Resolve bridge state is unreadable: {error}"
        raise BridgeStateError(message) from error

    if not isinstance(loaded, dict):
        raise BridgeStateError("Resolve bridge state must be a JSON object.")

    required_fields = (
        "bridge_version",
        "protocol_version",
        "status",
        "last_heartbeat",
        "capabilities",
    )
    missing = [field for field in required_fields if field not in loaded]
    if missing:
        raise BridgeStateError(
            f"Resolve bridge state is missing fields: {', '.join(missing)}"
        )
    if not isinstance(loaded["capabilities"], dict):
        raise BridgeStateError("Resolve bridge capabilities must be a JSON object.")

    return loaded


def heartbeat_age_seconds(
    state: dict[str, Any],
    now: datetime | None = None,
) -> float:
    """Return the age of the bridge heartbeat in seconds."""
    raw_heartbeat = state.get("last_heartbeat")
    if not isinstance(raw_heartbeat, str):
        raise BridgeStateError("Resolve bridge heartbeat must be an ISO-8601 string.")

    try:
        heartbeat = datetime.fromisoformat(raw_heartbeat.replace("Z", "+00:00"))
    except ValueError as error:
        raise BridgeStateError(
            "Resolve bridge heartbeat is not a valid ISO-8601 timestamp."
        ) from error

    if heartbeat.tzinfo is None:
        raise BridgeStateError("Resolve bridge heartbeat must include a timezone.")

    current_time = datetime.now(timezone.utc) if now is None else now
    return max(0.0, (current_time - heartbeat).total_seconds())


def bridge_is_healthy(
    state: dict[str, Any],
    *,
    max_age_seconds: int = DEFAULT_HEARTBEAT_MAX_AGE_SECONDS,
    now: datetime | None = None,
) -> bool:
    """Return whether the latest bridge execution is ready and recent."""
    return (
        state.get("status") == "ready"
        and heartbeat_age_seconds(state, now) <= max_age_seconds
    )
