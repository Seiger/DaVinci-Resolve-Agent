"""M48 declarative editing recipe tests."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from agent.contracts import validate_contract
from agent.recipes import EditingRecipeError, EditingRecipeRunner

PAIR_RECEIPT_ID = "a" * 64


class StubActions:
    def __init__(self, *, fail_link_once: bool = False) -> None:
        self.calls: list[str] = []
        self.fail_link_once = fail_link_once

    def compose_webcam_picture_in_picture(
        self,
        *,
        synchronized_pair_receipt_id: str,
        size_percent: float,
        center_x_percent: float,
        center_y_percent: float,
        confirm_layout: bool,
        timeout_seconds: float = 30,
    ) -> dict[str, Any]:
        assert synchronized_pair_receipt_id == PAIR_RECEIPT_ID
        assert (size_percent, center_x_percent, center_y_percent) == (
            25.0,
            82.0,
            82.0,
        )
        assert confirm_layout is True
        assert timeout_seconds == 30.0
        self.calls.append("compose_webcam_picture_in_picture")
        return {"receipt_id": "b" * 64, "status": "applied"}

    def link_synchronized_screen_pair(
        self,
        *,
        synchronized_pair_receipt_id: str,
        confirm_link: bool,
        timeout_seconds: float = 30,
    ) -> dict[str, Any]:
        assert synchronized_pair_receipt_id == PAIR_RECEIPT_ID
        assert confirm_link is True
        assert timeout_seconds == 30.0
        self.calls.append("link_synchronized_screen_pair")
        if self.fail_link_once:
            self.fail_link_once = False
            raise RuntimeError("simulated interruption")
        return {"receipt_id": "c" * 64, "status": "applied"}


def _runner(
    tmp_path: Path,
    actions: StubActions | None = None,
    capabilities: dict[str, Any] | None = None,
) -> EditingRecipeRunner:
    active_capabilities = {
        "clip.transform": True,
        "media.metadata.read": True,
        "clip.link": True,
    }
    if capabilities is not None:
        active_capabilities = capabilities
    return EditingRecipeRunner(
        actions=StubActions() if actions is None else actions,
        capabilities=lambda: active_capabilities,
        recipes_root=Path("config/recipes"),
        receipts_root=tmp_path / "recipe-runs",
    )


def _inputs() -> dict[str, Any]:
    return {"synchronized_pair_receipt_id": PAIR_RECEIPT_ID}


def test_recipe_list_and_get_use_packaged_validated_definition(
    tmp_path: Path,
) -> None:
    runner = _runner(tmp_path)

    listed = runner.list_recipes()
    recipe = runner.get_recipe("tutorial-layout-v1")

    assert listed == {
        "count": 1,
        "recipes": [
            {
                "recipe_id": "tutorial-layout-v1",
                "recipe_version": "1.0",
                "name": "Tutorial synchronized layout",
                "description": recipe["description"],
                "step_count": 2,
            }
        ],
    }
    validate_contract("editing-recipe", recipe)


def test_recipe_preview_resolves_defaults_and_capability_gates(
    tmp_path: Path,
) -> None:
    preview = _runner(tmp_path).preview("tutorial-layout-v1", _inputs())

    assert preview["status"] == "ready"
    assert len(preview["recipe_sha256"]) == 64
    assert preview["inputs"] == {
        "synchronized_pair_receipt_id": PAIR_RECEIPT_ID,
        "size_percent": 25.0,
        "center_x_percent": 82.0,
        "center_y_percent": 82.0,
    }
    assert [step["status"] for step in preview["steps"]] == ["ready", "ready"]
    assert preview["confirmation_required"] is True
    assert preview["writes_resolve"] is True

    blocked = _runner(
        tmp_path,
        capabilities={
            "clip.transform": True,
            "media.metadata.read": "unknown",
            "clip.link": True,
        },
    ).preview("tutorial-layout-v1", _inputs())

    assert blocked["status"] == "blocked"
    assert blocked["missing_capabilities"] == ["media.metadata.read"]


def test_recipe_run_requires_confirmation_and_replays_receipt(
    tmp_path: Path,
) -> None:
    actions = StubActions()
    runner = _runner(tmp_path, actions)

    with pytest.raises(EditingRecipeError, match="confirm_execute"):
        runner.run(
            "tutorial-layout-v1",
            _inputs(),
            confirm_execute=False,
        )

    first = runner.run(
        "tutorial-layout-v1",
        _inputs(),
        confirm_execute=True,
    )
    replay = runner.run(
        "tutorial-layout-v1",
        _inputs(),
        confirm_execute=True,
    )

    assert first == replay
    assert first["status"] == "applied"
    assert actions.calls == [
        "compose_webcam_picture_in_picture",
        "link_synchronized_screen_pair",
    ]
    validate_contract("editing-recipe-run", first)


def test_recipe_definition_hash_changes_run_identity(tmp_path: Path) -> None:
    recipe_root = tmp_path / "recipes"
    recipe_root.mkdir()
    source = Path("config/recipes/tutorial-layout-v1.json")
    recipe = json.loads(source.read_text(encoding="utf-8"))
    target = recipe_root / source.name
    target.write_text(json.dumps(recipe), encoding="utf-8")
    receipts_root = tmp_path / "recipe-runs"

    first = EditingRecipeRunner(
        actions=StubActions(),
        capabilities=lambda: {
            "clip.transform": True,
            "media.metadata.read": True,
            "clip.link": True,
        },
        recipes_root=recipe_root,
        receipts_root=receipts_root,
    ).run("tutorial-layout-v1", _inputs(), confirm_execute=True)

    recipe["description"] += " Updated definition."
    target.write_text(json.dumps(recipe), encoding="utf-8")
    second = EditingRecipeRunner(
        actions=StubActions(),
        capabilities=lambda: {
            "clip.transform": True,
            "media.metadata.read": True,
            "clip.link": True,
        },
        recipes_root=recipe_root,
        receipts_root=receipts_root,
    ).run("tutorial-layout-v1", _inputs(), confirm_execute=True)

    assert first["recipe_sha256"] != second["recipe_sha256"]
    assert first["receipt_id"] != second["receipt_id"]
    assert len(list(receipts_root.glob("*.json"))) == 2


def test_recipe_run_resumes_only_pending_step_after_interruption(
    tmp_path: Path,
) -> None:
    actions = StubActions(fail_link_once=True)
    runner = _runner(tmp_path, actions)

    with pytest.raises(RuntimeError, match="simulated interruption"):
        runner.run(
            "tutorial-layout-v1",
            _inputs(),
            confirm_execute=True,
        )

    receipt = next((tmp_path / "recipe-runs").glob("*.json"))
    assert '"status": "in_progress"' in receipt.read_text(encoding="utf-8")

    recovered = runner.run(
        "tutorial-layout-v1",
        _inputs(),
        confirm_execute=True,
    )

    assert recovered["status"] == "applied"
    assert actions.calls == [
        "compose_webcam_picture_in_picture",
        "link_synchronized_screen_pair",
        "link_synchronized_screen_pair",
    ]


@pytest.mark.parametrize(
    ("recipe_id", "inputs", "message"),
    [
        ("../unsafe", _inputs(), "recipe_id"),
        (
            "tutorial-layout-v1",
            {**_inputs(), "arbitrary_action": "shell"},
            "Unsupported recipe inputs",
        ),
        (
            "tutorial-layout-v1",
            {"synchronized_pair_receipt_id": "not-a-receipt"},
            "SHA-256",
        ),
    ],
)
def test_recipe_rejects_unsafe_identity_or_inputs(
    tmp_path: Path,
    recipe_id: str,
    inputs: dict[str, Any],
    message: str,
) -> None:
    with pytest.raises(EditingRecipeError, match=message):
        _runner(tmp_path).preview(recipe_id, inputs)
