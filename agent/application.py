"""Provider-neutral application services exposed to user-facing adapters."""

from __future__ import annotations

import math
from collections.abc import Callable
from typing import Any, Protocol

from agent.audio_workflow import DialogueAudioWorkflow
from agent.bridge_state import (
    DEFAULT_HEARTBEAT_MAX_AGE_SECONDS,
    bridge_is_healthy,
    heartbeat_age_seconds,
    load_bridge_state,
)
from agent.media import MediaPolicy
from agent.rendering import (
    DEFAULT_RENDER_PROFILE,
    validate_render_job_id,
    validate_render_name,
    validate_render_profile,
    verify_render_output,
)
from agent.rough_cut import RoughCutPlanner, RoughCutReviewer
from providers.resolve import ResolveProviderClient

MAX_COMMAND_TIMEOUT_SECONDS = 300.0
MAX_FRAME_VALUE = 2_147_483_647
MAX_TRACK_INDEX = 128


class ResolveReader(Protocol):
    """Read-only Resolve operations required by the application layer."""

    def current_project(self, timeout_seconds: float = 30) -> dict[str, Any] | None:
        """Return the current project."""

    def timelines(self, timeout_seconds: float = 30) -> list[dict[str, Any]]:
        """Return timelines in the current project."""

    def current_timeline(
        self,
        timeout_seconds: float = 30,
    ) -> dict[str, Any] | None:
        """Return the current timeline."""

    def timeline_items(
        self,
        timeline_id: str,
        *,
        timeout_seconds: float = 30,
    ) -> dict[str, Any]:
        """Return bounded metadata for items in one timeline."""

    def media_pool_items(
        self,
        timeout_seconds: float = 30,
    ) -> dict[str, Any]:
        """Return bounded identity metadata for Media Pool items."""

    def workspace_snapshot(
        self,
        timeout_seconds: float = 30,
    ) -> dict[str, Any]:
        """Return the fixed read-only workspace view."""

    def render_environment(
        self,
        timeout_seconds: float = 30,
    ) -> dict[str, Any]:
        """Return documented render discovery information."""

    def import_media(
        self,
        paths: list[str],
        *,
        timeout_seconds: float = 30,
        idempotency_key: str | None = None,
    ) -> dict[str, Any]:
        """Import media files."""

    def create_timeline(
        self,
        name: str,
        *,
        timeout_seconds: float = 30,
        idempotency_key: str | None = None,
    ) -> dict[str, Any]:
        """Create an empty timeline."""

    def duplicate_timeline(
        self,
        timeline_id: str,
        name: str,
        *,
        timeout_seconds: float = 30,
        idempotency_key: str | None = None,
    ) -> dict[str, Any]:
        """Duplicate one existing timeline."""

    def set_current_timeline(
        self,
        timeline_id: str,
        *,
        timeout_seconds: float = 30,
        idempotency_key: str | None = None,
    ) -> dict[str, Any]:
        """Select one current timeline."""

    def append_clip(
        self,
        timeline_id: str,
        asset_id: str,
        *,
        timeout_seconds: float = 30,
        idempotency_key: str | None = None,
    ) -> dict[str, Any]:
        """Append an asset to a timeline."""

    def insert_clip(
        self,
        timeline_id: str,
        asset_id: str,
        source_start_frame: int,
        source_end_frame: int,
        position_frames: int,
        track_type: str,
        track_index: int,
        *,
        timeout_seconds: float = 30,
        idempotency_key: str | None = None,
    ) -> dict[str, Any]:
        """Insert a bounded source range on one timeline track."""

    def set_clip_enabled(
        self,
        timeline_id: str,
        timeline_item_id: str,
        enabled: bool,
        *,
        timeout_seconds: float = 30,
        idempotency_key: str | None = None,
    ) -> dict[str, Any]:
        """Set one timeline item's enabled state."""

    def set_clips_linked(
        self,
        timeline_id: str,
        timeline_item_ids: list[str],
        linked: bool,
        *,
        timeout_seconds: float = 30,
        idempotency_key: str | None = None,
    ) -> dict[str, Any]:
        """Link or unlink a bounded group of timeline items."""

    def set_clip_transform(
        self,
        timeline_id: str,
        timeline_item_id: str,
        *,
        position_x: float | None = None,
        position_y: float | None = None,
        zoom: float | None = None,
        rotation_degrees: float | None = None,
        opacity_percent: float | None = None,
        timeout_seconds: float = 30,
        idempotency_key: str | None = None,
    ) -> dict[str, Any]:
        """Apply one bounded provider-neutral video clip transform."""

    def delete_clip(
        self,
        timeline_id: str,
        timeline_item_id: str,
        *,
        confirm_delete: bool,
        timeout_seconds: float = 30,
        idempotency_key: str | None = None,
    ) -> dict[str, Any]:
        """Delete exactly one timeline item without ripple."""

    def add_marker(
        self,
        timeline_id: str,
        frame: int,
        color: str,
        name: str,
        note: str,
        duration: int,
        *,
        timeout_seconds: float = 30,
        idempotency_key: str | None = None,
    ) -> dict[str, Any]:
        """Add a timeline marker."""

    def prepare_render_job(
        self,
        custom_name: str,
        *,
        profile: str = DEFAULT_RENDER_PROFILE,
        timeout_seconds: float = 30,
        idempotency_key: str | None = None,
    ) -> dict[str, Any]:
        """Prepare one fixed render job."""

    def render_job_status(
        self,
        job_id: str,
        *,
        timeout_seconds: float = 30,
    ) -> dict[str, Any]:
        """Return the current status of one render job."""

    def start_render_job(
        self,
        job_id: str,
        *,
        timeout_seconds: float = 30,
        idempotency_key: str | None = None,
    ) -> dict[str, Any]:
        """Start one agent-prepared render job."""


class MediaImportPolicy(Protocol):
    """Security policy applied before media paths reach a provider."""

    def prepare_import(self, paths: list[str]) -> list[str]:
        """Validate paths and publish the bridge policy."""

    def validate_files(self, paths: list[str]) -> list[str]:
        """Validate paths without publishing a Resolve write policy."""


class RoughCutPlanBuilder(Protocol):
    """Provider-neutral draft planner required by the application layer."""

    def create_plan(
        self,
        *,
        screen_file: str,
        webcam_file: str,
        screen_audio_file: str,
        webcam_audio_file: str,
        speech_audio_file: str,
        timeline_name: str,
        max_sync_offset_ms: int = 30_000,
        pause_threshold_dbfs: float = -40.0,
        min_pause_duration_ms: int = 700,
        preserve_context_ms: int = 120,
    ) -> dict[str, Any]:
        """Create a review-only rough-cut plan."""


class RoughCutPlanReviewer(Protocol):
    """Explicit local approval boundary for one stored rough-cut plan."""

    def approve(
        self,
        plan_id: str,
        *,
        confirm_review: bool,
    ) -> dict[str, Any]:
        """Persist one idempotent approval record."""


class DialogueAudioProcessor(Protocol):
    """Provider-neutral M6 dialogue workflow."""

    def process(
        self,
        source_file: str,
        *,
        preset: str = "pcm-dialogue-level-v1",
    ) -> dict[str, Any]:
        """Create derived audio and a before/after report."""


class AgentApplication:
    """Coordinate core status and provider operations for external adapters."""

    def __init__(
        self,
        resolve: ResolveReader | None = None,
        state_loader: Callable[[], dict[str, Any]] = load_bridge_state,
        media_policy: MediaImportPolicy | None = None,
        rough_cut_planner: RoughCutPlanBuilder | None = None,
        rough_cut_reviewer: RoughCutPlanReviewer | None = None,
        audio_processor: DialogueAudioProcessor | None = None,
    ) -> None:
        self._resolve = ResolveProviderClient() if resolve is None else resolve
        self._state_loader = state_loader
        self._media_policy = media_policy
        self._rough_cut_planner = rough_cut_planner
        self._rough_cut_reviewer = rough_cut_reviewer
        self._audio_processor = audio_processor

    def status(
        self,
        max_age_seconds: int = DEFAULT_HEARTBEAT_MAX_AGE_SECONDS,
    ) -> dict[str, Any]:
        """Return cached bridge state with computed health information."""
        if max_age_seconds < 1:
            raise ValueError("max_age_seconds must be greater than zero.")

        state = self._state_loader()
        return {
            "healthy": bridge_is_healthy(
                state,
                max_age_seconds=max_age_seconds,
            ),
            "heartbeat_age_seconds": heartbeat_age_seconds(state),
            "bridge": state,
        }

    def resolve_get_project(
        self,
        timeout_seconds: float = 30,
    ) -> dict[str, Any] | None:
        """Return the current Resolve project through the provider."""
        return self._resolve.current_project(
            self._validated_timeout(timeout_seconds)
        )

    def resolve_list_timelines(
        self,
        timeout_seconds: float = 30,
    ) -> list[dict[str, Any]]:
        """Return Resolve timelines through the provider."""
        return self._resolve.timelines(self._validated_timeout(timeout_seconds))

    def resolve_get_timeline(
        self,
        timeout_seconds: float = 30,
    ) -> dict[str, Any] | None:
        """Return the current Resolve timeline through the provider."""
        return self._resolve.current_timeline(
            self._validated_timeout(timeout_seconds)
        )

    def resolve_list_timeline_items(
        self,
        timeline_id: str,
        timeout_seconds: float = 30,
    ) -> dict[str, Any]:
        """List addressable video/audio items in one Resolve timeline."""
        if not timeline_id or len(timeline_id) > 128:
            raise ValueError("timeline_id must contain 1 to 128 characters.")
        return self._resolve.timeline_items(
            timeline_id,
            timeout_seconds=self._validated_timeout(timeout_seconds),
        )

    def resolve_list_media_pool_items(
        self,
        timeout_seconds: float = 30,
    ) -> dict[str, Any]:
        """List addressable items in the current Resolve Media Pool."""
        return self._resolve.media_pool_items(
            self._validated_timeout(timeout_seconds)
        )

    def resolve_get_workspace_snapshot(
        self,
        timeout_seconds: float = 30,
    ) -> dict[str, Any]:
        """Collect the current Resolve workspace through one bridge command."""
        return self._resolve.workspace_snapshot(
            self._validated_timeout(timeout_seconds)
        )

    def resolve_get_render_options(
        self,
        timeout_seconds: float = 30,
    ) -> dict[str, Any]:
        """Return Resolve render options without modifying the project."""
        return self._resolve.render_environment(
            self._validated_timeout(timeout_seconds)
        )

    def resolve_import_media(
        self,
        paths: list[str],
        *,
        timeout_seconds: float = 30,
        idempotency_key: str | None = None,
    ) -> dict[str, Any]:
        """Validate and import media through the Resolve provider."""
        policy = (
            MediaPolicy.from_local_config()
            if self._media_policy is None
            else self._media_policy
        )
        normalized = policy.prepare_import(paths)
        return self._resolve.import_media(
            normalized,
            timeout_seconds=self._validated_timeout(timeout_seconds),
            idempotency_key=idempotency_key,
        )

    def resolve_create_timeline(
        self,
        name: str,
        *,
        timeout_seconds: float = 30,
        idempotency_key: str | None = None,
    ) -> dict[str, Any]:
        """Create a Resolve timeline."""
        if not name.strip():
            raise ValueError("Timeline name must not be empty.")
        return self._resolve.create_timeline(
            name,
            timeout_seconds=self._validated_timeout(timeout_seconds),
            idempotency_key=idempotency_key,
        )

    def resolve_append_clip(
        self,
        timeline_id: str,
        asset_id: str,
        *,
        timeout_seconds: float = 30,
        idempotency_key: str | None = None,
    ) -> dict[str, Any]:
        """Append a media asset to a Resolve timeline."""
        if not timeline_id or not asset_id:
            raise ValueError("timeline_id and asset_id must not be empty.")
        return self._resolve.append_clip(
            timeline_id,
            asset_id,
            timeout_seconds=self._validated_timeout(timeout_seconds),
            idempotency_key=idempotency_key,
        )

    def resolve_duplicate_timeline(
        self,
        timeline_id: str,
        name: str,
        *,
        timeout_seconds: float = 30,
        idempotency_key: str | None = None,
    ) -> dict[str, Any]:
        """Duplicate one Resolve timeline after a project backup."""
        if not timeline_id or len(timeline_id) > 128:
            raise ValueError(
                "timeline_id must contain 1 to 128 characters."
            )
        if not name.strip() or len(name) > 128:
            raise ValueError(
                "Timeline name must contain 1 to 128 characters."
            )
        return self._resolve.duplicate_timeline(
            timeline_id,
            name,
            timeout_seconds=self._validated_timeout(timeout_seconds),
            idempotency_key=idempotency_key,
        )

    def resolve_set_current_timeline(
        self,
        timeline_id: str,
        *,
        timeout_seconds: float = 30,
        idempotency_key: str | None = None,
    ) -> dict[str, Any]:
        """Select one existing Resolve timeline."""
        if not timeline_id or len(timeline_id) > 128:
            raise ValueError(
                "timeline_id must contain 1 to 128 characters."
            )
        return self._resolve.set_current_timeline(
            timeline_id,
            timeout_seconds=self._validated_timeout(timeout_seconds),
            idempotency_key=idempotency_key,
        )

    def resolve_insert_clip(
        self,
        timeline_id: str,
        asset_id: str,
        source_start_frame: int,
        source_end_frame: int,
        position_frames: int,
        track_type: str,
        track_index: int,
        *,
        timeout_seconds: float = 30,
        idempotency_key: str | None = None,
    ) -> dict[str, Any]:
        """Insert one bounded media range into a Resolve timeline."""
        if not timeline_id or not asset_id:
            raise ValueError("timeline_id and asset_id must not be empty.")
        if (
            not 0 <= source_start_frame < source_end_frame <= MAX_FRAME_VALUE
        ):
            raise ValueError(
                "source frames must be ordered within the supported range."
            )
        if not 0 <= position_frames <= MAX_FRAME_VALUE:
            raise ValueError("position_frames must be a non-negative integer.")
        if track_type not in {"video", "audio"}:
            raise ValueError("track_type must be 'video' or 'audio'.")
        if not 1 <= track_index <= MAX_TRACK_INDEX:
            raise ValueError("track_index must be between 1 and 128.")
        return self._resolve.insert_clip(
            timeline_id,
            asset_id,
            source_start_frame,
            source_end_frame,
            position_frames,
            track_type,
            track_index,
            timeout_seconds=self._validated_timeout(timeout_seconds),
            idempotency_key=idempotency_key,
        )

    def resolve_add_marker(
        self,
        timeline_id: str,
        frame: int,
        color: str,
        name: str = "",
        note: str = "",
        duration: int = 1,
        *,
        timeout_seconds: float = 30,
        idempotency_key: str | None = None,
    ) -> dict[str, Any]:
        """Add a marker to a Resolve timeline."""
        if not timeline_id or not color:
            raise ValueError("timeline_id and color must not be empty.")
        if frame < 0 or duration < 1:
            raise ValueError("frame must be non-negative and duration positive.")
        return self._resolve.add_marker(
            timeline_id,
            frame,
            color,
            name,
            note,
            duration,
            timeout_seconds=self._validated_timeout(timeout_seconds),
            idempotency_key=idempotency_key,
        )

    def resolve_set_clip_enabled(
        self,
        timeline_id: str,
        timeline_item_id: str,
        enabled: bool,
        *,
        timeout_seconds: float = 30,
        idempotency_key: str | None = None,
    ) -> dict[str, Any]:
        """Set one Resolve timeline item enabled state."""
        if not timeline_id or len(timeline_id) > 128:
            raise ValueError(
                "timeline_id must contain 1 to 128 characters."
            )
        if not timeline_item_id or len(timeline_item_id) > 128:
            raise ValueError(
                "timeline_item_id must contain 1 to 128 characters."
            )
        if not isinstance(enabled, bool):
            raise ValueError("enabled must be a boolean.")
        return self._resolve.set_clip_enabled(
            timeline_id,
            timeline_item_id,
            enabled,
            timeout_seconds=self._validated_timeout(timeout_seconds),
            idempotency_key=idempotency_key,
        )

    def resolve_set_clips_linked(
        self,
        timeline_id: str,
        timeline_item_ids: list[str],
        linked: bool,
        *,
        timeout_seconds: float = 30,
        idempotency_key: str | None = None,
    ) -> dict[str, Any]:
        """Link or unlink 2 to 16 unique timeline items after a backup."""
        if not timeline_id or len(timeline_id) > 128:
            raise ValueError(
                "timeline_id must contain 1 to 128 characters."
            )
        if (
            not isinstance(timeline_item_ids, list)
            or not 2 <= len(timeline_item_ids) <= 16
            or any(
                not isinstance(item_id, str)
                or not item_id
                or len(item_id) > 128
                for item_id in timeline_item_ids
            )
            or len(set(timeline_item_ids)) != len(timeline_item_ids)
        ):
            raise ValueError(
                "timeline_item_ids must contain 2 to 16 unique bounded IDs."
            )
        if not isinstance(linked, bool):
            raise ValueError("linked must be a boolean.")
        return self._resolve.set_clips_linked(
            timeline_id,
            timeline_item_ids,
            linked,
            timeout_seconds=self._validated_timeout(timeout_seconds),
            idempotency_key=idempotency_key,
        )

    def resolve_set_clip_transform(
        self,
        timeline_id: str,
        timeline_item_id: str,
        *,
        position_x: float | None = None,
        position_y: float | None = None,
        zoom: float | None = None,
        rotation_degrees: float | None = None,
        opacity_percent: float | None = None,
        timeout_seconds: float = 30,
        idempotency_key: str | None = None,
    ) -> dict[str, Any]:
        """Apply one bounded transform to a Resolve video timeline item."""
        for name, value in (
            ("timeline_id", timeline_id),
            ("timeline_item_id", timeline_item_id),
        ):
            if not value or len(value) > 128:
                raise ValueError(
                    f"{name} must contain 1 to 128 characters."
                )
        values = {
            "position_x": position_x,
            "position_y": position_y,
            "zoom": zoom,
            "rotation_degrees": rotation_degrees,
            "opacity_percent": opacity_percent,
        }
        if all(value is None for value in values.values()):
            raise ValueError("At least one transform value is required.")
        ranges = {
            "position_x": (-32_768.0, 32_768.0),
            "position_y": (-32_768.0, 32_768.0),
            "zoom": (0.0, 100.0),
            "rotation_degrees": (-360.0, 360.0),
            "opacity_percent": (0.0, 100.0),
        }
        for transform_name, transform_value in values.items():
            if transform_value is None:
                continue
            minimum, maximum = ranges[transform_name]
            if (
                isinstance(transform_value, bool)
                or not isinstance(transform_value, (int, float))
                or not math.isfinite(transform_value)
                or not minimum <= transform_value <= maximum
            ):
                raise ValueError(
                    f"{transform_name} must be a finite number from "
                    f"{minimum} to {maximum}."
                )
        return self._resolve.set_clip_transform(
            timeline_id,
            timeline_item_id,
            position_x=position_x,
            position_y=position_y,
            zoom=zoom,
            rotation_degrees=rotation_degrees,
            opacity_percent=opacity_percent,
            timeout_seconds=self._validated_timeout(timeout_seconds),
            idempotency_key=idempotency_key,
        )

    def resolve_delete_clip(
        self,
        timeline_id: str,
        timeline_item_id: str,
        *,
        confirm_delete: bool = False,
        timeout_seconds: float = 30,
        idempotency_key: str | None = None,
    ) -> dict[str, Any]:
        """Delete one timeline item only after explicit confirmation."""
        for field_name, value in (
            ("timeline_id", timeline_id),
            ("timeline_item_id", timeline_item_id),
        ):
            if not value or len(value) > 128:
                raise ValueError(
                    f"{field_name} must contain 1 to 128 characters."
                )
        if confirm_delete is not True:
            raise ValueError("confirm_delete must be true.")
        return self._resolve.delete_clip(
            timeline_id,
            timeline_item_id,
            confirm_delete=True,
            timeout_seconds=self._validated_timeout(timeout_seconds),
            idempotency_key=idempotency_key,
        )

    def resolve_prepare_render_job(
        self,
        custom_name: str,
        *,
        profile: str = DEFAULT_RENDER_PROFILE,
        timeout_seconds: float = 30,
        idempotency_key: str | None = None,
    ) -> dict[str, Any]:
        """Prepare one fixed render job without starting rendering."""
        normalized_name = validate_render_name(custom_name)
        normalized_profile = validate_render_profile(profile)
        return self._resolve.prepare_render_job(
            normalized_name,
            profile=normalized_profile.name,
            timeout_seconds=self._validated_timeout(timeout_seconds),
            idempotency_key=idempotency_key,
        )

    def resolve_get_render_job_status(
        self,
        job_id: str,
        *,
        timeout_seconds: float = 30,
    ) -> dict[str, Any]:
        """Return documented status for one Resolve render job."""
        normalized_job_id = validate_render_job_id(job_id)
        return self._resolve.render_job_status(
            normalized_job_id,
            timeout_seconds=self._validated_timeout(timeout_seconds),
        )

    def resolve_start_render_job(
        self,
        job_id: str,
        *,
        timeout_seconds: float = 30,
        idempotency_key: str | None = None,
    ) -> dict[str, Any]:
        """Start one agent-prepared Resolve render job."""
        normalized_job_id = validate_render_job_id(job_id)
        return self._resolve.start_render_job(
            normalized_job_id,
            timeout_seconds=self._validated_timeout(timeout_seconds),
            idempotency_key=idempotency_key,
        )

    def resolve_verify_render_output(
        self,
        job_id: str,
        *,
        timeout_seconds: float = 30,
    ) -> dict[str, Any]:
        """Verify that one completed job produced a managed non-empty MP4."""
        normalized_job_id = validate_render_job_id(job_id)
        render_status = self._resolve.render_job_status(
            normalized_job_id,
            timeout_seconds=self._validated_timeout(timeout_seconds),
        )
        return verify_render_output(render_status)

    def create_rough_cut(
        self,
        *,
        screen_file: str,
        webcam_file: str,
        screen_audio_file: str,
        webcam_audio_file: str,
        speech_audio_file: str,
        timeline_name: str,
        max_sync_offset_ms: int = 30_000,
        pause_threshold_dbfs: float = -40.0,
        min_pause_duration_ms: int = 700,
        preserve_context_ms: int = 120,
    ) -> dict[str, Any]:
        """Validate sources and create an M5 draft without changing Resolve."""
        policy = (
            MediaPolicy.from_local_config()
            if self._media_policy is None
            else self._media_policy
        )
        normalized = policy.validate_files(
            [
                screen_file,
                webcam_file,
                screen_audio_file,
                webcam_audio_file,
                speech_audio_file,
            ]
        )
        planner = (
            RoughCutPlanner()
            if self._rough_cut_planner is None
            else self._rough_cut_planner
        )
        return planner.create_plan(
            screen_file=normalized[0],
            webcam_file=normalized[1],
            screen_audio_file=normalized[2],
            webcam_audio_file=normalized[3],
            speech_audio_file=normalized[4],
            timeline_name=timeline_name,
            max_sync_offset_ms=max_sync_offset_ms,
            pause_threshold_dbfs=pause_threshold_dbfs,
            min_pause_duration_ms=min_pause_duration_ms,
            preserve_context_ms=preserve_context_ms,
        )

    def approve_rough_cut(
        self,
        plan_id: str,
        *,
        confirm_review: bool,
    ) -> dict[str, Any]:
        """Record explicit review without applying the plan to Resolve."""
        reviewer = (
            RoughCutReviewer()
            if self._rough_cut_reviewer is None
            else self._rough_cut_reviewer
        )
        return reviewer.approve(
            plan_id,
            confirm_review=confirm_review,
        )

    def clean_dialogue_audio(
        self,
        source_file: str,
        *,
        preset: str = "pcm-dialogue-level-v1",
    ) -> dict[str, Any]:
        """Create a derived WAV and report without calling Resolve."""
        policy = (
            MediaPolicy.from_local_config()
            if self._media_policy is None
            else self._media_policy
        )
        normalized = policy.validate_files([source_file])
        processor = (
            DialogueAudioWorkflow()
            if self._audio_processor is None
            else self._audio_processor
        )
        return processor.process(normalized[0], preset=preset)

    @staticmethod
    def _validated_timeout(timeout_seconds: float) -> float:
        if not 0 < timeout_seconds <= MAX_COMMAND_TIMEOUT_SECONDS:
            raise ValueError(
                "timeout_seconds must be greater than zero and no more than 300."
            )
        return timeout_seconds
