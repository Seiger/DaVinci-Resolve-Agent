"""Local stdio MCP server exposing the fixed application API."""

from __future__ import annotations

import asyncio
from typing import Any

from mcp.server import MCPServer
from mcp.types import ToolAnnotations

from agent import __version__
from agent.application import AgentApplication

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
