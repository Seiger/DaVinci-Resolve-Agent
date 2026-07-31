"""Local stdio MCP server exposing the fixed application API."""

from __future__ import annotations

import asyncio
from typing import Any

from mcp.server import MCPServer
from mcp.types import ToolAnnotations

from agent import __version__
from agent.application import AgentApplication
from agent.rendering import DEFAULT_RENDER_PROFILE

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
    service = AgentApplication() if application is None else application
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
        profile: str = DEFAULT_RENDER_PROFILE,
        timeout_seconds: float = 30,
        idempotency_key: str | None = None,
    ) -> dict[str, Any]:
        """Add a fixed MP4/H264 job after backup without starting render."""
        return await asyncio.to_thread(
            service.resolve_prepare_render_job,
            custom_name,
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

    return server


def main() -> None:
    """Run the local MCP server over stdio."""
    create_server().run()


if __name__ == "__main__":
    main()
