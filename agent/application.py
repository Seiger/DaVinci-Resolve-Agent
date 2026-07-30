"""Provider-neutral application services exposed to user-facing adapters."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any, Protocol

from agent.bridge_state import (
    DEFAULT_HEARTBEAT_MAX_AGE_SECONDS,
    bridge_is_healthy,
    heartbeat_age_seconds,
    load_bridge_state,
)
from agent.media import MediaPolicy
from agent.rough_cut import RoughCutPlanner
from providers.resolve import ResolveProviderClient

MAX_COMMAND_TIMEOUT_SECONDS = 300.0


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

    def append_clip(
        self,
        timeline_id: str,
        asset_id: str,
        *,
        timeout_seconds: float = 30,
        idempotency_key: str | None = None,
    ) -> dict[str, Any]:
        """Append an asset to a timeline."""

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


class AgentApplication:
    """Coordinate core status and provider operations for external adapters."""

    def __init__(
        self,
        resolve: ResolveReader | None = None,
        state_loader: Callable[[], dict[str, Any]] = load_bridge_state,
        media_policy: MediaImportPolicy | None = None,
        rough_cut_planner: RoughCutPlanBuilder | None = None,
    ) -> None:
        self._resolve = ResolveProviderClient() if resolve is None else resolve
        self._state_loader = state_loader
        self._media_policy = media_policy
        self._rough_cut_planner = rough_cut_planner

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

    @staticmethod
    def _validated_timeout(timeout_seconds: float) -> float:
        if not 0 < timeout_seconds <= MAX_COMMAND_TIMEOUT_SECONDS:
            raise ValueError(
                "timeout_seconds must be greater than zero and no more than 300."
            )
        return timeout_seconds
