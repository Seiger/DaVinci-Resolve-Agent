"""M52 packaged animation-template catalogue tests."""

from __future__ import annotations

import json
from pathlib import Path, PureWindowsPath

import pytest

from agent.animation_templates import (
    AnimationTemplateCatalogue,
    AnimationTemplateError,
    installed_template_path,
)
from agent.contracts import validate_contract


def test_packaged_animation_template_is_listed_hashed_and_valid() -> None:
    catalogue = AnimationTemplateCatalogue()

    listing = catalogue.list_templates()
    template = catalogue.get_template("accent-card-v1")

    assert listing["count"] == 1
    assert listing["templates"][0]["template_id"] == "accent-card-v1"
    assert template["resolve_name"] == "DaVinci Agent Accent Card"
    assert template["programmatic_inputs"] == []
    validate_contract("animation-template", template)


def test_modified_packaged_asset_is_rejected(tmp_path: Path) -> None:
    manifests = tmp_path / "manifests"
    assets = tmp_path / "assets" / "Edit" / "Titles"
    manifests.mkdir()
    assets.mkdir(parents=True)
    source_manifest = Path("config/animation_templates/accent-card-v1.json")
    manifest = json.loads(source_manifest.read_text(encoding="utf-8"))
    (manifests / "accent-card-v1.json").write_text(
        json.dumps(manifest), encoding="utf-8"
    )
    (assets / "DaVinci Agent Accent Card.setting").write_text(
        "modified", encoding="utf-8"
    )
    catalogue = AnimationTemplateCatalogue(
        manifests_root=manifests,
        assets_root=tmp_path / "assets",
    )

    with pytest.raises(AnimationTemplateError, match="hash mismatch"):
        catalogue.get_template("accent-card-v1")


def test_accent_card_uses_documented_mirrored_anim_curves_reveal() -> None:
    setting = Path(
        "config/fusion_templates/Edit/Titles/"
        "DaVinci Agent Accent Card.setting"
    ).read_text(encoding="utf-8")

    assert "Reveal = Dissolve {" in setting
    assert 'SourceOp = "RevealAnimCurves"' in setting
    assert 'Source = "Value"' in setting
    assert "RevealAnimCurves = LUTLookup {" in setting
    assert "Mirror = Input { Value = 1, }" in setting
    assert 'Background = Input { SourceOp = "Canvas"' in setting
    assert 'Foreground = Input { SourceOp = "MergeSubtitle"' in setting
    assert "KeyStretcherMod" not in setting
    assert "BezierSpline" not in setting


def test_installed_template_path_uses_appdata_without_user_literal() -> None:
    first = installed_template_path(
        "Edit/Titles/DaVinci Agent Accent Card.setting",
        Path(r"C:\Users\first\AppData\Roaming"),
    )
    second = installed_template_path(
        "Edit/Titles/DaVinci Agent Accent Card.setting",
        Path(r"D:\Profiles\second\Roaming"),
    )

    assert first != second
    assert PureWindowsPath(str(first)).parts[-4:] == (
        "Templates",
        "Edit",
        "Titles",
        "DaVinci Agent Accent Card.setting",
    )
    assert "vogdj" not in str(first).casefold()
    assert "vogdj" not in str(second).casefold()
