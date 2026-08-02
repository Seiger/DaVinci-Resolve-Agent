"""Packaged, allowlisted M53 CDL preset catalogue."""

from __future__ import annotations

import json
from importlib import resources
from typing import Any

from agent.contracts import validate_contract


class ColorPresetError(ValueError):
    """Raised when a packaged color preset is invalid or unavailable."""


class ColorPresetCatalogue:
    """Read immutable CDL presets without accepting LUT or DRX paths."""

    def __init__(self, *, manifests_root: Any | None = None) -> None:
        self._manifests_root = (
            resources.files("config").joinpath("color_presets")
            if manifests_root is None
            else manifests_root
        )

    def list_presets(self) -> dict[str, Any]:
        """Return stable summaries for every validated packaged preset."""
        presets = [
            self._summary(self._load_path(path))
            for path in sorted(
                self._manifests_root.iterdir(), key=lambda item: item.name
            )
            if path.name.endswith(".json")
        ]
        return {"presets": presets, "count": len(presets)}

    def get_preset(self, preset_id: str) -> dict[str, Any]:
        """Return one exact packaged preset by bounded canonical ID."""
        identifier = self._preset_id(preset_id)
        path = self._manifests_root.joinpath(f"{identifier}.json")
        if not path.is_file():
            raise ColorPresetError(f"Packaged color preset was not found: {identifier}")
        return self._load_path(path)

    def _load_path(self, path: Any) -> dict[str, Any]:
        try:
            with path.open("r", encoding="utf-8") as source:
                manifest = json.load(source)
        except (OSError, json.JSONDecodeError) as error:
            raise ColorPresetError(
                f"Color preset manifest is unreadable: {path.name}"
            ) from error
        if not isinstance(manifest, dict):
            raise ColorPresetError("Color preset manifest must be an object.")
        validate_contract("color-preset", manifest)
        if path.name != f"{manifest['preset_id']}.json":
            raise ColorPresetError(
                "Color preset filename must match its preset_id."
            )
        return manifest

    @staticmethod
    def _summary(manifest: dict[str, Any]) -> dict[str, Any]:
        return {
            key: manifest[key]
            for key in (
                "preset_id",
                "preset_version",
                "display_name",
                "description",
                "kind",
                "scope",
                "apply_policy",
            )
        }

    @staticmethod
    def _preset_id(value: str) -> str:
        if (
            not isinstance(value, str)
            or not 1 <= len(value) <= 64
            or any(
                character not in "abcdefghijklmnopqrstuvwxyz0123456789-"
                for character in value
            )
            or value.startswith("-")
            or value.endswith("-")
            or "--" in value
        ):
            raise ColorPresetError("preset_id is invalid.")
        return value
