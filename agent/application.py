"""Provider-neutral application services exposed to user-facing adapters."""

from __future__ import annotations

import math
from collections.abc import Callable
from typing import Any, Protocol, TypeVar

from agent.audio_workflow import AudioReportInspector, DialogueAudioWorkflow
from agent.bridge_state import (
    DEFAULT_HEARTBEAT_MAX_AGE_SECONDS,
    bridge_is_healthy,
    heartbeat_age_seconds,
    load_bridge_state,
)
from agent.finalized_render import FinalizedRenderPreparer
from agent.media import MediaPolicy
from agent.pause_compaction import PauseCompactionApplier, PauseCompactionPreviewer
from agent.pause_compaction_finalize import PauseCompactionFinalizer
from agent.picture_in_picture import PictureInPictureComposer
from agent.rendering import (
    DEFAULT_RENDER_PROFILE,
    validate_render_job_id,
    validate_render_name,
    validate_render_profile,
    verify_render_output,
)
from agent.rough_cut import (
    RoughCutInspector,
    RoughCutPlanner,
    RoughCutReviewer,
)
from agent.rough_cut_apply import RoughCutApplier
from agent.synchronized_link import SynchronizedScreenLinker
from agent.synchronized_pair import SynchronizedPairAssembler
from providers.resolve import ResolveProviderClient

MAX_COMMAND_TIMEOUT_SECONDS = 300.0
MAX_FRAME_VALUE = 2_147_483_647
MAX_TRACK_INDEX = 128
ApplicationResultT = TypeVar("ApplicationResultT")


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

    def editing_metadata(
        self,
        timeline_id: str,
        asset_ids: list[str],
        *,
        timeout_seconds: float = 30,
    ) -> dict[str, Any]:
        """Return placement-relevant media metadata and target track counts."""

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

    def stop_bridge(
        self,
        timeout_seconds: float = 30,
    ) -> dict[str, Any]:
        """Request clean shutdown of the persistent Resolve bridge."""

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

    def ensure_timeline_tracks(
        self,
        timeline_id: str,
        video_track_count: int,
        audio_track_count: int,
        *,
        timeout_seconds: float = 30,
        idempotency_key: str | None = None,
    ) -> dict[str, Any]:
        """Ensure bounded minimum timeline track counts."""

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

    def insert_clips(
        self,
        timeline_id: str,
        placements: list[dict[str, Any]],
        *,
        timeout_seconds: float = 30,
        idempotency_key: str | None = None,
    ) -> dict[str, Any]:
        """Insert bounded source ranges in one provider operation."""

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

    def set_clip_link_groups(
        self,
        timeline_id: str,
        groups: list[list[str]],
        linked: bool,
        *,
        timeout_seconds: float = 30,
        idempotency_key: str | None = None,
    ) -> dict[str, Any]:
        """Apply bounded independent link groups in one operation."""

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

    def set_clip_transforms(
        self,
        timeline_id: str,
        items: list[dict[str, Any]],
        *,
        timeout_seconds: float = 30,
        idempotency_key: str | None = None,
    ) -> dict[str, Any]:
        """Apply bounded video transforms in one provider operation."""

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
        timeline_id: str | None = None,
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


class RoughCutPlanInspector(Protocol):
    """Read-only access to validated local rough-cut artifacts."""

    def get_plan(self, plan_id: str) -> dict[str, Any]:
        """Return one draft and its effective approval state."""

    def list_plans(self, limit: int = 100) -> dict[str, Any]:
        """Return bounded plan summaries."""


class RoughCutPlanApplier(Protocol):
    """Preview or apply an approved rough-cut plan to a copied timeline."""

    def preview(
        self,
        plan_id: str,
        source_timeline_id: str,
        target_timeline_name: str,
    ) -> dict[str, Any]:
        """Return a write-free apply preview."""

    def apply(
        self,
        plan_id: str,
        source_timeline_id: str,
        target_timeline_name: str,
        *,
        confirm_apply: bool,
        timeout_seconds: float = 30,
    ) -> dict[str, Any]:
        """Apply the supported plan to the copied timeline."""


class SynchronizedPairWorkflow(Protocol):
    """Provider-neutral synchronized screen/webcam assembly boundary."""

    def assemble(
        self,
        *,
        timeline_name: str,
        screen_asset_id: str,
        webcam_asset_id: str,
        webcam_offset_ms: int,
        confirm_sync: bool,
        timeout_seconds: float = 30,
    ) -> dict[str, Any]:
        """Create and populate one synchronized V1/A1/V2 timeline."""


class PictureInPictureWorkflow(Protocol):
    """Provider-neutral synchronized webcam layout boundary."""

    def compose(
        self,
        *,
        synchronized_pair_receipt_id: str,
        size_percent: float,
        center_x_percent: float,
        center_y_percent: float,
        confirm_layout: bool,
        timeout_seconds: float = 30,
    ) -> dict[str, Any]:
        """Apply one normalized picture-in-picture webcam layout."""


class SynchronizedLinkWorkflow(Protocol):
    """Provider-neutral synchronized screen link boundary."""

    def link(
        self,
        *,
        synchronized_pair_receipt_id: str,
        confirm_link: bool,
        timeout_seconds: float = 30,
    ) -> dict[str, Any]:
        """Link canonical screen video/audio items from one M38 receipt."""


class PauseCompactionWorkflow(Protocol):
    """Provider-neutral pause-removal rebuild preview boundary."""

    def preview(
        self,
        *,
        plan_id: str,
        synchronized_pair_receipt_id: str,
        target_timeline_name: str,
        timeout_seconds: float = 30,
    ) -> dict[str, Any]:
        """Return kept-range V1/A1/V2 placements without editing Resolve."""


class PauseCompactionApplyWorkflow(Protocol):
    """Provider-neutral confirmed pause-removal rebuild boundary."""

    def apply(
        self,
        *,
        plan_id: str,
        synchronized_pair_receipt_id: str,
        target_timeline_name: str,
        confirm_apply: bool,
        timeout_seconds: float = 30,
    ) -> dict[str, Any]:
        """Create one new timeline from approved kept ranges."""


class PauseCompactionFinalizationWorkflow(Protocol):
    """Provider-neutral M42 segment finalization boundary."""

    def finalize(
        self,
        *,
        pause_compaction_receipt_id: str,
        picture_in_picture_receipt_id: str,
        synchronized_link_receipt_id: str,
        confirm_finalize: bool,
        timeout_seconds: float = 30,
    ) -> dict[str, Any]:
        """Propagate approved links and webcam layout to M42 segments."""


class FinalizedRenderPreparationWorkflow(Protocol):
    """Provider-neutral M44 finalized render preparation boundary."""

    def prepare(
        self,
        *,
        finalization_receipt_id: str,
        custom_name: str,
        profile: str,
        confirm_prepare: bool,
        timeout_seconds: float = 30,
    ) -> dict[str, Any]:
        """Prepare one render job bound to an applied M43 timeline."""


class DialogueAudioProcessor(Protocol):
    """Provider-neutral M6 dialogue workflow."""

    def process(
        self,
        source_file: str,
        *,
        preset: str = "pcm-dialogue-level-v1",
    ) -> dict[str, Any]:
        """Create derived audio and a before/after report."""


class AudioReportReader(Protocol):
    """Read-only access to validated local audio reports."""

    def get_report(self, report_id: str) -> dict[str, Any]:
        """Return one canonical before/after report."""

    def list_reports(self, limit: int = 100) -> dict[str, Any]:
        """Return bounded report summaries."""


class WorkflowOperationAuditor(Protocol):
    """Audit provider-neutral local operations without inspecting inputs."""

    def run(
        self,
        operation: str,
        callback: Callable[[], ApplicationResultT],
    ) -> ApplicationResultT:
        """Run one allowlisted local operation with lifecycle audit."""


class AgentApplication:
    """Coordinate core status and provider operations for external adapters."""

    def __init__(
        self,
        resolve: ResolveReader | None = None,
        state_loader: Callable[[], dict[str, Any]] = load_bridge_state,
        media_policy: MediaImportPolicy | None = None,
        rough_cut_planner: RoughCutPlanBuilder | None = None,
        rough_cut_reviewer: RoughCutPlanReviewer | None = None,
        rough_cut_inspector: RoughCutPlanInspector | None = None,
        rough_cut_applier: RoughCutPlanApplier | None = None,
        synchronized_pair_assembler: SynchronizedPairWorkflow | None = None,
        picture_in_picture_composer: PictureInPictureWorkflow | None = None,
        synchronized_screen_linker: SynchronizedLinkWorkflow | None = None,
        pause_compaction_previewer: PauseCompactionWorkflow | None = None,
        pause_compaction_applier: PauseCompactionApplyWorkflow | None = None,
        pause_compaction_finalizer: PauseCompactionFinalizationWorkflow | None = None,
        finalized_render_preparer: FinalizedRenderPreparationWorkflow | None = None,
        audio_processor: DialogueAudioProcessor | None = None,
        audio_report_inspector: AudioReportReader | None = None,
        workflow_audit: WorkflowOperationAuditor | None = None,
    ) -> None:
        self._resolve = ResolveProviderClient() if resolve is None else resolve
        self._state_loader = state_loader
        self._media_policy = media_policy
        self._rough_cut_planner = rough_cut_planner
        self._rough_cut_reviewer = rough_cut_reviewer
        self._rough_cut_inspector = rough_cut_inspector
        self._rough_cut_applier = rough_cut_applier
        self._synchronized_pair_assembler = synchronized_pair_assembler
        self._picture_in_picture_composer = picture_in_picture_composer
        self._synchronized_screen_linker = synchronized_screen_linker
        self._pause_compaction_previewer = pause_compaction_previewer
        self._pause_compaction_applier = pause_compaction_applier
        self._pause_compaction_finalizer = pause_compaction_finalizer
        self._finalized_render_preparer = finalized_render_preparer
        self._audio_processor = audio_processor
        self._audio_report_inspector = audio_report_inspector
        self._workflow_audit = workflow_audit

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

    def resolve_get_editing_metadata(
        self,
        timeline_id: str,
        asset_ids: list[str],
        timeout_seconds: float = 30,
    ) -> dict[str, Any]:
        """Read documented source duration/FPS and target timeline tracks."""
        if not timeline_id or len(timeline_id) > 128:
            raise ValueError("timeline_id must contain 1 to 128 characters.")
        if (
            not 1 <= len(asset_ids) <= 100
            or len(set(asset_ids)) != len(asset_ids)
            or not all(
                isinstance(asset_id, str)
                and 1 <= len(asset_id) <= 128
                for asset_id in asset_ids
            )
        ):
            raise ValueError(
                "asset_ids must contain 1 to 100 unique identifiers of up to "
                "128 characters."
            )
        return self._resolve.editing_metadata(
            timeline_id,
            asset_ids,
            timeout_seconds=self._validated_timeout(timeout_seconds),
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

    def resolve_stop_bridge(
        self,
        timeout_seconds: float = 30,
    ) -> dict[str, Any]:
        """Request clean shutdown without changing the Resolve project."""
        return self._resolve.stop_bridge(
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

    def resolve_ensure_timeline_tracks(
        self,
        timeline_id: str,
        video_track_count: int,
        audio_track_count: int,
        *,
        timeout_seconds: float = 30,
        idempotency_key: str | None = None,
    ) -> dict[str, Any]:
        """Ensure the timeline has bounded minimum video/audio tracks."""
        if not timeline_id or len(timeline_id) > 128:
            raise ValueError("timeline_id must contain 1 to 128 characters.")
        for field, value in (
            ("video_track_count", video_track_count),
            ("audio_track_count", audio_track_count),
        ):
            if (
                not isinstance(value, int)
                or isinstance(value, bool)
                or not 1 <= value <= 8
            ):
                raise ValueError(f"{field} must be between 1 and 8.")
        return self._resolve.ensure_timeline_tracks(
            timeline_id,
            video_track_count,
            audio_track_count,
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
        timeline_id: str | None = None,
        profile: str = DEFAULT_RENDER_PROFILE,
        timeout_seconds: float = 30,
        idempotency_key: str | None = None,
    ) -> dict[str, Any]:
        """Prepare one fixed render job without starting rendering."""
        normalized_name = validate_render_name(custom_name)
        normalized_profile = validate_render_profile(profile)
        if timeline_id is not None and (
            not timeline_id or len(timeline_id) > 128
        ):
            raise ValueError("timeline_id must contain 1 to 128 characters.")
        return self._resolve.prepare_render_job(
            normalized_name,
            timeline_id=timeline_id,
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
        def execute() -> dict[str, Any]:
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

        return self._run_local_workflow("create_rough_cut", execute)

    def approve_rough_cut(
        self,
        plan_id: str,
        *,
        confirm_review: bool,
    ) -> dict[str, Any]:
        """Record explicit review without applying the plan to Resolve."""
        def execute() -> dict[str, Any]:
            reviewer = (
                RoughCutReviewer()
                if self._rough_cut_reviewer is None
                else self._rough_cut_reviewer
            )
            return reviewer.approve(
                plan_id,
                confirm_review=confirm_review,
            )

        return self._run_local_workflow("approve_rough_cut", execute)

    def get_rough_cut_plan(self, plan_id: str) -> dict[str, Any]:
        """Return one validated draft and approval without changing either."""
        return self._run_local_workflow(
            "get_rough_cut_plan",
            lambda: (
                RoughCutInspector()
                if self._rough_cut_inspector is None
                else self._rough_cut_inspector
            ).get_plan(plan_id),
        )

    def list_rough_cut_plans(self, limit: int = 100) -> dict[str, Any]:
        """Return bounded summaries for locally stored rough-cut plans."""
        return self._run_local_workflow(
            "list_rough_cut_plans",
            lambda: (
                RoughCutInspector()
                if self._rough_cut_inspector is None
                else self._rough_cut_inspector
            ).list_plans(limit),
        )

    def preview_rough_cut_apply(
        self,
        plan_id: str,
        source_timeline_id: str,
        target_timeline_name: str,
    ) -> dict[str, Any]:
        """Preview M34 application without sending a Resolve command."""
        return self._run_local_workflow(
            "preview_rough_cut_apply",
            lambda: self._rough_cut_apply_service().preview(
                plan_id,
                source_timeline_id,
                target_timeline_name,
            ),
        )

    def apply_rough_cut(
        self,
        plan_id: str,
        source_timeline_id: str,
        target_timeline_name: str,
        *,
        confirm_apply: bool,
        timeout_seconds: float = 30,
    ) -> dict[str, Any]:
        """Apply an approved and fully supported plan only to a timeline copy."""
        return self._run_local_workflow(
            "apply_rough_cut",
            lambda: self._rough_cut_apply_service().apply(
                plan_id,
                source_timeline_id,
                target_timeline_name,
                confirm_apply=confirm_apply,
                timeout_seconds=self._validated_timeout(timeout_seconds),
            ),
        )

    def sync_screen_and_webcam(
        self,
        *,
        timeline_name: str,
        screen_asset_id: str,
        webcam_asset_id: str,
        webcam_offset_ms: int,
        confirm_sync: bool,
        timeout_seconds: float = 30,
    ) -> dict[str, Any]:
        """Create a timeline and place one synchronized screen/webcam pair."""
        return self._run_local_workflow(
            "sync_screen_and_webcam",
            lambda: self._synchronized_pair_service().assemble(
                timeline_name=timeline_name,
                screen_asset_id=screen_asset_id,
                webcam_asset_id=webcam_asset_id,
                webcam_offset_ms=webcam_offset_ms,
                confirm_sync=confirm_sync,
                timeout_seconds=self._validated_timeout(timeout_seconds),
            ),
        )

    def _synchronized_pair_service(self) -> SynchronizedPairWorkflow:
        if self._synchronized_pair_assembler is not None:
            return self._synchronized_pair_assembler
        return SynchronizedPairAssembler(
            gateway=self._resolve,
            capabilities=lambda: self.status()["bridge"].get(
                "capabilities", {}
            ),
        )

    def compose_webcam_picture_in_picture(
        self,
        *,
        synchronized_pair_receipt_id: str,
        size_percent: float = 25.0,
        center_x_percent: float = 82.0,
        center_y_percent: float = 82.0,
        confirm_layout: bool,
        timeout_seconds: float = 30,
    ) -> dict[str, Any]:
        """Apply a normalized layout to the webcam item created by M38."""
        return self._run_local_workflow(
            "compose_webcam_picture_in_picture",
            lambda: self._picture_in_picture_service().compose(
                synchronized_pair_receipt_id=synchronized_pair_receipt_id,
                size_percent=size_percent,
                center_x_percent=center_x_percent,
                center_y_percent=center_y_percent,
                confirm_layout=confirm_layout,
                timeout_seconds=self._validated_timeout(timeout_seconds),
            ),
        )

    def _picture_in_picture_service(self) -> PictureInPictureWorkflow:
        if self._picture_in_picture_composer is not None:
            return self._picture_in_picture_composer
        return PictureInPictureComposer(
            gateway=self._resolve,
            capabilities=lambda: self.status()["bridge"].get(
                "capabilities", {}
            ),
        )

    def link_synchronized_screen_pair(
        self,
        *,
        synchronized_pair_receipt_id: str,
        confirm_link: bool,
        timeout_seconds: float = 30,
    ) -> dict[str, Any]:
        """Link the screen video/audio items created by M38."""
        return self._run_local_workflow(
            "link_synchronized_screen_pair",
            lambda: self._synchronized_link_service().link(
                synchronized_pair_receipt_id=synchronized_pair_receipt_id,
                confirm_link=confirm_link,
                timeout_seconds=self._validated_timeout(timeout_seconds),
            ),
        )

    def _synchronized_link_service(self) -> SynchronizedLinkWorkflow:
        if self._synchronized_screen_linker is not None:
            return self._synchronized_screen_linker
        return SynchronizedScreenLinker(
            gateway=self._resolve,
            capabilities=lambda: self.status()["bridge"].get(
                "capabilities", {}
            ),
        )

    def preview_synchronized_pause_compaction(
        self,
        *,
        plan_id: str,
        synchronized_pair_receipt_id: str,
        target_timeline_name: str,
        timeout_seconds: float = 30,
    ) -> dict[str, Any]:
        """Preview rebuilding a synchronized timeline from kept ranges."""
        return self._run_local_workflow(
            "preview_synchronized_pause_compaction",
            lambda: self._pause_compaction_service().preview(
                plan_id=plan_id,
                synchronized_pair_receipt_id=synchronized_pair_receipt_id,
                target_timeline_name=target_timeline_name,
                timeout_seconds=self._validated_timeout(timeout_seconds),
            ),
        )

    def _pause_compaction_service(self) -> PauseCompactionWorkflow:
        if self._pause_compaction_previewer is not None:
            return self._pause_compaction_previewer
        return PauseCompactionPreviewer(
            gateway=self._resolve,
            capabilities=self.status()["bridge"].get("capabilities", {}),
            inspector=(
                None
                if self._rough_cut_inspector is None
                else self._rough_cut_inspector
            ),
        )

    def apply_synchronized_pause_compaction(
        self,
        *,
        plan_id: str,
        synchronized_pair_receipt_id: str,
        target_timeline_name: str,
        confirm_apply: bool,
        timeout_seconds: float = 30,
    ) -> dict[str, Any]:
        """Create a new compacted synchronized timeline after confirmation."""
        return self._run_local_workflow(
            "apply_synchronized_pause_compaction",
            lambda: self._pause_compaction_apply_service().apply(
                plan_id=plan_id,
                synchronized_pair_receipt_id=synchronized_pair_receipt_id,
                target_timeline_name=target_timeline_name,
                confirm_apply=confirm_apply,
                timeout_seconds=self._validated_timeout(timeout_seconds),
            ),
        )

    def _pause_compaction_apply_service(self) -> PauseCompactionApplyWorkflow:
        if self._pause_compaction_applier is not None:
            return self._pause_compaction_applier
        def capabilities() -> dict[str, Any]:
            discovered = self.status()["bridge"].get("capabilities", {})
            return discovered if isinstance(discovered, dict) else {}

        previewer = PauseCompactionPreviewer(
            gateway=self._resolve,
            capabilities=capabilities(),
            inspector=(
                None
                if self._rough_cut_inspector is None
                else self._rough_cut_inspector
            ),
        )
        return PauseCompactionApplier(
            gateway=self._resolve,
            capabilities=capabilities,
            previewer=previewer,
        )

    def finalize_synchronized_pause_compaction(
        self,
        *,
        pause_compaction_receipt_id: str,
        picture_in_picture_receipt_id: str,
        synchronized_link_receipt_id: str,
        confirm_finalize: bool,
        timeout_seconds: float = 30,
    ) -> dict[str, Any]:
        """Propagate approved link and layout state to compacted segments."""
        return self._run_local_workflow(
            "finalize_synchronized_pause_compaction",
            lambda: self._pause_compaction_finalization_service().finalize(
                pause_compaction_receipt_id=pause_compaction_receipt_id,
                picture_in_picture_receipt_id=picture_in_picture_receipt_id,
                synchronized_link_receipt_id=synchronized_link_receipt_id,
                confirm_finalize=confirm_finalize,
                timeout_seconds=self._validated_timeout(timeout_seconds),
            ),
        )

    def _pause_compaction_finalization_service(
        self,
    ) -> PauseCompactionFinalizationWorkflow:
        if self._pause_compaction_finalizer is not None:
            return self._pause_compaction_finalizer

        def capabilities() -> dict[str, Any]:
            discovered = self.status()["bridge"].get("capabilities", {})
            return discovered if isinstance(discovered, dict) else {}

        return PauseCompactionFinalizer(
            gateway=self._resolve,
            capabilities=capabilities,
        )

    def prepare_finalized_timeline_render(
        self,
        *,
        finalization_receipt_id: str,
        custom_name: str,
        profile: str = DEFAULT_RENDER_PROFILE,
        confirm_prepare: bool,
        timeout_seconds: float = 30,
    ) -> dict[str, Any]:
        """Prepare a fixed render job for one applied M43 timeline."""
        return self._run_local_workflow(
            "prepare_finalized_timeline_render",
            lambda: self._finalized_render_preparation_service().prepare(
                finalization_receipt_id=finalization_receipt_id,
                custom_name=custom_name,
                profile=profile,
                confirm_prepare=confirm_prepare,
                timeout_seconds=self._validated_timeout(timeout_seconds),
            ),
        )

    def _finalized_render_preparation_service(
        self,
    ) -> FinalizedRenderPreparationWorkflow:
        if self._finalized_render_preparer is not None:
            return self._finalized_render_preparer

        def capabilities() -> dict[str, Any]:
            discovered = self.status()["bridge"].get("capabilities", {})
            return discovered if isinstance(discovered, dict) else {}

        return FinalizedRenderPreparer(
            gateway=self._resolve,
            capabilities=capabilities,
        )

    def _rough_cut_apply_service(self) -> RoughCutPlanApplier:
        if self._rough_cut_applier is not None:
            return self._rough_cut_applier
        return RoughCutApplier(
            capabilities=lambda: self.status()["bridge"].get("capabilities", {}),
            duplicate_timeline=lambda source_id, name, key, timeout_seconds: (
                self.resolve_duplicate_timeline(
                    source_id,
                    name,
                    timeout_seconds=timeout_seconds,
                    idempotency_key=key,
                )
            ),
        )

    def clean_dialogue_audio(
        self,
        source_file: str,
        *,
        preset: str = "pcm-dialogue-level-v1",
    ) -> dict[str, Any]:
        """Create a derived WAV and report without calling Resolve."""
        def execute() -> dict[str, Any]:
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

        return self._run_local_workflow("clean_dialogue_audio", execute)

    def get_audio_report(self, report_id: str) -> dict[str, Any]:
        """Return one validated report without processing media."""
        return self._run_local_workflow(
            "get_audio_report",
            lambda: (
                AudioReportInspector()
                if self._audio_report_inspector is None
                else self._audio_report_inspector
            ).get_report(report_id),
        )

    def list_audio_reports(self, limit: int = 100) -> dict[str, Any]:
        """Return bounded summaries for locally stored audio reports."""
        return self._run_local_workflow(
            "list_audio_reports",
            lambda: (
                AudioReportInspector()
                if self._audio_report_inspector is None
                else self._audio_report_inspector
            ).list_reports(limit),
        )

    def _run_local_workflow(
        self,
        operation: str,
        callback: Callable[[], ApplicationResultT],
    ) -> ApplicationResultT:
        if self._workflow_audit is None:
            return callback()
        return self._workflow_audit.run(operation, callback)

    @staticmethod
    def _validated_timeout(timeout_seconds: float) -> float:
        if not 0 < timeout_seconds <= MAX_COMMAND_TIMEOUT_SECONDS:
            raise ValueError(
                "timeout_seconds must be greater than zero and no more than 300."
            )
        return timeout_seconds
