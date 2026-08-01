"""Validated allowlisted declarative editing recipe execution."""

from __future__ import annotations

import hashlib
import json
import math
import re
from collections.abc import Callable, Mapping
from importlib import resources
from pathlib import Path
from typing import Any, Protocol

from agent.contracts import validate_contract
from agent.paths import editing_recipe_runs_directory
from transports.filesystem import atomic_write_json, read_json_object

RECIPE_RUN_VERSION = "1.0"
RECEIPT_ID_LENGTH = 64
MAX_RECIPE_INPUTS = 32

ACTION_CAPABILITIES: dict[str, tuple[str, ...]] = {
    "compose_webcam_picture_in_picture": (
        "clip.transform",
        "media.metadata.read",
    ),
    "link_synchronized_screen_pair": ("clip.link",),
}
ACTION_INPUTS: dict[str, tuple[str, ...]] = {
    "compose_webcam_picture_in_picture": (
        "synchronized_pair_receipt_id",
        "size_percent",
        "center_x_percent",
        "center_y_percent",
    ),
    "link_synchronized_screen_pair": ("synchronized_pair_receipt_id",),
}
INPUT_KINDS = {
    "synchronized_pair_receipt_id": "receipt_id",
    "size_percent": "number",
    "center_x_percent": "number",
    "center_y_percent": "number",
}


class EditingRecipeError(ValueError):
    """Raised when a declarative recipe cannot be handled safely."""


class EditingRecipeActions(Protocol):
    """Allowlisted application operations available to recipe steps."""

    def compose_webcam_picture_in_picture(
        self,
        *,
        synchronized_pair_receipt_id: str,
        size_percent: float,
        center_x_percent: float,
        center_y_percent: float,
        confirm_layout: bool,
        timeout_seconds: float = 30,
    ) -> dict[str, Any]: ...

    def link_synchronized_screen_pair(
        self,
        *,
        synchronized_pair_receipt_id: str,
        confirm_link: bool,
        timeout_seconds: float = 30,
    ) -> dict[str, Any]: ...


class EditingRecipeRunner:
    """Preview and execute packaged recipes through fixed application actions."""

    def __init__(
        self,
        *,
        actions: EditingRecipeActions,
        capabilities: Callable[[], dict[str, Any]],
        recipes_root: Any | None = None,
        receipts_root: Path | None = None,
    ) -> None:
        self._actions = actions
        self._capabilities = capabilities
        self._recipes_root = (
            resources.files("config").joinpath("recipes")
            if recipes_root is None
            else recipes_root
        )
        self._receipts_root = (
            editing_recipe_runs_directory()
            if receipts_root is None
            else receipts_root
        )

    def list_recipes(self) -> dict[str, Any]:
        """Return bounded summaries for every valid packaged recipe."""
        recipes = [
            self._summary(self._load_recipe(path.name.removesuffix(".json")))
            for path in sorted(
                (
                    item
                    for item in self._recipes_root.iterdir()
                    if item.is_file() and item.name.endswith(".json")
                ),
                key=lambda item: item.name,
            )
        ]
        return {"recipes": recipes, "count": len(recipes)}

    def get_recipe(self, recipe_id: str) -> dict[str, Any]:
        """Return one validated packaged recipe without executing it."""
        return self._load_recipe(recipe_id)

    def preview(
        self,
        recipe_id: str,
        inputs: Mapping[str, Any],
    ) -> dict[str, Any]:
        """Resolve recipe defaults and capability gates without writes."""
        recipe = self._load_recipe(recipe_id)
        normalized_inputs = _normalize_inputs(recipe, inputs)
        capabilities = self._capabilities()
        steps: list[dict[str, Any]] = []
        missing_all: set[str] = set()
        for raw_step in recipe["steps"]:
            required = _validated_step_capabilities(raw_step)
            missing = [
                capability
                for capability in required
                if capabilities.get(capability) is not True
            ]
            missing_all.update(missing)
            steps.append(
                {
                    "step_id": raw_step["step_id"],
                    "action": raw_step["action"],
                    "required_capabilities": list(required),
                    "missing_capabilities": missing,
                    "status": "blocked" if missing else "ready",
                }
            )
        return {
            "recipe_id": recipe["recipe_id"],
            "recipe_version": recipe["recipe_version"],
            "recipe_sha256": _recipe_sha256(recipe),
            "status": "blocked" if missing_all else "ready",
            "inputs": normalized_inputs,
            "steps": steps,
            "missing_capabilities": sorted(missing_all),
            "writes_resolve": True,
            "confirmation_required": True,
        }

    def run(
        self,
        recipe_id: str,
        inputs: Mapping[str, Any],
        *,
        confirm_execute: bool,
        timeout_seconds: float = 30,
    ) -> dict[str, Any]:
        """Execute one exact previewable recipe with durable step replay."""
        if confirm_execute is not True:
            raise EditingRecipeError("confirm_execute must be true.")
        timeout = _validated_timeout(timeout_seconds)
        preview = self.preview(recipe_id, inputs)
        if preview["status"] != "ready":
            raise EditingRecipeError(
                "Recipe capabilities are not verified: "
                + ", ".join(preview["missing_capabilities"])
            )
        normalized_inputs = preview["inputs"]
        receipt_id = _receipt_id(
            recipe_id,
            preview["recipe_version"],
            preview["recipe_sha256"],
            normalized_inputs,
        )
        receipt_path = self._receipts_root / f"{receipt_id}.json"
        if receipt_path.is_file():
            receipt = read_json_object(receipt_path)
            validate_contract("editing-recipe-run", receipt)
            if (
                receipt.get("receipt_id") != receipt_id
                or receipt.get("recipe_id") != recipe_id
                or receipt.get("recipe_sha256") != preview["recipe_sha256"]
                or receipt.get("inputs") != normalized_inputs
            ):
                raise EditingRecipeError(
                    "Stored recipe run does not match the request."
                )
            if receipt.get("status") == "applied":
                return receipt
        else:
            receipt = {
                "recipe_run_version": RECIPE_RUN_VERSION,
                "receipt_id": receipt_id,
                "recipe_id": recipe_id,
                "recipe_version": preview["recipe_version"],
                "recipe_sha256": preview["recipe_sha256"],
                "status": "in_progress",
                "inputs": normalized_inputs,
                "steps": [
                    {
                        "step_id": step["step_id"],
                        "action": step["action"],
                        "status": "pending",
                        "result": None,
                    }
                    for step in preview["steps"]
                ],
            }
            self._persist(receipt_path, receipt)

        for step in receipt["steps"]:
            if step["status"] == "applied":
                continue
            step["result"] = self._execute_step(
                step["action"],
                normalized_inputs,
                timeout,
            )
            step["status"] = "applied"
            self._persist(receipt_path, receipt)
        receipt["status"] = "applied"
        self._persist(receipt_path, receipt)
        return receipt

    def _execute_step(
        self,
        action: str,
        inputs: dict[str, Any],
        timeout_seconds: float,
    ) -> dict[str, Any]:
        if action == "compose_webcam_picture_in_picture":
            return self._actions.compose_webcam_picture_in_picture(
                synchronized_pair_receipt_id=inputs[
                    "synchronized_pair_receipt_id"
                ],
                size_percent=inputs["size_percent"],
                center_x_percent=inputs["center_x_percent"],
                center_y_percent=inputs["center_y_percent"],
                confirm_layout=True,
                timeout_seconds=timeout_seconds,
            )
        if action == "link_synchronized_screen_pair":
            return self._actions.link_synchronized_screen_pair(
                synchronized_pair_receipt_id=inputs[
                    "synchronized_pair_receipt_id"
                ],
                confirm_link=True,
                timeout_seconds=timeout_seconds,
            )
        raise EditingRecipeError(f"Unsupported recipe action: {action}")

    def _load_recipe(self, recipe_id: str) -> dict[str, Any]:
        _validate_recipe_id(recipe_id)
        path = self._recipes_root.joinpath(f"{recipe_id}.json")
        if not path.is_file():
            raise EditingRecipeError(f"Editing recipe was not found: {recipe_id}")
        try:
            with path.open("r", encoding="utf-8") as source:
                recipe = json.load(source)
        except (OSError, json.JSONDecodeError) as error:
            raise EditingRecipeError(
                f"Editing recipe could not be read: {recipe_id}"
            ) from error
        if not isinstance(recipe, dict):
            raise EditingRecipeError("Editing recipe root must be an object.")
        validate_contract("editing-recipe", recipe)
        if recipe.get("recipe_id") != recipe_id:
            raise EditingRecipeError(
                "Editing recipe identity does not match its filename."
            )
        _validate_recipe_definition(recipe)
        return recipe

    @staticmethod
    def _summary(recipe: dict[str, Any]) -> dict[str, Any]:
        return {
            "recipe_id": recipe["recipe_id"],
            "recipe_version": recipe["recipe_version"],
            "name": recipe["name"],
            "description": recipe["description"],
            "step_count": len(recipe["steps"]),
        }

    def _persist(self, path: Path, receipt: dict[str, Any]) -> None:
        validate_contract("editing-recipe-run", receipt)
        atomic_write_json(path, receipt)


def _validate_recipe_id(recipe_id: str) -> None:
    if (
        not isinstance(recipe_id, str)
        or not 1 <= len(recipe_id) <= 80
        or re.fullmatch(r"[a-z0-9]+(?:-[a-z0-9]+)*-v[0-9]+", recipe_id)
        is None
    ):
        raise EditingRecipeError("recipe_id has an invalid canonical format.")


def _validate_recipe_definition(recipe: dict[str, Any]) -> None:
    input_names = [item["name"] for item in recipe["inputs"]]
    step_ids = [item["step_id"] for item in recipe["steps"]]
    if len(input_names) != len(set(input_names)):
        raise EditingRecipeError("Recipe input names must be unique.")
    if len(step_ids) != len(set(step_ids)):
        raise EditingRecipeError("Recipe step IDs must be unique.")
    required_input_names = {
        name
        for step in recipe["steps"]
        for name in ACTION_INPUTS.get(step["action"], ())
    }
    if set(input_names) != required_input_names:
        raise EditingRecipeError(
            "Recipe inputs do not exactly match its allowlisted actions."
        )
    for definition in recipe["inputs"]:
        name = definition["name"]
        if definition["kind"] != INPUT_KINDS[name]:
            raise EditingRecipeError(f"Recipe input kind is invalid: {name}")
    receipt_definition = next(
        item
        for item in recipe["inputs"]
        if item["name"] == "synchronized_pair_receipt_id"
    )
    if receipt_definition["required"] is not True:
        raise EditingRecipeError(
            "synchronized_pair_receipt_id must be required."
        )
    for step in recipe["steps"]:
        _validated_step_capabilities(step)


def _validated_step_capabilities(step: dict[str, Any]) -> tuple[str, ...]:
    action = step["action"]
    expected = ACTION_CAPABILITIES.get(action)
    actual = tuple(step["required_capabilities"])
    if expected is None or actual != expected:
        raise EditingRecipeError(
            f"Recipe capability declaration is invalid for action: {action}"
        )
    return expected


def _normalize_inputs(
    recipe: dict[str, Any],
    supplied: Mapping[str, Any],
) -> dict[str, Any]:
    if not isinstance(supplied, Mapping) or len(supplied) > MAX_RECIPE_INPUTS:
        raise EditingRecipeError("Recipe inputs must be a bounded object.")
    definitions = {item["name"]: item for item in recipe["inputs"]}
    unknown = sorted(set(supplied) - set(definitions))
    if unknown:
        raise EditingRecipeError(
            "Unsupported recipe inputs: " + ", ".join(unknown)
        )
    normalized: dict[str, Any] = {}
    for name, definition in definitions.items():
        if name in supplied:
            value = supplied[name]
        elif "default" in definition:
            value = definition["default"]
        elif definition["required"]:
            raise EditingRecipeError(f"Required recipe input is missing: {name}")
        else:
            continue
        normalized[name] = _normalize_input(name, definition, value)
    return normalized


def _normalize_input(
    name: str,
    definition: dict[str, Any],
    value: Any,
) -> Any:
    kind = definition["kind"]
    if kind == "receipt_id":
        if (
            not isinstance(value, str)
            or len(value) != RECEIPT_ID_LENGTH
            or any(character not in "0123456789abcdef" for character in value)
        ):
            raise EditingRecipeError(f"{name} must be a lowercase SHA-256 ID.")
        return value
    if kind == "number":
        if (
            isinstance(value, bool)
            or not isinstance(value, (int, float))
            or not math.isfinite(float(value))
        ):
            raise EditingRecipeError(f"{name} must be a finite number.")
        number = float(value)
        minimum = definition.get("minimum")
        maximum = definition.get("maximum")
        if isinstance(minimum, (int, float)) and number < float(minimum):
            raise EditingRecipeError(f"{name} is below the recipe minimum.")
        if isinstance(maximum, (int, float)) and number > float(maximum):
            raise EditingRecipeError(f"{name} exceeds the recipe maximum.")
        return number
    if kind == "string":
        if not isinstance(value, str) or not value or len(value) > 500:
            raise EditingRecipeError(f"{name} must be a bounded string.")
        return value
    if kind == "boolean":
        if not isinstance(value, bool):
            raise EditingRecipeError(f"{name} must be boolean.")
        return value
    raise EditingRecipeError(f"Unsupported recipe input kind: {kind}")


def _validated_timeout(value: float) -> float:
    if (
        isinstance(value, bool)
        or not isinstance(value, (int, float))
        or not math.isfinite(float(value))
        or not 0 < float(value) <= 300
    ):
        raise EditingRecipeError(
            "timeout_seconds must be greater than zero and no more than 300."
        )
    return float(value)


def _receipt_id(
    recipe_id: str,
    recipe_version: str,
    recipe_sha256: str,
    inputs: dict[str, Any],
) -> str:
    payload = {
        "recipe_id": recipe_id,
        "recipe_version": recipe_version,
        "recipe_sha256": recipe_sha256,
        "inputs": inputs,
    }
    encoded = json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _recipe_sha256(recipe: dict[str, Any]) -> str:
    encoded = json.dumps(
        recipe,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()
