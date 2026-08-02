"""M53 packaged color-preset catalogue tests."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from agent.color_presets import ColorPresetCatalogue, ColorPresetError
from agent.contracts import validate_contract


def test_packaged_color_preset_is_listed_and_valid() -> None:
    catalogue = ColorPresetCatalogue()

    listing = catalogue.list_presets()
    preset = catalogue.get_preset("tutorial-clean-v1")

    assert listing["count"] == 1
    assert listing["presets"][0]["preset_id"] == "tutorial-clean-v1"
    assert preset["cdl"]["saturation"] == 1.05
    validate_contract("color-preset", preset)


def test_color_preset_filename_must_match_id(tmp_path: Path) -> None:
    source = Path("config/color_presets/tutorial-clean-v1.json")
    manifest = json.loads(source.read_text(encoding="utf-8"))
    (tmp_path / "wrong.json").write_text(json.dumps(manifest), encoding="utf-8")

    with pytest.raises(ColorPresetError, match="filename"):
        ColorPresetCatalogue(manifests_root=tmp_path).list_presets()
