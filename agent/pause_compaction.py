"""Provider-neutral M41 preview for pause-removal timeline rebuilding."""

from __future__ import annotations

import hashlib
import json
import math
from pathlib import Path, PureWindowsPath
from typing import Any, Protocol

from agent.contracts import validate_contract
from agent.paths import synchronized_pairs_directory
from agent.rough_cut import RoughCutInspector
from transports.filesystem import read_json_object

PREVIEW_VERSION = "1.0"
MAX_CUTS = 1_000
MAX_FRAME_VALUE = 2_147_483_647
FUTURE_APPLY_CAPABILITIES = (
    "clip.insert",
    "timeline.create",
    "timeline.track.create",
)


class PauseCompactionError(ValueError):
    """Raised when a pause-compaction preview cannot be derived safely."""


class PauseCompactionGateway(Protocol):
    """Read-only provider metadata required by M41."""

    def editing_metadata(
        self,
        timeline_id: str,
        asset_ids: list[str],
        *,
        timeout_seconds: float,
    ) -> dict[str, Any]: ...


class RoughCutPlanReader(Protocol):
    """Approved rough-cut detail reader required by M41."""

    def get_plan(self, plan_id: str) -> dict[str, Any]: ...


class PauseCompactionPreviewer:
    """Plan kept-range V1/A1/V2 placement without modifying Resolve."""

    def __init__(
        self,
        *,
        gateway: PauseCompactionGateway,
        capabilities: dict[str, Any],
        inspector: RoughCutPlanReader | None = None,
        synchronized_pairs_root: Path | None = None,
    ) -> None:
        self._gateway = gateway
        self._capabilities = capabilities
        self._inspector = RoughCutInspector() if inspector is None else inspector
        self._synchronized_pairs_root = (
            synchronized_pairs_directory()
            if synchronized_pairs_root is None
            else synchronized_pairs_root
        )

    def preview(
        self,
        *,
        plan_id: str,
        synchronized_pair_receipt_id: str,
        target_timeline_name: str,
        timeout_seconds: float = 30,
    ) -> dict[str, Any]:
        """Return deterministic kept source ranges in provider-neutral frames."""
        _validate_request(
            plan_id,
            synchronized_pair_receipt_id,
            target_timeline_name,
            timeout_seconds,
        )
        if self._capabilities.get("media.metadata.read") is not True:
            raise PauseCompactionError(
                "Required Resolve capability is not verified: media.metadata.read"
            )
        plan, plan_sha256 = self._approved_plan(plan_id)
        synchronized_pair = self._load_synchronized_pair(
            synchronized_pair_receipt_id
        )
        _verify_plan_pair_binding(plan, synchronized_pair)
        source = _source_binding(plan, synchronized_pair)
        metadata = self._gateway.editing_metadata(
            source["timeline_id"],
            [source["screen_asset_id"], source["webcam_asset_id"]],
            timeout_seconds=float(timeout_seconds),
        )
        timeline_frame_rate, assets = _metadata(metadata, source)
        cuts, kept_intervals, source_duration_ms = _timeline_intervals(
            plan,
            synchronized_pair,
            assets,
        )
        placements = _placements(
            kept_intervals,
            synchronized_pair,
            source,
            assets,
            timeline_frame_rate,
        )
        removed_duration_ms = sum(cut["duration_ms"] for cut in cuts)
        output_duration_ms = source_duration_ms - removed_duration_ms
        unsupported = sorted(
            capability
            for capability in FUTURE_APPLY_CAPABILITIES
            if self._capabilities.get(capability) is not True
        )
        output_duration_frames = _milliseconds_to_frames(
            output_duration_ms, timeline_frame_rate
        )
        if not 1 <= output_duration_frames <= MAX_FRAME_VALUE:
            raise PauseCompactionError(
                "Preview output duration exceeds bounded frame limits."
            )
        result = {
            "preview_version": PREVIEW_VERSION,
            "status": "preview",
            "apply_supported": False,
            "plan_id": plan_id,
            "plan_sha256": plan_sha256,
            "synchronized_pair_receipt_id": synchronized_pair_receipt_id,
            "target_timeline_name": target_timeline_name.strip(),
            "timeline": {
                "frame_rate": timeline_frame_rate,
                "source_duration_ms": source_duration_ms,
                "removed_duration_ms": removed_duration_ms,
                "output_duration_ms": output_duration_ms,
                "output_duration_frames": output_duration_frames,
            },
            "cuts": cuts,
            "kept_intervals": kept_intervals,
            "placements": placements,
            "required_capabilities": list(FUTURE_APPLY_CAPABILITIES),
            "unsupported_capabilities": unsupported,
        }
        validate_contract("pause-compaction-preview", result)
        return result

    def _approved_plan(self, plan_id: str) -> tuple[dict[str, Any], str]:
        detail = self._inspector.get_plan(plan_id)
        plan = detail.get("plan")
        approval = detail.get("approval")
        if not isinstance(plan, dict) or not isinstance(approval, dict):
            raise PauseCompactionError(
                "A current matching rough-cut approval is required."
            )
        plan_sha256 = _canonical_sha256(plan)
        if (
            approval.get("status") != "approved"
            or approval.get("plan_sha256") != plan_sha256
        ):
            raise PauseCompactionError(
                "Approval SHA-256 does not match the current plan."
            )
        return plan, plan_sha256

    def _load_synchronized_pair(self, receipt_id: str) -> dict[str, Any]:
        path = self._synchronized_pairs_root / f"{receipt_id}.json"
        if not path.is_file():
            raise PauseCompactionError(
                "Synchronized-pair receipt was not found."
            )
        receipt = read_json_object(path)
        validate_contract("synchronized-pair-result", receipt)
        if receipt.get("receipt_id") != receipt_id:
            raise PauseCompactionError(
                "Synchronized-pair receipt identity does not match its file."
            )
        if receipt.get("status") != "applied":
            raise PauseCompactionError(
                "Synchronized-pair receipt must be fully applied."
            )
        return receipt


def _validate_request(
    plan_id: str,
    receipt_id: str,
    target_timeline_name: str,
    timeout_seconds: float,
) -> None:
    for name, value in (("plan_id", plan_id), ("receipt_id", receipt_id)):
        if (
            not isinstance(value, str)
            or len(value) != 64
            or any(character not in "0123456789abcdef" for character in value)
        ):
            raise PauseCompactionError(
                f"{name} must be a lowercase SHA-256 ID."
            )
    if (
        not isinstance(target_timeline_name, str)
        or not target_timeline_name.strip()
        or len(target_timeline_name.strip()) > 128
    ):
        raise PauseCompactionError(
            "target_timeline_name must contain 1 to 128 characters."
        )
    if (
        isinstance(timeout_seconds, bool)
        or not isinstance(timeout_seconds, (int, float))
        or not math.isfinite(float(timeout_seconds))
        or not 0 < float(timeout_seconds) <= 300
    ):
        raise PauseCompactionError(
            "timeout_seconds must be greater than zero and no more than 300."
        )


def _verify_plan_pair_binding(
    plan: dict[str, Any], synchronized_pair: dict[str, Any]
) -> None:
    plan_sync = plan.get("synchronization")
    pair_inputs = synchronized_pair.get("inputs")
    if (
        not isinstance(plan_sync, dict)
        or not isinstance(pair_inputs, dict)
        or plan_sync.get("webcam_offset_ms")
        != pair_inputs.get("webcam_offset_ms")
    ):
        raise PauseCompactionError(
            "Plan and synchronized-pair webcam offsets do not match."
        )


def _source_binding(
    plan: dict[str, Any], synchronized_pair: dict[str, Any]
) -> dict[str, str]:
    plan_inputs = plan.get("inputs")
    pair_inputs = synchronized_pair.get("inputs")
    timeline = synchronized_pair.get("timeline")
    if not all(
        isinstance(value, dict)
        for value in (plan_inputs, pair_inputs, timeline)
    ):
        raise PauseCompactionError("Plan or synchronized-pair inputs are invalid.")
    plan_inputs = plan_inputs if isinstance(plan_inputs, dict) else {}
    pair_inputs = pair_inputs if isinstance(pair_inputs, dict) else {}
    timeline = timeline if isinstance(timeline, dict) else {}
    values = {
        "timeline_id": timeline.get("timeline_id"),
        "screen_asset_id": pair_inputs.get("screen_asset_id"),
        "webcam_asset_id": pair_inputs.get("webcam_asset_id"),
        "screen_file_name": _file_name(plan_inputs.get("screen_file")),
        "webcam_file_name": _file_name(plan_inputs.get("webcam_file")),
    }
    if not all(isinstance(value, str) and value for value in values.values()):
        raise PauseCompactionError(
            "Plan and synchronized-pair source binding is incomplete."
        )
    return {name: str(value) for name, value in values.items()}


def _file_name(value: Any) -> str:
    if not isinstance(value, str) or not value:
        return ""
    return (
        PureWindowsPath(value).name
        if "\\" in value or (len(value) >= 2 and value[1] == ":")
        else Path(value).name
    )


def _metadata(
    metadata: dict[str, Any], source: dict[str, str]
) -> tuple[float, dict[str, dict[str, Any]]]:
    timeline = metadata.get("timeline")
    raw_assets = metadata.get("assets")
    frame_rate = timeline.get("frame_rate") if isinstance(timeline, dict) else None
    if (
        not isinstance(frame_rate, (int, float))
        or isinstance(frame_rate, bool)
        or not math.isfinite(float(frame_rate))
        or float(frame_rate) <= 0
        or not isinstance(raw_assets, list)
    ):
        raise PauseCompactionError("Bounded editing metadata is invalid.")
    assets: dict[str, dict[str, Any]] = {}
    for asset in raw_assets:
        if not isinstance(asset, dict):
            raise PauseCompactionError("Asset editing metadata is invalid.")
        asset_id = asset.get("asset_id")
        name = asset.get("name")
        duration = asset.get("duration_frames")
        source_rate = asset.get("frame_rate")
        if (
            not isinstance(asset_id, str)
            or not isinstance(name, str)
            or not isinstance(duration, int)
            or isinstance(duration, bool)
            or duration < 2
            or duration > MAX_FRAME_VALUE + 1
            or not isinstance(source_rate, (int, float))
            or isinstance(source_rate, bool)
            or not math.isfinite(float(source_rate))
            or float(source_rate) <= 0
        ):
            raise PauseCompactionError("Asset editing metadata is invalid.")
        assets[asset_id] = asset
    for role in ("screen", "webcam"):
        asset_id = source[f"{role}_asset_id"]
        asset = assets.get(asset_id)
        if (
            asset is None
            or str(asset["name"]).casefold()
            != source[f"{role}_file_name"].casefold()
        ):
            raise PauseCompactionError(
                f"{role} plan file name does not match bounded asset metadata."
            )
    return float(frame_rate), assets


def _timeline_intervals(
    plan: dict[str, Any],
    synchronized_pair: dict[str, Any],
    assets: dict[str, dict[str, Any]],
) -> tuple[list[dict[str, int]], list[dict[str, int]], int]:
    inputs = synchronized_pair["inputs"]
    screen_start = max(0, -int(inputs["webcam_offset_ms"]))
    webcam_start = max(0, int(inputs["webcam_offset_ms"]))
    screen_duration = _frames_to_milliseconds(
        int(assets[inputs["screen_asset_id"]]["duration_frames"]),
        float(assets[inputs["screen_asset_id"]]["frame_rate"]),
    )
    webcam_duration = _frames_to_milliseconds(
        int(assets[inputs["webcam_asset_id"]]["duration_frames"]),
        float(assets[inputs["webcam_asset_id"]]["frame_rate"]),
    )
    source_duration = max(
        screen_start + screen_duration,
        webcam_start + webcam_duration,
    )
    pause_analysis = plan.get("pause_analysis")
    raw_cuts = (
        pause_analysis.get("proposed_cuts")
        if isinstance(pause_analysis, dict)
        else None
    )
    if not isinstance(raw_cuts, list) or len(raw_cuts) > MAX_CUTS:
        raise PauseCompactionError("Plan proposed cuts are missing or unbounded.")
    cuts: list[dict[str, int]] = []
    previous_end = 0
    for raw_cut in raw_cuts:
        if not isinstance(raw_cut, dict):
            raise PauseCompactionError("A proposed cut is invalid.")
        start = raw_cut.get("start_ms")
        end = raw_cut.get("end_ms")
        duration = raw_cut.get("duration_ms")
        if (
            not isinstance(start, int)
            or isinstance(start, bool)
            or not isinstance(end, int)
            or isinstance(end, bool)
            or not isinstance(duration, int)
            or isinstance(duration, bool)
            or start < previous_end
            or not start < end <= source_duration
            or duration != end - start
        ):
            raise PauseCompactionError(
                "Proposed cuts must be ordered, non-overlapping, and in bounds."
            )
        cuts.append({"start_ms": start, "end_ms": end, "duration_ms": duration})
        previous_end = end
    kept: list[dict[str, int]] = []
    cursor = 0
    output_cursor = 0
    for cut in cuts:
        if cursor < cut["start_ms"]:
            duration = cut["start_ms"] - cursor
            kept.append(
                {
                    "start_ms": cursor,
                    "end_ms": cut["start_ms"],
                    "duration_ms": duration,
                    "output_start_ms": output_cursor,
                }
            )
            output_cursor += duration
        cursor = cut["end_ms"]
    if cursor < source_duration:
        kept.append(
            {
                "start_ms": cursor,
                "end_ms": source_duration,
                "duration_ms": source_duration - cursor,
                "output_start_ms": output_cursor,
            }
        )
    if not kept:
        raise PauseCompactionError("Proposed cuts remove the entire source.")
    return cuts, kept, source_duration


def _placements(
    kept: list[dict[str, int]],
    synchronized_pair: dict[str, Any],
    source: dict[str, str],
    assets: dict[str, dict[str, Any]],
    timeline_frame_rate: float,
) -> list[dict[str, Any]]:
    offset = int(synchronized_pair["inputs"]["webcam_offset_ms"])
    roles = (
        ("screen_video", "screen", "video", 1, max(0, -offset)),
        ("screen_audio", "screen", "audio", 1, max(0, -offset)),
        ("webcam_video", "webcam", "video", 2, max(0, offset)),
    )
    placements: list[dict[str, Any]] = []
    for segment_index, interval in enumerate(kept):
        for role, asset_role, track_type, track_index, asset_start_ms in roles:
            asset_id = source[f"{asset_role}_asset_id"]
            asset = assets[asset_id]
            source_rate = float(asset["frame_rate"])
            asset_duration_ms = _frames_to_milliseconds(
                int(asset["duration_frames"]), source_rate
            )
            overlap_start = max(interval["start_ms"], asset_start_ms)
            overlap_end = min(
                interval["end_ms"], asset_start_ms + asset_duration_ms
            )
            if overlap_start >= overlap_end:
                continue
            source_start = _milliseconds_to_frames(
                overlap_start - asset_start_ms, source_rate
            )
            source_end_exclusive = _milliseconds_to_frames(
                overlap_end - asset_start_ms, source_rate
            )
            if source_end_exclusive <= source_start + 1:
                continue
            output_position_ms = (
                interval["output_start_ms"]
                + overlap_start
                - interval["start_ms"]
            )
            position_frames = _milliseconds_to_frames(
                output_position_ms, timeline_frame_rate
            )
            source_end_frame = source_end_exclusive - 1
            if (
                source_start > MAX_FRAME_VALUE
                or source_end_frame > MAX_FRAME_VALUE
                or position_frames > MAX_FRAME_VALUE
            ):
                raise PauseCompactionError(
                    "A kept-range placement exceeds bounded frame limits."
                )
            placements.append(
                {
                    "segment_index": segment_index,
                    "role": role,
                    "asset_id": asset_id,
                    "track_type": track_type,
                    "track_index": track_index,
                    "source_start_frame": source_start,
                    "source_end_frame": source_end_frame,
                    "position_frames": position_frames,
                    "source_frame_rate": source_rate,
                }
            )
    if not placements:
        raise PauseCompactionError("No bounded kept-range placements were produced.")
    return placements


def _milliseconds_to_frames(milliseconds: int, frame_rate: float) -> int:
    return math.floor(milliseconds * frame_rate / 1000.0 + 0.5)


def _frames_to_milliseconds(frames: int, frame_rate: float) -> int:
    return math.floor(frames * 1000.0 / frame_rate + 0.5)


def _canonical_sha256(payload: dict[str, Any]) -> str:
    canonical = json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()
