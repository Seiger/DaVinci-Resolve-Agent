"""Resolved per-machine storage layout tests."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from agent.storage import (
    StorageConfigurationError,
    data_root,
    ensure_storage_capacity,
    managed_media_root,
    runtime_root,
    storage_manifest_file,
)


def test_storage_manifest_routes_runtime_and_media_to_configured_root(
    tmp_path: Path,
) -> None:
    environment = {
        "APPDATA": str(tmp_path / "roaming"),
        "LOCALAPPDATA": str(tmp_path / "local"),
    }
    configured = tmp_path / "video-drive" / "DaVinciResolveAgent"
    manifest = storage_manifest_file(environment)
    manifest.parent.mkdir(parents=True)
    manifest.write_text(
        json.dumps(
            {"storage_version": "1.0", "data_root": str(configured)}
        ),
        encoding="utf-8",
    )

    assert data_root(environment) == configured.resolve()
    assert runtime_root(environment) == configured.resolve() / "runtime"
    assert managed_media_root(environment) == configured.resolve() / "media"


def test_storage_fallback_is_portable_and_user_independent(
    tmp_path: Path,
) -> None:
    environment = {
        "APPDATA": str(tmp_path / "roaming"),
        "LOCALAPPDATA": str(tmp_path / "local"),
    }

    assert data_root(environment) == (
        tmp_path / "local" / "DaVinciResolveAgent"
    )


def test_storage_manifest_rejects_a_volume_root(tmp_path: Path) -> None:
    environment = {
        "APPDATA": str(tmp_path / "roaming"),
        "LOCALAPPDATA": str(tmp_path / "local"),
    }
    manifest = storage_manifest_file(environment)
    manifest.parent.mkdir(parents=True)
    manifest.write_text(
        json.dumps({"storage_version": "1.0", "data_root": Path.cwd().anchor}),
        encoding="utf-8",
    )

    with pytest.raises(StorageConfigurationError, match="non-volume-root"):
        data_root(environment)


def test_storage_capacity_preserves_ten_gib_reserve(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    usage = type("Usage", (), {"free": 11 * 1024 * 1024 * 1024})()
    monkeypatch.setattr("agent.storage.shutil.disk_usage", lambda _: usage)

    with pytest.raises(StorageConfigurationError, match="10 GiB"):
        ensure_storage_capacity(tmp_path / "media", 2 * 1024 * 1024 * 1024)
