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
        "resolve_get_project",
        "resolve_list_timelines",
        "resolve_get_timeline",
        "resolve_import_media",
        "resolve_create_timeline",
        "resolve_append_clip",
        "resolve_add_marker",
        "create_rough_cut",
    }
