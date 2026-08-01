"""Provider-neutral M50 baseline edit QA and deterministic render start."""

from __future__ import annotations

import hashlib
import json
import math
from pathlib import Path
from typing import Any, Protocol

from agent.contracts import validate_contract
from agent.paths import (
    baseline_edit_runs_directory,
    finalized_audio_integrations_directory,
    pause_compaction_finalizations_directory,
    subtitle_receipts_directory,
    visual_treatments_directory,
)
from agent.rendering import validate_render_name, validate_render_profile
from transports.filesystem import atomic_write_json, read_json_object

BASELINE_EDIT_VERSION = "1.0"


class BaselineEditError(ValueError):
    """Raised when a baseline edit cannot pass QA or render safely."""


class BaselineEditGateway(Protocol):
    """Read-only provider calls used by baseline QA."""

    def timeline_items(
        self,
        timeline_id: str,
        *,
        timeout_seconds: float,
    ) -> dict[str, Any]: ...

    def subtitle_environment(
        self,
        timeline_id: str,
        *,
        timeout_seconds: float,
    ) -> dict[str, Any]: ...


class BaselineRenderPreparer(Protocol):
    def prepare(
        self,
        *,
        finalization_receipt_id: str,
        custom_name: str,
        profile: str,
        confirm_prepare: bool,
        timeout_seconds: float,
    ) -> dict[str, Any]: ...


class BaselineRenderExecutor(Protocol):
    def start(
        self,
        *,
        preparation_receipt_id: str,
        confirm_render: bool,
        timeout_seconds: float,
    ) -> dict[str, Any]: ...

    def status(
        self,
        execution_receipt_id: str,
        *,
        timeout_seconds: float,
    ) -> dict[str, Any]: ...


class BaselineEditWorkflow:
    """Bind proven edit receipts, live QA, and a new deterministic render."""

    def __init__(
        self,
        *,
        gateway: BaselineEditGateway,
        render_preparer: BaselineRenderPreparer,
        render_executor: BaselineRenderExecutor,
        finalizations_root: Path | None = None,
        audio_integrations_root: Path | None = None,
        subtitle_receipts_root: Path | None = None,
        visual_treatments_root: Path | None = None,
        runs_root: Path | None = None,
    ) -> None:
        self._gateway = gateway
        self._render_preparer = render_preparer
        self._render_executor = render_executor
        self._finalizations_root = (
            finalizations_root or pause_compaction_finalizations_directory()
        )
        self._audio_integrations_root = (
            audio_integrations_root or finalized_audio_integrations_directory()
        )
        self._subtitle_receipts_root = (
            subtitle_receipts_root or subtitle_receipts_directory()
        )
        self._visual_treatments_root = (
            visual_treatments_root or visual_treatments_directory()
        )
        self._runs_root = runs_root or baseline_edit_runs_directory()

    def preview(
        self,
        *,
        finalization_receipt_id: str,
        audio_integration_receipt_id: str,
        subtitle_receipt_id: str | None = None,
        visual_treatment_receipt_id: str | None = None,
        timeout_seconds: float = 30,
    ) -> dict[str, Any]:
        """Inspect canonical receipts and their live timeline readback."""
        inputs = _receipt_inputs(
            finalization_receipt_id,
            audio_integration_receipt_id,
            subtitle_receipt_id,
            visual_treatment_receipt_id,
        )
        timeout = _validated_timeout(timeout_seconds)
        receipts, checks = self._load_receipts(inputs)
        target = _target_from_finalization(receipts["finalization"])
        target_ids = _receipt_target_ids(receipts)
        checks.append(
            _check(
                "single_timeline",
                target_ids == {target["timeline_id"]},
                "All edit receipts target one canonical timeline.",
                "Edit receipts target different timelines.",
            )
        )

        if target_ids == {target["timeline_id"]}:
            live = self._gateway.timeline_items(
                target["timeline_id"], timeout_seconds=timeout
            )
            subtitles = (
                self._gateway.subtitle_environment(
                    target["timeline_id"], timeout_seconds=timeout
                )
                if "subtitles" in receipts
                else None
            )
            checks.extend(_live_checks(target, receipts, live, subtitles))
        else:
            checks.extend(
                [
                    _check(
                        "timeline_identity",
                        False,
                        "",
                        "Live QA skipped because receipt timelines differ.",
                    ),
                    _check(
                        "core_items",
                        False,
                        "",
                        "Live QA skipped because receipt timelines differ.",
                    ),
                    _check(
                        "cleaned_audio",
                        False,
                        "",
                        "Live QA skipped because receipt timelines differ.",
                    ),
                ]
            )
            for optional_name in ("subtitles", "visual"):
                if optional_name in receipts:
                    checks.append(
                        _check(
                            "subtitles"
                            if optional_name == "subtitles"
                            else "visual_treatment",
                            False,
                            "",
                            "Live QA skipped because receipt timelines differ.",
                        )
                    )

        failed = sum(item["status"] == "failed" for item in checks)
        result = {
            "baseline_edit_version": BASELINE_EDIT_VERSION,
            "status": "ready" if failed == 0 else "blocked",
            "inputs": inputs,
            "target": target,
            "checks": checks,
            "summary": {"passed": len(checks) - failed, "failed": failed},
        }
        validate_contract("baseline-edit-qa", result)
        return result

    def start(
        self,
        *,
        finalization_receipt_id: str,
        audio_integration_receipt_id: str,
        custom_name: str,
        profile: str,
        confirm_render: bool,
        subtitle_receipt_id: str | None = None,
        visual_treatment_receipt_id: str | None = None,
        timeout_seconds: float = 30,
    ) -> dict[str, Any]:
        """Run QA and start a new baseline render after explicit confirmation."""
        if confirm_render is not True:
            raise BaselineEditError("confirm_render must be true.")
        inputs: dict[str, Any] = {
            **_receipt_inputs(
                finalization_receipt_id,
                audio_integration_receipt_id,
                subtitle_receipt_id,
                visual_treatment_receipt_id,
            ),
            "custom_name": validate_render_name(custom_name),
            "profile": validate_render_profile(profile).name,
        }
        timeout = _validated_timeout(timeout_seconds)
        receipt_id = _receipt_id(inputs)
        path = self._runs_root / f"{receipt_id}.json"
        if path.is_file():
            receipt = self._load_run(receipt_id)
            if receipt.get("inputs") != inputs:
                raise BaselineEditError(
                    "Stored baseline inputs do not match the request."
                )
            if receipt.get("status") == "started":
                return receipt
        else:
            qa = self.preview(timeout_seconds=timeout, **_qa_inputs(inputs))
            if qa["status"] != "ready":
                raise BaselineEditError(
                    "Baseline edit QA is blocked; render was not prepared."
                )
            render_name = _render_name(inputs["custom_name"], receipt_id)
            receipt = {
                "baseline_edit_version": BASELINE_EDIT_VERSION,
                "receipt_id": receipt_id,
                "status": "in_progress",
                "inputs": inputs,
                "target": qa["target"],
                "qa": qa,
                "render": {
                    "custom_name": render_name,
                    "preparation_receipt_id": None,
                    "execution_receipt_id": None,
                },
            }
            self._persist(path, receipt)

        render = receipt["render"]
        preparation = self._render_preparer.prepare(
            finalization_receipt_id=inputs["finalization_receipt_id"],
            custom_name=render["custom_name"],
            profile=inputs["profile"],
            confirm_prepare=True,
            timeout_seconds=timeout,
        )
        preparation_id = _result_receipt_id(preparation, "render preparation")
        render["preparation_receipt_id"] = preparation_id
        self._persist(path, receipt)
        execution = self._render_executor.start(
            preparation_receipt_id=preparation_id,
            confirm_render=True,
            timeout_seconds=timeout,
        )
        render["execution_receipt_id"] = _result_receipt_id(
            execution, "render execution"
        )
        receipt["status"] = "started"
        self._persist(path, receipt)
        return receipt

    def status(
        self,
        receipt_id: str,
        *,
        timeout_seconds: float = 30,
    ) -> dict[str, Any]:
        """Re-run live QA and inspect the exact managed render output."""
        normalized_id = _sha256(receipt_id, "receipt_id")
        receipt = self._load_run(normalized_id)
        if receipt.get("status") != "started":
            raise BaselineEditError("Baseline render has not confirmed a start.")
        timeout = _validated_timeout(timeout_seconds)
        qa = self.preview(timeout_seconds=timeout, **_qa_inputs(receipt["inputs"]))
        execution_id = receipt["render"].get("execution_receipt_id")
        if not isinstance(execution_id, str):
            raise BaselineEditError("Baseline receipt has no render execution ID.")
        render = self._render_executor.status(execution_id, timeout_seconds=timeout)
        live = render.get("live")
        output = render.get("output")
        validation = output.get("validation") if isinstance(output, dict) else None
        complete = (
            qa["status"] == "ready"
            and isinstance(live, dict)
            and isinstance(live.get("status"), dict)
            and live["status"].get("JobStatus") == "Complete"
            and isinstance(validation, dict)
            and validation.get("passed") is True
        )
        result = {
            "receipt_id": normalized_id,
            "status": "complete" if complete else "in_progress",
            "target": receipt["target"],
            "qa": qa,
            "render": render,
        }
        validate_contract("baseline-edit-status", result)
        return result

    def _load_receipts(
        self, inputs: dict[str, str | None]
    ) -> tuple[dict[str, dict[str, Any]], list[dict[str, str]]]:
        specifications = (
            (
                "finalization",
                "finalization_receipt_id",
                self._finalizations_root,
                "pause-compaction-finalization",
            ),
            (
                "audio",
                "audio_integration_receipt_id",
                self._audio_integrations_root,
                "finalized-audio-integration",
            ),
            (
                "subtitles",
                "subtitle_receipt_id",
                self._subtitle_receipts_root,
                "subtitle-generation",
            ),
            (
                "visual",
                "visual_treatment_receipt_id",
                self._visual_treatments_root,
                "visual-treatment-result",
            ),
        )
        receipts: dict[str, dict[str, Any]] = {}
        checks: list[dict[str, str]] = []
        for name, input_name, root, contract in specifications:
            receipt_id = inputs[input_name]
            if receipt_id is None:
                continue
            path = root / f"{receipt_id}.json"
            if not path.is_file():
                raise BaselineEditError(f"Required {name} receipt was not found.")
            receipt = read_json_object(path)
            validate_contract(contract, receipt)  # type: ignore[arg-type]
            applied = (
                receipt.get("receipt_id") == receipt_id
                and receipt.get("status") == "applied"
            )
            if not applied:
                raise BaselineEditError(
                    f"Required {name} receipt is not canonical and applied."
                )
            receipts[name] = receipt
            checks.append(
                _check(
                    f"{name}_receipt",
                    True,
                    f"Canonical applied {name} receipt is valid.",
                    "",
                )
            )
        return receipts, checks

    def _load_run(self, receipt_id: str) -> dict[str, Any]:
        path = self._runs_root / f"{receipt_id}.json"
        if not path.is_file():
            raise BaselineEditError("M50 baseline edit receipt was not found.")
        receipt = read_json_object(path)
        validate_contract("baseline-edit-run", receipt)
        if receipt.get("receipt_id") != receipt_id:
            raise BaselineEditError("M50 receipt filename does not match its ID.")
        return receipt

    def _persist(self, path: Path, receipt: dict[str, Any]) -> None:
        validate_contract("baseline-edit-run", receipt)
        self._runs_root.mkdir(parents=True, exist_ok=True)
        atomic_write_json(path, receipt)


def _live_checks(
    target: dict[str, str],
    receipts: dict[str, dict[str, Any]],
    live: dict[str, Any],
    subtitles: dict[str, Any] | None,
) -> list[dict[str, str]]:
    items = live.get("items")
    live_items = (
        {
            item.get("timeline_item_id"): item
            for item in items
            if isinstance(item, dict) and isinstance(items, list)
        }
        if isinstance(items, list)
        else {}
    )
    identity_ok = (
        live.get("timeline_id") == target["timeline_id"]
        and live.get("name") == target["timeline_name"]
    )
    final_items = _receipt_items(receipts["finalization"])
    audio_items = _receipt_items(receipts["audio"])
    core_ok = _items_match(final_items, live_items)
    audio_ok = _items_match(audio_items, live_items)
    checks = [
        _check(
            "timeline_identity",
            identity_ok,
            "Live timeline identity matches all receipts.",
            "Live timeline identity does not match the canonical target.",
        ),
        _check(
            "core_items",
            core_ok,
            "All finalized rough-cut items retain their canonical bounds.",
            "Finalized rough-cut item identity or bounds changed.",
        ),
        _check(
            "cleaned_audio",
            audio_ok,
            "Cleaned audio and source media items retain their canonical bounds.",
            "Cleaned-audio item identity or bounds changed.",
        ),
    ]
    if "subtitles" in receipts:
        subtitle_ids = set(receipts["subtitles"]["timeline_item_ids"])
        live_subtitle_ids = _subtitle_ids(subtitles or {})
        checks.append(
            _check(
                "subtitles",
                subtitle_ids.issubset(live_subtitle_ids),
                "All generated subtitle items remain present.",
                "One or more generated subtitle items are missing.",
            )
        )
    if "visual" in receipts:
        visual_ids = {
            transform["timeline_item_id"]
            for transform in receipts["visual"]["inputs"]["transforms"]
        }
        title_items = _visual_title_items(receipts["visual"])
        titles_ok = not title_items or _items_match(title_items, live_items)
        visual_ok = visual_ids.issubset(live_items) and titles_ok
        checks.append(
            _check(
                "visual_treatment",
                visual_ok,
                "Visual targets and generated titles remain present with "
                "canonical bounds.",
                "A visual target or generated title is missing or changed.",
            )
        )
    return checks


def _receipt_items(receipt: dict[str, Any]) -> list[dict[str, Any]]:
    readback = receipt.get("readback")
    items = readback.get("items") if isinstance(readback, dict) else None
    return (
        [item for item in items if isinstance(item, dict)]
        if isinstance(items, list)
        else []
    )


def _visual_title_items(receipt: dict[str, Any]) -> list[dict[str, Any]]:
    found: list[dict[str, Any]] = []
    for operation in receipt.get("operations", []):
        result = operation.get("result") if isinstance(operation, dict) else None
        item = result.get("item") if isinstance(result, dict) else None
        if operation.get("kind") == "insert_title" and isinstance(item, dict):
            found.append(item)
    return found


def _items_match(
    expected: list[dict[str, Any]], live: dict[Any, dict[str, Any]]
) -> bool:
    keys = (
        "timeline_start_frame",
        "timeline_end_frame",
        "duration_frames",
        "track_type",
        "track_index",
    )
    return bool(expected) and all(
        isinstance(item.get("timeline_item_id"), str)
        and item["timeline_item_id"] in live
        and all(
            live[item["timeline_item_id"]].get(key) == item.get(key)
            for key in keys
            if key in item
        )
        for item in expected
    )


def _subtitle_ids(environment: dict[str, Any]) -> set[str]:
    found: set[str] = set()
    for track in environment.get("tracks", []):
        if not isinstance(track, dict):
            continue
        for item in track.get("items", []):
            if isinstance(item, dict) and isinstance(item.get("timeline_item_id"), str):
                found.add(item["timeline_item_id"])
    return found


def _receipt_target_ids(receipts: dict[str, dict[str, Any]]) -> set[str]:
    target_ids = {
        str(receipts["finalization"]["target"]["timeline_id"]),
        str(receipts["audio"]["target"]["timeline_id"]),
    }
    if "subtitles" in receipts:
        target_ids.add(str(receipts["subtitles"]["timeline_id"]))
    if "visual" in receipts:
        target_ids.add(str(receipts["visual"]["inputs"]["timeline_id"]))
    return target_ids


def _target_from_finalization(receipt: dict[str, Any]) -> dict[str, str]:
    return {
        "timeline_id": str(receipt["target"]["timeline_id"]),
        "timeline_name": str(receipt["target"]["timeline_name"]),
    }


def _receipt_inputs(
    finalization: str,
    audio: str,
    subtitles: str | None,
    visual: str | None,
) -> dict[str, str | None]:
    return {
        "finalization_receipt_id": _sha256(finalization, "finalization_receipt_id"),
        "audio_integration_receipt_id": _sha256(audio, "audio_integration_receipt_id"),
        "subtitle_receipt_id": _optional_sha256(subtitles, "subtitle_receipt_id"),
        "visual_treatment_receipt_id": _optional_sha256(
            visual, "visual_treatment_receipt_id"
        ),
    }


def _qa_inputs(inputs: dict[str, Any]) -> dict[str, Any]:
    return {
        name: inputs[name]
        for name in (
            "finalization_receipt_id",
            "audio_integration_receipt_id",
            "subtitle_receipt_id",
            "visual_treatment_receipt_id",
        )
    }


def _sha256(value: str, name: str) -> str:
    if (
        not isinstance(value, str)
        or len(value) != 64
        or any(character not in "0123456789abcdef" for character in value)
    ):
        raise BaselineEditError(f"{name} must be a lowercase SHA-256 ID.")
    return value


def _optional_sha256(value: str | None, name: str) -> str | None:
    return None if value is None else _sha256(value, name)


def _validated_timeout(value: float) -> float:
    if (
        isinstance(value, bool)
        or not isinstance(value, (int, float))
        or not math.isfinite(float(value))
        or not 0 < float(value) <= 300
    ):
        raise BaselineEditError(
            "timeout_seconds must be greater than zero and no more than 300."
        )
    return float(value)


def _check(name: str, passed: bool, success: str, failure: str) -> dict[str, str]:
    return {
        "name": name,
        "status": "passed" if passed else "failed",
        "message": success if passed else failure,
    }


def _receipt_id(inputs: dict[str, Any]) -> str:
    payload = json.dumps(
        {"baseline_edit_version": BASELINE_EDIT_VERSION, "inputs": inputs},
        sort_keys=True,
        separators=(",", ":"),
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _render_name(custom_name: str, receipt_id: str) -> str:
    suffix = f"-{receipt_id[:12]}"
    return f"{custom_name[: 128 - len(suffix)].rstrip()}{suffix}"


def _result_receipt_id(result: dict[str, Any], label: str) -> str:
    value = result.get("receipt_id")
    if not isinstance(value, str):
        raise BaselineEditError(f"M50 {label} returned no receipt ID.")
    return _sha256(value, f"{label}_receipt_id")
