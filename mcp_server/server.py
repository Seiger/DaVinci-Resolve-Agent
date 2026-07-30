"""Local stdio MCP server exposing the read-only application API."""

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


def create_server(application: AgentApplication | None = None) -> MCPServer:
    """Create an MCP server bound to an application service."""
    service = AgentApplication() if application is None else application
    server = MCPServer(
        name="davinci-resolve-agent",
        version=__version__,
        instructions=(
            "Local read-only access to DaVinci Resolve Agent. "
            "The Resolve tools require the one-shot ResolveBridge script to be "
            "launched inside DaVinci Resolve while the request is waiting."
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

    return server


def main() -> None:
    """Run the local MCP server over stdio."""
    create_server().run()


if __name__ == "__main__":
    main()
