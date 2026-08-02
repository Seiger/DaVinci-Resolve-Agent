"""Resolved per-machine storage layout shared by the external agent."""

from __future__ import annotations

import json
import os
import shutil
from collections.abc import Mapping
from pathlib import Path
from typing import Any, Final

APPLICATION_DIRECTORY_NAME: Final = "DaVinciResolveAgent"
STORAGE_LAYOUT_VERSION: Final = "1.0"
STORAGE_MANIFEST_NAME: Final = "storage.json"
MAX_STORAGE_MANIFEST_BYTES: Final = 16_384
MINIMUM_FREE_BYTES: Final = 10 * 1024 * 1024 * 1024


class StorageConfigurationError(ValueError):
    """Raised when the resolved local storage manifest is unsafe."""


def _environment_value(name: str, environment: Mapping[str, str]) -> str:
    value = environment.get(name)
    if not value:
        raise StorageConfigurationError(
            f"Required Windows environment variable {name} is not set."
        )
    return value


def config_directory(environment: Mapping[str, str] | None = None) -> Path:
    """Return the small per-user configuration directory."""
    source = os.environ if environment is None else environment
    return Path(_environment_value("APPDATA", source)) / APPLICATION_DIRECTORY_NAME


def config_file(environment: Mapping[str, str] | None = None) -> Path:
    """Return the per-user TOML configuration path."""
    return config_directory(environment) / "config.toml"


def storage_manifest_file(
    environment: Mapping[str, str] | None = None,
) -> Path:
    """Return the installed resolved-storage manifest path."""
    return config_directory(environment) / STORAGE_MANIFEST_NAME


def data_root(environment: Mapping[str, str] | None = None) -> Path:
    """Resolve the configured data root or the portable Windows fallback."""
    source = os.environ if environment is None else environment
    if source.get("APPDATA"):
        manifest = storage_manifest_file(source)
        if manifest.is_file():
            return _read_manifest(manifest)
    return (
        Path(_environment_value("LOCALAPPDATA", source))
        / APPLICATION_DIRECTORY_NAME
    )


def runtime_root(environment: Mapping[str, str] | None = None) -> Path:
    """Return the filesystem transport and durable receipt root."""
    return data_root(environment) / "runtime"


def managed_media_root(environment: Mapping[str, str] | None = None) -> Path:
    """Return the root for all generated media artifacts."""
    return data_root(environment) / "media"


def ensure_storage_capacity(directory: Path, planned_bytes: int = 0) -> None:
    """Require room for a bounded write while preserving a 10 GiB reserve."""
    if planned_bytes < 0:
        raise StorageConfigurationError("planned_bytes must not be negative.")
    directory.mkdir(parents=True, exist_ok=True)
    free = shutil.disk_usage(directory).free
    if free < MINIMUM_FREE_BYTES + planned_bytes:
        raise StorageConfigurationError(
            "The configured storage volume cannot preserve the 10 GiB free-space "
            "reserve for this operation."
        )


def _read_manifest(path: Path) -> Path:
    try:
        if path.stat().st_size > MAX_STORAGE_MANIFEST_BYTES:
            raise StorageConfigurationError("Storage manifest is unexpectedly large.")
        with path.open("r", encoding="utf-8") as stream:
            payload: Any = json.load(stream)
    except (OSError, json.JSONDecodeError) as error:
        raise StorageConfigurationError(
            f"Storage manifest is unreadable: {error}"
        ) from error
    if (
        not isinstance(payload, dict)
        or set(payload) != {"storage_version", "data_root"}
        or payload.get("storage_version") != STORAGE_LAYOUT_VERSION
        or not isinstance(payload.get("data_root"), str)
    ):
        raise StorageConfigurationError("Storage manifest does not match version 1.0.")
    root = Path(payload["data_root"])
    if not root.is_absolute() or root == Path(root.anchor):
        raise StorageConfigurationError(
            "Storage data_root must be an absolute non-volume-root path."
        )
    return root.resolve()
