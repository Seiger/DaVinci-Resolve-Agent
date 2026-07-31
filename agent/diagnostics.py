"""Safe local diagnostics bundle generation."""

from __future__ import annotations

import json
import os
import platform
import re
from collections import deque
from collections.abc import Mapping
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from agent import __version__
from agent.bridge_state import (
    BridgeStateError,
    heartbeat_age_seconds,
    load_bridge_state,
)
from agent.configuration import load_config
from agent.contracts import validate_contract
from agent.paths import config_file, runtime_directory
from transports.filesystem import atomic_write_json, read_json_object

BUNDLE_VERSION = "1.0"
MAX_FAILED_COMMANDS = 20
MAX_LOG_FILES = 5
MAX_LOG_LINES = 50
MAX_LOG_BYTES = 131_072
LOG_SUFFIXES = {".json", ".jsonl", ".log", ".txt"}
SENSITIVE_KEY_PARTS = (
    "api_key",
    "apikey",
    "authorization",
    "connection_string",
    "credential",
    "password",
    "passwd",
    "private_key",
    "secret",
    "token",
)
INLINE_SECRET_PATTERN = re.compile(
    r"""(?ix)
    (
        ["']?
        (?:api[_-]?key|authorization|connection[_-]?string|credential|
           password|passwd|private[_-]?key|secret|token)
        ["']?
        \s*[:=]\s*
    )
    (?:"[^"]*"|'[^']*'|[^\s,;]+)
    """
)


class DiagnosticsError(RuntimeError):
    """Raised when a diagnostics bundle cannot be created safely."""


class DiagnosticsBundleBuilder:
    """Collect bounded local diagnostics without Resolve communication."""

    def __init__(
        self,
        runtime_root: Path | None = None,
        local_config_file: Path | None = None,
        environment: Mapping[str, str] | None = None,
    ) -> None:
        self._runtime_root = (
            runtime_directory()
            if runtime_root is None
            else runtime_root
        )
        self._config_file = (
            config_file()
            if local_config_file is None
            else local_config_file
        )
        self._environment = os.environ if environment is None else environment

    def create(self) -> Path:
        """Create one canonical JSON bundle in the managed runtime root."""
        try:
            return self._create()
        except OSError as error:
            raise DiagnosticsError(
                f"Diagnostics bundle could not be written: {error}"
            ) from error

    def _create(self) -> Path:
        generated_at = _utc_now()
        warnings: list[str] = []
        bridge = self._bridge_summary(warnings)
        payload: dict[str, Any] = {
            "bundle_version": BUNDLE_VERSION,
            "generated_at": generated_at,
            "agent": {
                "version": __version__,
                "python_version": platform.python_version(),
                "platform": platform.system() or "unknown",
                "platform_release": platform.release() or "unknown",
                "architecture": platform.machine() or "unknown",
            },
            "config_source": (
                "local" if self._config_file.is_file() else "packaged_default"
            ),
            "config": self._sanitize(load_config(self._config_file)),
            "bridge": bridge,
            "failed_commands": self._failed_command_metadata(warnings),
            "logs": self._log_excerpts(warnings),
            "warnings": warnings,
        }
        validate_contract("diagnostics-bundle", payload)
        output_root = self._runtime_root / "diagnostics"
        if output_root.is_symlink():
            raise DiagnosticsError(
                "Managed diagnostics directory must not be a symbolic link."
            )
        timestamp = generated_at.replace("-", "").replace(":", "").replace(
            ".", ""
        )
        output_path = output_root / f"diagnostics-{timestamp}.json"
        atomic_write_json(output_path, payload)
        return output_path

    def _bridge_summary(self, warnings: list[str]) -> dict[str, Any]:
        try:
            state = load_bridge_state(self._runtime_root)
            heartbeat_age_seconds(state)
        except BridgeStateError:
            warnings.append(
                "Cached Resolve bridge state is unavailable or invalid."
            )
            return {
                "available": False,
                "status": None,
                "bridge_version": None,
                "protocol_version": None,
                "resolve_version": None,
                "last_heartbeat": None,
                "capabilities": {},
            }
        return {
            "available": True,
            "status": _optional_string(state.get("status")),
            "bridge_version": _optional_string(
                state.get("bridge_version")
            ),
            "protocol_version": _optional_string(
                state.get("protocol_version")
            ),
            "resolve_version": _optional_string(
                state.get("resolve_version")
            ),
            "last_heartbeat": _optional_string(
                state.get("last_heartbeat")
            ),
            "capabilities": self._sanitize(state["capabilities"]),
        }

    def _failed_command_metadata(
        self,
        warnings: list[str],
    ) -> list[dict[str, Any]]:
        failed_root = self._runtime_root / "failed"
        paths = _recent_files(
            failed_root,
            suffixes={".json"},
            limit=MAX_FAILED_COMMANDS,
        )
        metadata: list[dict[str, Any]] = []
        for path in paths:
            try:
                payload = read_json_object(path)
            except (OSError, ValueError, json.JSONDecodeError):
                warnings.append(
                    f"Failed command metadata is unreadable: {path.name}"
                )
                continue
            stat = path.stat()
            safety = payload.get("safety")
            safe_safety = safety if isinstance(safety, dict) else {}
            metadata.append(
                {
                    "file_name": path.name,
                    "modified_at": _timestamp(stat.st_mtime),
                    "size_bytes": stat.st_size,
                    "command_id": _optional_string(
                        payload.get("command_id")
                    ),
                    "provider": _optional_string(payload.get("provider")),
                    "action": _optional_string(payload.get("action")),
                    "created_at": _optional_string(
                        payload.get("created_at")
                    ),
                    "allow_destructive": bool(
                        safe_safety.get("allow_destructive", False)
                    ),
                    "create_backup": bool(
                        safe_safety.get("create_backup", False)
                    ),
                }
            )
        return metadata

    def _log_excerpts(
        self,
        warnings: list[str],
    ) -> list[dict[str, Any]]:
        log_root = self._runtime_root / "logs"
        paths = _recent_files(
            log_root,
            suffixes=LOG_SUFFIXES,
            limit=MAX_LOG_FILES,
        )
        excerpts: list[dict[str, Any]] = []
        for path in paths:
            try:
                stat = path.stat()
                raw_lines, byte_truncated = _tail_lines(path)
            except OSError:
                warnings.append(f"Runtime log is unreadable: {path.name}")
                continue
            excerpts.append(
                {
                    "file_name": path.name,
                    "modified_at": _timestamp(stat.st_mtime),
                    "size_bytes": stat.st_size,
                    "truncated": (
                        byte_truncated or len(raw_lines) > MAX_LOG_LINES
                    ),
                    "lines": [
                        self._sanitize_text(line)
                        for line in raw_lines[-MAX_LOG_LINES:]
                    ],
                }
            )
        return excerpts

    def _sanitize(self, value: Any) -> Any:
        if isinstance(value, dict):
            sanitized: dict[str, Any] = {}
            for key, item in value.items():
                key_text = str(key)
                if _is_sensitive_key(key_text):
                    sanitized[key_text] = "[REDACTED]"
                else:
                    sanitized[key_text] = self._sanitize(item)
            return sanitized
        if isinstance(value, list):
            return [self._sanitize(item) for item in value]
        if isinstance(value, str):
            return self._sanitize_text(value)
        return value

    def _sanitize_text(self, value: str) -> str:
        sanitized = INLINE_SECRET_PATTERN.sub(r"\1[REDACTED]", value)
        replacements = _path_replacements(self._environment)
        for source, placeholder in replacements:
            sanitized = re.sub(
                re.escape(source),
                placeholder,
                sanitized,
                flags=re.IGNORECASE,
            )
        return sanitized


def _recent_files(
    root: Path,
    *,
    suffixes: set[str],
    limit: int,
) -> list[Path]:
    if not root.is_dir() or root.is_symlink():
        return []
    candidates = [
        path
        for path in root.iterdir()
        if (
            path.is_file()
            and not path.is_symlink()
            and path.suffix.lower() in suffixes
        )
    ]
    candidates.sort(
        key=lambda path: (path.stat().st_mtime, path.name),
        reverse=True,
    )
    return candidates[:limit]


def _tail_lines(path: Path) -> tuple[list[str], bool]:
    size = path.stat().st_size
    start = max(0, size - MAX_LOG_BYTES)
    with path.open("rb") as stream:
        stream.seek(start)
        data = stream.read(MAX_LOG_BYTES)
    text = data.decode("utf-8", errors="replace")
    lines = text.splitlines()
    if start > 0 and lines:
        lines = lines[1:]
    bounded = list(deque(lines, maxlen=MAX_LOG_LINES + 1))
    return bounded, start > 0


def _is_sensitive_key(key: str) -> bool:
    normalized = key.lower().replace("-", "_")
    return any(part in normalized for part in SENSITIVE_KEY_PARTS)


def _path_replacements(
    environment: Mapping[str, str],
) -> list[tuple[str, str]]:
    replacements: dict[str, str] = {}
    for name in ("LOCALAPPDATA", "APPDATA", "USERPROFILE"):
        value = environment.get(name)
        if not value:
            continue
        placeholder = f"${{{name}}}"
        replacements[value] = placeholder
        replacements[value.replace("\\", "/")] = placeholder
    replacements.setdefault(str(Path.home()), "${USERPROFILE}")
    return sorted(
        replacements.items(),
        key=lambda item: len(item[0]),
        reverse=True,
    )


def _optional_string(value: Any) -> str | None:
    return value if isinstance(value, str) else None


def _timestamp(value: float) -> str:
    return (
        datetime.fromtimestamp(value, timezone.utc)
        .isoformat()
        .replace("+00:00", "Z")
    )


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
