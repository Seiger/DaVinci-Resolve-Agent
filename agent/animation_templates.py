"""Packaged, allowlisted M52 animation-template catalogue."""

from __future__ import annotations

import hashlib
import json
from importlib import resources
from pathlib import Path
from typing import Any

from agent.contracts import validate_contract


class AnimationTemplateError(ValueError):
    """Raised when a packaged animation template is invalid or unavailable."""


class AnimationTemplateCatalogue:
    """Discover immutable packaged templates without accepting external files."""

    def __init__(
        self,
        *,
        manifests_root: Any | None = None,
        assets_root: Any | None = None,
    ) -> None:
        config_root = resources.files("config")
        self._manifests_root = (
            config_root.joinpath("animation_templates")
            if manifests_root is None
            else manifests_root
        )
        self._assets_root = (
            config_root.joinpath("fusion_templates")
            if assets_root is None
            else assets_root
        )

    def list_templates(self) -> dict[str, Any]:
        """Return stable summaries for every validated packaged template."""
        templates = [
            self._summary(self._load_path(path))
            for path in sorted(
                self._manifests_root.iterdir(), key=lambda item: item.name
            )
            if path.name.endswith(".json")
        ]
        return {"templates": templates, "count": len(templates)}

    def get_template(self, template_id: str) -> dict[str, Any]:
        """Return one exact packaged template by bounded canonical ID."""
        identifier = self._template_id(template_id)
        path = self._manifests_root.joinpath(f"{identifier}.json")
        if not path.is_file():
            raise AnimationTemplateError(
                f"Packaged animation template was not found: {identifier}"
            )
        return self._load_path(path)

    def _load_path(self, path: Any) -> dict[str, Any]:
        try:
            with path.open("r", encoding="utf-8") as source:
                manifest = json.load(source)
        except (OSError, json.JSONDecodeError) as error:
            raise AnimationTemplateError(
                f"Animation template manifest is unreadable: {path.name}"
            ) from error
        if not isinstance(manifest, dict):
            raise AnimationTemplateError(
                "Animation template manifest must be an object."
            )
        validate_contract("animation-template", manifest)
        expected_name = f"{manifest['template_id']}.json"
        if path.name != expected_name:
            raise AnimationTemplateError(
                "Animation template filename must match its template_id."
            )
        asset = self._asset_path(manifest["asset_relative_path"])
        if not asset.is_file():
            raise AnimationTemplateError(
                f"Packaged Fusion template is missing: {asset.name}"
            )
        with asset.open("rb") as source:
            actual_hash = hashlib.sha256(source.read()).hexdigest()
        if actual_hash != manifest["asset_sha256"]:
            raise AnimationTemplateError(
                f"Packaged Fusion template hash mismatch: {manifest['template_id']}"
            )
        return manifest

    def _asset_path(self, relative_path: str) -> Any:
        parts = relative_path.split("/")
        if any(part in {"", ".", ".."} for part in parts):
            raise AnimationTemplateError("Animation template asset path is invalid.")
        path = self._assets_root
        for part in parts:
            path = path.joinpath(part)
        return path

    @staticmethod
    def _summary(manifest: dict[str, Any]) -> dict[str, Any]:
        return {
            key: manifest[key]
            for key in (
                "template_id",
                "template_version",
                "display_name",
                "description",
                "kind",
                "duration_policy",
                "editable_in_resolve",
                "programmatic_inputs",
            )
        }

    @staticmethod
    def _template_id(value: str) -> str:
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
            raise AnimationTemplateError("template_id is invalid.")
        return value


def installed_template_path(relative_path: str, appdata: Path) -> Path:
    """Build the documented Resolve user-template path without user literals."""
    base = (
        appdata
        / "Blackmagic Design"
        / "DaVinci Resolve"
        / "Support"
        / "Fusion"
        / "Templates"
    )
    result = base
    for part in relative_path.split("/"):
        if part in {"", ".", ".."}:
            raise AnimationTemplateError("Animation template asset path is invalid.")
        result /= part
    return result
