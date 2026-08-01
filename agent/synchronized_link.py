"""Provider-neutral M40 synchronized screen video/audio linking."""

from __future__ import annotations

import hashlib
import json
import math
from collections.abc import Callable
from pathlib import Path
from typing import Any, Protocol, cast

from agent.contracts import validate_contract
from agent.paths import (
    synchronized_links_directory,
    synchronized_pairs_directory,
)
from transports.filesystem import atomic_write_json, read_json_object

LINK_VERSION = "1.0"
REQUIRED_CAPABILITIES = ("clip.link",)


class SynchronizedLinkError(ValueError):
    """Raised when an M38 screen pair cannot be linked safely."""


class SynchronizedLinkGateway(Protocol):
    """Provider-neutral operation required by the M40 workflow."""

    def set_clips_linked(
        self,
        timeline_id: str,
        timeline_item_ids: list[str],
        linked: bool,
        *,
        timeout_seconds: float,
        idempotency_key: str,
    ) -> dict[str, Any]: ...


class SynchronizedScreenLinker:
    """Link exactly the screen video/audio items from one applied M38 receipt."""

    def __init__(
        self,
        *,
        gateway: SynchronizedLinkGateway,
        capabilities: Callable[[], dict[str, Any]],
        synchronized_pairs_root: Path | None = None,
        receipts_root: Path | None = None,
    ) -> None:
        self._gateway = gateway
        self._capabilities = capabilities
        self._synchronized_pairs_root = (
            synchronized_pairs_directory()
            if synchronized_pairs_root is None
            else synchronized_pairs_root
        )
        self._receipts_root = (
            synchronized_links_directory()
            if receipts_root is None
            else receipts_root
        )

    def link(
        self,
        *,
        synchronized_pair_receipt_id: str,
        confirm_link: bool,
        timeout_seconds: float = 30,
    ) -> dict[str, Any]:
        """Link the canonical M38 screen pair with durable replay safety."""
        inputs = _validated_inputs(
            synchronized_pair_receipt_id,
            confirm_link,
            timeout_seconds,
        )
        source_receipt = self._load_synchronized_pair(
            inputs["synchronized_pair_receipt_id"]
        )
        self._require_capabilities()
        source = _source_details(source_receipt)
        receipt_id = _receipt_id(inputs)
        receipt_path = self._receipts_root / f"{receipt_id}.json"
        if receipt_path.is_file():
            receipt = read_json_object(receipt_path)
            validate_contract("synchronized-link-result", receipt)
            if receipt["receipt_id"] != receipt_id or receipt["inputs"] != inputs:
                raise SynchronizedLinkError(
                    "Stored synchronized-link inputs do not match the request."
                )
            if receipt["status"] == "applied":
                return receipt
        else:
            receipt = _new_receipt(receipt_id, inputs, source)
            self._persist(receipt_path, receipt)

        item_ids = [
            source["screen_video_timeline_item_id"],
            source["screen_audio_timeline_item_id"],
        ]
        result = self._gateway.set_clips_linked(
            source["timeline_id"],
            item_ids,
            True,
            timeout_seconds=float(timeout_seconds),
            idempotency_key=f"{receipt_id}:screen-pair",
        )
        _verify_link_result(source, result)
        receipt["operation"] = {
            "operation": "set_screen_pair_linked",
            "status": "applied",
            "result": result,
        }
        receipt["status"] = "applied"
        self._persist(receipt_path, receipt)
        return receipt

    def _load_synchronized_pair(self, receipt_id: str) -> dict[str, Any]:
        path = self._synchronized_pairs_root / f"{receipt_id}.json"
        if not path.is_file():
            raise SynchronizedLinkError(
                "Synchronized-pair receipt was not found."
            )
        receipt = read_json_object(path)
        validate_contract("synchronized-pair-result", receipt)
        if receipt.get("receipt_id") != receipt_id:
            raise SynchronizedLinkError(
                "Synchronized-pair receipt identity does not match its file."
            )
        if receipt.get("status") != "applied":
            raise SynchronizedLinkError(
                "Synchronized-pair receipt must be fully applied."
            )
        return receipt

    def _require_capabilities(self) -> None:
        capabilities = self._capabilities()
        unsupported = [
            name
            for name in REQUIRED_CAPABILITIES
            if capabilities.get(name) is not True
        ]
        if unsupported:
            raise SynchronizedLinkError(
                "Required Resolve capabilities are not verified: "
                + ", ".join(unsupported)
            )

    def _persist(self, path: Path, receipt: dict[str, Any]) -> None:
        validate_contract("synchronized-link-result", receipt)
        self._receipts_root.mkdir(parents=True, exist_ok=True)
        atomic_write_json(path, receipt)


def _validated_inputs(
    receipt_id: str,
    confirm_link: bool,
    timeout_seconds: float,
) -> dict[str, str]:
    if (
        not isinstance(receipt_id, str)
        or len(receipt_id) != 64
        or any(character not in "0123456789abcdef" for character in receipt_id)
    ):
        raise SynchronizedLinkError(
            "synchronized_pair_receipt_id must be a lowercase SHA-256 ID."
        )
    if confirm_link is not True:
        raise SynchronizedLinkError("confirm_link must be true.")
    if (
        isinstance(timeout_seconds, bool)
        or not isinstance(timeout_seconds, (int, float))
        or not math.isfinite(float(timeout_seconds))
        or not 0 < float(timeout_seconds) <= 300
    ):
        raise SynchronizedLinkError(
            "timeout_seconds must be greater than zero and no more than 300."
        )
    return {"synchronized_pair_receipt_id": receipt_id}


def _source_details(receipt: dict[str, Any]) -> dict[str, str]:
    timeline = receipt.get("timeline")
    operations = receipt.get("operations")
    video_operation = operations[2] if isinstance(operations, list) else None
    audio_operation = operations[3] if isinstance(operations, list) else None
    video_result = (
        video_operation.get("result")
        if isinstance(video_operation, dict)
        else None
    )
    audio_result = (
        audio_operation.get("result")
        if isinstance(audio_operation, dict)
        else None
    )
    video_item = (
        video_result.get("item") if isinstance(video_result, dict) else None
    )
    audio_item = (
        audio_result.get("item") if isinstance(audio_result, dict) else None
    )
    timeline_id = timeline.get("timeline_id") if isinstance(timeline, dict) else None
    video_id = (
        video_item.get("timeline_item_id")
        if isinstance(video_item, dict)
        else None
    )
    audio_id = (
        audio_item.get("timeline_item_id")
        if isinstance(audio_item, dict)
        else None
    )
    if (
        not all(
            isinstance(value, str) and value
            for value in (timeline_id, video_id, audio_id)
        )
        or video_id == audio_id
    ):
        raise SynchronizedLinkError(
            "Synchronized-pair receipt has no distinct canonical screen items."
        )
    return {
        "timeline_id": cast(str, timeline_id),
        "screen_video_timeline_item_id": cast(str, video_id),
        "screen_audio_timeline_item_id": cast(str, audio_id),
    }


def _verify_link_result(
    source: dict[str, str], result: dict[str, Any]
) -> None:
    expected_ids = {
        source["screen_video_timeline_item_id"],
        source["screen_audio_timeline_item_id"],
    }
    items = result.get("items")
    if (
        result.get("timeline_id") != source["timeline_id"]
        or result.get("linked") is not True
        or not isinstance(items, list)
        or len(items) != 2
    ):
        raise SynchronizedLinkError(
            "Screen link returned invalid identity or readback."
        )
    discovered: dict[str, dict[str, Any]] = {}
    for item in items:
        if not isinstance(item, dict):
            raise SynchronizedLinkError("Screen link item readback is invalid.")
        item_id = item.get("timeline_item_id")
        if isinstance(item_id, str):
            discovered[item_id] = item
    if set(discovered) != expected_ids:
        raise SynchronizedLinkError(
            "Screen link readback returned unexpected item IDs."
        )
    for item_id, item in discovered.items():
        peer_id = next(iter(expected_ids - {item_id}))
        linked_ids = item.get("linked_item_ids")
        if not isinstance(linked_ids, list) or peer_id not in linked_ids:
            raise SynchronizedLinkError(
                "Screen items do not report a mutual link."
            )


def _receipt_id(inputs: dict[str, str]) -> str:
    payload = json.dumps(
        {"link_version": LINK_VERSION, "inputs": inputs},
        sort_keys=True,
        separators=(",", ":"),
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _new_receipt(
    receipt_id: str,
    inputs: dict[str, str],
    source: dict[str, str],
) -> dict[str, Any]:
    return {
        "link_version": LINK_VERSION,
        "receipt_id": receipt_id,
        "status": "in_progress",
        "inputs": inputs,
        "source": source,
        "operation": {
            "operation": "set_screen_pair_linked",
            "status": "pending",
            "result": None,
        },
    }
