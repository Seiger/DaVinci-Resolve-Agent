"""Installer-owned local storage TOML update tests."""

from __future__ import annotations

import importlib.util
from pathlib import Path
from types import ModuleType


def _module() -> ModuleType:
    path = (
        Path(__file__).parents[2]
        / "installer"
        / "update_storage_config.py"
    )
    spec = importlib.util.spec_from_file_location("update_storage_config", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_storage_config_update_preserves_unrelated_values(tmp_path: Path) -> None:
    config = tmp_path / "config.toml"
    config.write_text(
        "\n".join(
            (
                "[agent]",
                'provider = "resolve"',
                "[runtime]",
                'root = "old/runtime"',
                "[media]",
                'allowed_roots = ["G:/sources"]',
                "",
            )
        ),
        encoding="utf-8",
    )
    data_root = tmp_path / "video-drive" / "DaVinciResolveAgent"

    _module().update_storage_config(config, data_root)
    updated = config.read_text(encoding="utf-8")

    root = data_root.resolve().as_posix()
    assert 'provider = "resolve"' in updated
    assert 'allowed_roots = ["G:/sources"]' in updated
    assert f'root = "{root}/runtime"' in updated
    assert f'managed_root = "{root}/media"' in updated
    assert f'data_root = "{root}"' in updated
