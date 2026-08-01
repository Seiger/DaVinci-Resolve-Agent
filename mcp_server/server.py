"""Local stdio MCP server exposing the fixed application API."""

from __future__ import annotations

import asyncio
from typing import Any

from mcp.server import MCPServer
from mcp.types import ToolAnnotations

from agent import __version__
from agent.application import AgentApplication
from agent.rendering import DEFAULT_RENDER_PROFILE
from agent.workflow_audit import WorkflowAuditLog

READ_ONLY_TOOL = ToolAnnotations(
    read_only_hint=True,
    destructive_hint=False,
    idempotent_hint=True,
    open_world_hint=False,
)
WRITE_TOOL = ToolAnnotations(
    read_only_hint=False,
    destructive_hint=False,
    idempotent_hint=True,
    open_world_hint=False,
)
DESTRUCTIVE_WRITE_TOOL = ToolAnnotations(
    read_only_hint=False,
    destructive_hint=True,
    idempotent_hint=True,
    open_world_hint=False,
)


def create_server(application: AgentApplication | None = None) -> MCPServer:
    """Create an MCP server bound to an application service."""
    service = (
        AgentApplication(workflow_audit=WorkflowAuditLog())
        if application is None
        else application
    )
    server = MCPServer(
        name="davinci-resolve-agent",
        version=__version__,
    instructions=(
            "Local access to DaVinci Resolve Agent. "
            "The Resolve tools require the one-shot ResolveBridge script to be "
            "launched inside DaVinci Resolve while the request is waiting. "
            "Rough-cut and audio workflows run locally without changing Resolve."
        ),
    )

    @server.tool(annotations=READ_ONLY_TOOL)
    async def video_agent_status(
        max_age_seconds: int = 120,
    ) -> dict[str, Any]:
        """Return cached bridge status without sending a Resolve command."""
        return await asyncio.to_thread(service.status, max_age_seconds)

    @server.tool(annotations=READ_ONLY_TOOL)
    async def resolve_get_project(
        timeout_seconds: float = 30,
    ) -> dict[str, Any]:
        """Return the current Resolve project."""
        project = await asyncio.to_thread(
            service.resolve_get_project,
            timeout_seconds,
        )
        return {"project": project}

    @server.tool(annotations=WRITE_TOOL)
    async def resolve_stop_bridge(
        timeout_seconds: float = 30,
    ) -> dict[str, Any]:
        """Stop the manually launched persistent bridge cleanly."""
        return await asyncio.to_thread(service.resolve_stop_bridge, timeout_seconds)

    @server.tool(annotations=READ_ONLY_TOOL)
    async def resolve_list_timelines(
        timeout_seconds: float = 30,
    ) -> dict[str, Any]:
        """List timelines in the current Resolve project."""
        timelines = await asyncio.to_thread(
            service.resolve_list_timelines,
            timeout_seconds,
        )
        return {"timelines": timelines}

    @server.tool(annotations=READ_ONLY_TOOL)
    async def resolve_get_timeline(
        timeout_seconds: float = 30,
    ) -> dict[str, Any]:
        """Return the current Resolve timeline."""
        timeline = await asyncio.to_thread(
            service.resolve_get_timeline,
            timeout_seconds,
        )
        return {"timeline": timeline}

    @server.tool(annotations=READ_ONLY_TOOL)
    async def resolve_list_timeline_items(
        timeline_id: str,
        timeout_seconds: float = 30,
    ) -> dict[str, Any]:
        """List bounded metadata for video/audio items in one timeline."""
        return await asyncio.to_thread(
            service.resolve_list_timeline_items,
            timeline_id,
            timeout_seconds,
        )

    @server.tool(annotations=READ_ONLY_TOOL)
    async def resolve_list_media_pool_items(
        timeout_seconds: float = 30,
    ) -> dict[str, Any]:
        """List bounded identities for items in the current Media Pool."""
        return await asyncio.to_thread(
            service.resolve_list_media_pool_items,
            timeout_seconds,
        )

    @server.tool(annotations=READ_ONLY_TOOL)
    async def resolve_get_editing_metadata(
        timeline_id: str,
        asset_ids: list[str],
        timeout_seconds: float = 30,
    ) -> dict[str, Any]:
        """Read source frame count/FPS and target video/audio track counts."""
        return await asyncio.to_thread(
            service.resolve_get_editing_metadata,
            timeline_id,
            asset_ids,
            timeout_seconds,
        )

    @server.tool(annotations=READ_ONLY_TOOL)
    async def resolve_get_workspace_snapshot(
        timeout_seconds: float = 30,
    ) -> dict[str, Any]:
        """Collect project, timeline, Media Pool, and render discovery once."""
        return await asyncio.to_thread(
            service.resolve_get_workspace_snapshot,
            timeout_seconds,
        )

    @server.tool(annotations=READ_ONLY_TOOL)
    async def resolve_get_render_options(
        timeout_seconds: float = 30,
    ) -> dict[str, Any]:
        """Discover documented render formats, codecs, presets, and jobs."""
        return await asyncio.to_thread(
            service.resolve_get_render_options,
            timeout_seconds,
        )

    @server.tool(annotations=WRITE_TOOL)
    async def resolve_import_media(
        paths: list[str],
        timeout_seconds: float = 30,
        idempotency_key: str | None = None,
    ) -> dict[str, Any]:
        """Import allowlisted local media after exporting a project backup."""
        return await asyncio.to_thread(
            service.resolve_import_media,
            paths,
            timeout_seconds=timeout_seconds,
            idempotency_key=idempotency_key,
        )

    @server.tool(annotations=WRITE_TOOL)
    async def resolve_create_timeline(
        name: str,
        timeout_seconds: float = 30,
        idempotency_key: str | None = None,
    ) -> dict[str, Any]:
        """Create an empty timeline after exporting a project backup."""
        return await asyncio.to_thread(
            service.resolve_create_timeline,
            name,
            timeout_seconds=timeout_seconds,
            idempotency_key=idempotency_key,
        )

    @server.tool(annotations=WRITE_TOOL)
    async def resolve_ensure_timeline_tracks(
        timeline_id: str,
        video_track_count: int,
        audio_track_count: int,
        timeout_seconds: float = 30,
        idempotency_key: str | None = None,
    ) -> dict[str, Any]:
        """Ensure 1-8 video/audio tracks after exporting a backup."""
        return await asyncio.to_thread(
            service.resolve_ensure_timeline_tracks,
            timeline_id,
            video_track_count,
            audio_track_count,
            timeout_seconds=timeout_seconds,
            idempotency_key=idempotency_key,
        )

    @server.tool(annotations=WRITE_TOOL)
    async def resolve_duplicate_timeline(
        timeline_id: str,
        name: str,
        timeout_seconds: float = 30,
        idempotency_key: str | None = None,
    ) -> dict[str, Any]:
        """Duplicate one timeline after exporting a project backup."""
        return await asyncio.to_thread(
            service.resolve_duplicate_timeline,
            timeline_id,
            name,
            timeout_seconds=timeout_seconds,
            idempotency_key=idempotency_key,
        )

    @server.tool(annotations=WRITE_TOOL)
    async def resolve_set_current_timeline(
        timeline_id: str,
        timeout_seconds: float = 30,
        idempotency_key: str | None = None,
    ) -> dict[str, Any]:
        """Select one existing timeline after exporting a project backup."""
        return await asyncio.to_thread(
            service.resolve_set_current_timeline,
            timeline_id,
            timeout_seconds=timeout_seconds,
            idempotency_key=idempotency_key,
        )

    @server.tool(annotations=WRITE_TOOL)
    async def resolve_append_clip(
        timeline_id: str,
        asset_id: str,
        timeout_seconds: float = 30,
        idempotency_key: str | None = None,
    ) -> dict[str, Any]:
        """Append a media asset after exporting a project backup."""
        return await asyncio.to_thread(
            service.resolve_append_clip,
            timeline_id,
            asset_id,
            timeout_seconds=timeout_seconds,
            idempotency_key=idempotency_key,
        )

    @server.tool(annotations=WRITE_TOOL)
    async def resolve_insert_clip(
        timeline_id: str,
        asset_id: str,
        source_start_frame: int,
        source_end_frame: int,
        position_frames: int,
        track_type: str,
        track_index: int,
        timeout_seconds: float = 30,
        idempotency_key: str | None = None,
    ) -> dict[str, Any]:
        """Insert one bounded source range after exporting a project backup."""
        return await asyncio.to_thread(
            service.resolve_insert_clip,
            timeline_id,
            asset_id,
            source_start_frame,
            source_end_frame,
            position_frames,
            track_type,
            track_index,
            timeout_seconds=timeout_seconds,
            idempotency_key=idempotency_key,
        )

    @server.tool(annotations=WRITE_TOOL)
    async def resolve_set_clip_enabled(
        timeline_id: str,
        timeline_item_id: str,
        enabled: bool,
        timeout_seconds: float = 30,
        idempotency_key: str | None = None,
    ) -> dict[str, Any]:
        """Set one timeline item enabled state after exporting a backup."""
        return await asyncio.to_thread(
            service.resolve_set_clip_enabled,
            timeline_id,
            timeline_item_id,
            enabled,
            timeout_seconds=timeout_seconds,
            idempotency_key=idempotency_key,
        )

    @server.tool(annotations=WRITE_TOOL)
    async def resolve_set_clips_linked(
        timeline_id: str,
        timeline_item_ids: list[str],
        linked: bool,
        timeout_seconds: float = 30,
        idempotency_key: str | None = None,
    ) -> dict[str, Any]:
        """Link or unlink 2 to 16 timeline items after exporting a backup."""
        return await asyncio.to_thread(
            service.resolve_set_clips_linked,
            timeline_id,
            timeline_item_ids,
            linked,
            timeout_seconds=timeout_seconds,
            idempotency_key=idempotency_key,
        )

    @server.tool(annotations=WRITE_TOOL)
    async def resolve_set_clip_transform(
        timeline_id: str,
        timeline_item_id: str,
        position_x: float | None = None,
        position_y: float | None = None,
        zoom: float | None = None,
        rotation_degrees: float | None = None,
        opacity_percent: float | None = None,
        timeout_seconds: float = 30,
        idempotency_key: str | None = None,
    ) -> dict[str, Any]:
        """Apply one fixed bounded video clip transform after a backup."""
        return await asyncio.to_thread(
            service.resolve_set_clip_transform,
            timeline_id,
            timeline_item_id,
            position_x=position_x,
            position_y=position_y,
            zoom=zoom,
            rotation_degrees=rotation_degrees,
            opacity_percent=opacity_percent,
            timeout_seconds=timeout_seconds,
            idempotency_key=idempotency_key,
        )

    @server.tool(annotations=DESTRUCTIVE_WRITE_TOOL)
    async def resolve_delete_clip(
        timeline_id: str,
        timeline_item_id: str,
        confirm_delete: bool = False,
        timeout_seconds: float = 30,
        idempotency_key: str | None = None,
    ) -> dict[str, Any]:
        """Delete exactly one timeline item without ripple after confirmation."""
        return await asyncio.to_thread(
            service.resolve_delete_clip,
            timeline_id,
            timeline_item_id,
            confirm_delete=confirm_delete,
            timeout_seconds=timeout_seconds,
            idempotency_key=idempotency_key,
        )

    @server.tool(annotations=WRITE_TOOL)
    async def resolve_add_marker(
        timeline_id: str,
        frame: int,
        color: str,
        name: str = "",
        note: str = "",
        duration: int = 1,
        timeout_seconds: float = 30,
        idempotency_key: str | None = None,
    ) -> dict[str, Any]:
        """Add a timeline marker after exporting a project backup."""
        return await asyncio.to_thread(
            service.resolve_add_marker,
            timeline_id,
            frame,
            color,
            name,
            note,
            duration,
            timeout_seconds=timeout_seconds,
            idempotency_key=idempotency_key,
        )

    @server.tool(annotations=WRITE_TOOL)
    async def resolve_prepare_render_job(
        custom_name: str,
        timeline_id: str | None = None,
        profile: str = DEFAULT_RENDER_PROFILE,
        timeout_seconds: float = 30,
        idempotency_key: str | None = None,
    ) -> dict[str, Any]:
        """Add a fixed MP4/H264 job after backup without starting render."""
        return await asyncio.to_thread(
            service.resolve_prepare_render_job,
            custom_name,
            timeline_id=timeline_id,
            profile=profile,
            timeout_seconds=timeout_seconds,
            idempotency_key=idempotency_key,
        )

    @server.tool(annotations=READ_ONLY_TOOL)
    async def resolve_get_render_job_status(
        job_id: str,
        timeout_seconds: float = 30,
    ) -> dict[str, Any]:
        """Return current Resolve status for one render job."""
        return await asyncio.to_thread(
            service.resolve_get_render_job_status,
            job_id,
            timeout_seconds=timeout_seconds,
        )

    @server.tool(annotations=WRITE_TOOL)
    async def resolve_start_render_job(
        job_id: str,
        timeout_seconds: float = 30,
        idempotency_key: str | None = None,
    ) -> dict[str, Any]:
        """Start one agent-prepared render job after a project backup."""
        return await asyncio.to_thread(
            service.resolve_start_render_job,
            job_id,
            timeout_seconds=timeout_seconds,
            idempotency_key=idempotency_key,
        )

    @server.tool(annotations=READ_ONLY_TOOL)
    async def resolve_verify_render_output(
        job_id: str,
        timeout_seconds: float = 30,
    ) -> dict[str, Any]:
        """Verify one completed render as a managed non-empty MP4 file."""
        return await asyncio.to_thread(
            service.resolve_verify_render_output,
            job_id,
            timeout_seconds=timeout_seconds,
        )

    @server.tool(annotations=WRITE_TOOL)
    async def create_rough_cut(
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
        """Create and persist a pending-review plan without changing Resolve."""
        return await asyncio.to_thread(
            service.create_rough_cut,
            screen_file=screen_file,
            webcam_file=webcam_file,
            screen_audio_file=screen_audio_file,
            webcam_audio_file=webcam_audio_file,
            speech_audio_file=speech_audio_file,
            timeline_name=timeline_name,
            max_sync_offset_ms=max_sync_offset_ms,
            pause_threshold_dbfs=pause_threshold_dbfs,
            min_pause_duration_ms=min_pause_duration_ms,
            preserve_context_ms=preserve_context_ms,
        )

    @server.tool(annotations=WRITE_TOOL)
    async def approve_rough_cut(
        plan_id: str,
        confirm_review: bool,
    ) -> dict[str, Any]:
        """Approve one stored draft without applying any Resolve edits."""
        return await asyncio.to_thread(
            service.approve_rough_cut,
            plan_id,
            confirm_review=confirm_review,
        )

    @server.tool(annotations=READ_ONLY_TOOL)
    async def get_rough_cut_plan(plan_id: str) -> dict[str, Any]:
        """Return one stored draft and its matching approval state."""
        return await asyncio.to_thread(
            service.get_rough_cut_plan,
            plan_id,
        )

    @server.tool(annotations=READ_ONLY_TOOL)
    async def list_rough_cut_plans(limit: int = 100) -> dict[str, Any]:
        """List bounded rough-cut summaries without source media paths."""
        return await asyncio.to_thread(
            service.list_rough_cut_plans,
            limit,
        )

    @server.tool(annotations=READ_ONLY_TOOL)
    async def preview_rough_cut_apply(
        plan_id: str,
        source_timeline_id: str,
        target_timeline_name: str,
    ) -> dict[str, Any]:
        """Show M34 operations and capability blocks without changing Resolve."""
        return await asyncio.to_thread(
            service.preview_rough_cut_apply,
            plan_id,
            source_timeline_id,
            target_timeline_name,
        )

    @server.tool(annotations=WRITE_TOOL)
    async def apply_rough_cut(
        plan_id: str,
        source_timeline_id: str,
        target_timeline_name: str,
        confirm_apply: bool = False,
        timeout_seconds: float = 30,
    ) -> dict[str, Any]:
        """Apply an approved plan only when every required API is verified."""
        return await asyncio.to_thread(
            service.apply_rough_cut,
            plan_id,
            source_timeline_id,
            target_timeline_name,
            confirm_apply=confirm_apply,
            timeout_seconds=timeout_seconds,
        )

    @server.tool(annotations=WRITE_TOOL)
    async def sync_screen_and_webcam(
        timeline_name: str,
        screen_asset_id: str,
        webcam_asset_id: str,
        webcam_offset_ms: int,
        confirm_sync: bool,
        timeout_seconds: float = 30,
    ) -> dict[str, Any]:
        """Create a timeline and place synchronized screen V1/A1 + webcam V2."""
        return await asyncio.to_thread(
            service.sync_screen_and_webcam,
            timeline_name=timeline_name,
            screen_asset_id=screen_asset_id,
            webcam_asset_id=webcam_asset_id,
            webcam_offset_ms=webcam_offset_ms,
            confirm_sync=confirm_sync,
            timeout_seconds=timeout_seconds,
        )

    @server.tool(annotations=WRITE_TOOL)
    async def compose_webcam_picture_in_picture(
        synchronized_pair_receipt_id: str,
        size_percent: float = 25.0,
        center_x_percent: float = 82.0,
        center_y_percent: float = 82.0,
        confirm_layout: bool = False,
        timeout_seconds: float = 30,
    ) -> dict[str, Any]:
        """Lay out the synchronized webcam using normalized frame coordinates."""
        return await asyncio.to_thread(
            service.compose_webcam_picture_in_picture,
            synchronized_pair_receipt_id=synchronized_pair_receipt_id,
            size_percent=size_percent,
            center_x_percent=center_x_percent,
            center_y_percent=center_y_percent,
            confirm_layout=confirm_layout,
            timeout_seconds=timeout_seconds,
        )

    @server.tool(annotations=WRITE_TOOL)
    async def link_synchronized_screen_pair(
        synchronized_pair_receipt_id: str,
        confirm_link: bool = False,
        timeout_seconds: float = 30,
    ) -> dict[str, Any]:
        """Link the canonical screen video/audio items from an M38 receipt."""
        return await asyncio.to_thread(
            service.link_synchronized_screen_pair,
            synchronized_pair_receipt_id=synchronized_pair_receipt_id,
            confirm_link=confirm_link,
            timeout_seconds=timeout_seconds,
        )

    @server.tool(annotations=READ_ONLY_TOOL)
    async def preview_synchronized_pause_compaction(
        plan_id: str,
        synchronized_pair_receipt_id: str,
        target_timeline_name: str,
        timeout_seconds: float = 30,
    ) -> dict[str, Any]:
        """Preview a kept-range synchronized rebuild without editing Resolve."""
        return await asyncio.to_thread(
            service.preview_synchronized_pause_compaction,
            plan_id=plan_id,
            synchronized_pair_receipt_id=synchronized_pair_receipt_id,
            target_timeline_name=target_timeline_name,
            timeout_seconds=timeout_seconds,
        )

    @server.tool(annotations=WRITE_TOOL)
    async def apply_synchronized_pause_compaction(
        plan_id: str,
        synchronized_pair_receipt_id: str,
        target_timeline_name: str,
        confirm_apply: bool,
        timeout_seconds: float = 30,
    ) -> dict[str, Any]:
        """Create a new synchronized timeline from approved kept ranges."""
        return await asyncio.to_thread(
            service.apply_synchronized_pause_compaction,
            plan_id=plan_id,
            synchronized_pair_receipt_id=synchronized_pair_receipt_id,
            target_timeline_name=target_timeline_name,
            confirm_apply=confirm_apply,
            timeout_seconds=timeout_seconds,
        )

    @server.tool(annotations=WRITE_TOOL)
    async def finalize_synchronized_pause_compaction(
        pause_compaction_receipt_id: str,
        picture_in_picture_receipt_id: str,
        synchronized_link_receipt_id: str,
        confirm_finalize: bool,
        timeout_seconds: float = 30,
    ) -> dict[str, Any]:
        """Propagate approved screen links and webcam layout to M42 segments."""
        return await asyncio.to_thread(
            service.finalize_synchronized_pause_compaction,
            pause_compaction_receipt_id=pause_compaction_receipt_id,
            picture_in_picture_receipt_id=picture_in_picture_receipt_id,
            synchronized_link_receipt_id=synchronized_link_receipt_id,
            confirm_finalize=confirm_finalize,
            timeout_seconds=timeout_seconds,
        )

    @server.tool(annotations=WRITE_TOOL)
    async def prepare_finalized_timeline_render(
        finalization_receipt_id: str,
        custom_name: str,
        profile: str = DEFAULT_RENDER_PROFILE,
        confirm_prepare: bool = False,
        timeout_seconds: float = 30,
    ) -> dict[str, Any]:
        """Prepare a fixed render job for one applied M43 timeline."""
        return await asyncio.to_thread(
            service.prepare_finalized_timeline_render,
            finalization_receipt_id=finalization_receipt_id,
            custom_name=custom_name,
            profile=profile,
            confirm_prepare=confirm_prepare,
            timeout_seconds=timeout_seconds,
        )

    @server.tool(annotations=WRITE_TOOL)
    async def clean_dialogue_audio(
        source_file: str,
        preset: str = "pcm-dialogue-level-v1",
    ) -> dict[str, Any]:
        """Create a derived PCM WAV and canonical before/after report."""
        return await asyncio.to_thread(
            service.clean_dialogue_audio,
            source_file,
            preset=preset,
        )

    @server.tool(annotations=READ_ONLY_TOOL)
    async def get_audio_report(report_id: str) -> dict[str, Any]:
        """Return one stored and validated audio before/after report."""
        return await asyncio.to_thread(
            service.get_audio_report,
            report_id,
        )

    @server.tool(annotations=READ_ONLY_TOOL)
    async def list_audio_reports(limit: int = 100) -> dict[str, Any]:
        """List bounded audio summaries without local filesystem paths."""
        return await asyncio.to_thread(
            service.list_audio_reports,
            limit,
        )

    return server


def main() -> None:
    """Run the local MCP server over stdio."""
    create_server().run()


if __name__ == "__main__":
    main()
