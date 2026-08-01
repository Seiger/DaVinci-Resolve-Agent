"""End-to-end MCP stdio handshake through the installed console script."""

from __future__ import annotations

import asyncio
import os
import sys
from pathlib import Path

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client


def test_installed_mcp_server_supports_stdio_handshake() -> None:
    executable_name = (
        "davinci-agent-mcp.exe" if os.name == "nt" else "davinci-agent-mcp"
    )
    executable = Path(sys.executable).parent / executable_name
    assert executable.is_file()

    async def list_tool_names() -> set[str]:
        parameters = StdioServerParameters(command=str(executable), args=[])
        async with (
            stdio_client(parameters) as (read_stream, write_stream),
            ClientSession(read_stream, write_stream) as session,
        ):
            await session.initialize()
            result = await session.list_tools()
            return {tool.name for tool in result.tools}

    assert asyncio.run(list_tool_names()) == {
        "video_agent_status",
        "resolve_stop_bridge",
        "resolve_get_project",
        "resolve_list_timelines",
        "resolve_get_timeline",
        "resolve_list_timeline_items",
        "resolve_list_media_pool_items",
        "resolve_get_editing_metadata",
        "resolve_get_workspace_snapshot",
        "resolve_get_render_options",
        "resolve_import_media",
        "resolve_create_timeline",
        "resolve_ensure_timeline_tracks",
        "resolve_duplicate_timeline",
        "resolve_set_current_timeline",
        "resolve_append_clip",
        "resolve_insert_clip",
        "resolve_set_clip_enabled",
        "resolve_set_clips_linked",
        "resolve_set_clip_transform",
        "resolve_delete_clip",
        "resolve_add_marker",
        "resolve_prepare_render_job",
        "resolve_get_render_job_status",
        "resolve_start_render_job",
        "resolve_verify_render_output",
        "create_rough_cut",
        "approve_rough_cut",
        "get_rough_cut_plan",
        "list_rough_cut_plans",
        "preview_rough_cut_apply",
        "apply_rough_cut",
        "sync_screen_and_webcam",
        "compose_webcam_picture_in_picture",
        "link_synchronized_screen_pair",
        "preview_synchronized_pause_compaction",
        "apply_synchronized_pause_compaction",
        "finalize_synchronized_pause_compaction",
        "prepare_finalized_timeline_render",
        "clean_dialogue_audio",
        "get_audio_report",
        "list_audio_reports",
    }
