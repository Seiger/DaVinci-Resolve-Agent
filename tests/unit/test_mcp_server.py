"""MCP tool-surface tests using the official in-memory client."""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from typing import Any

from mcp import Client

from agent.application import AgentApplication
from mcp_server.server import create_server


class StubResolveReader:
    def current_project(self, timeout_seconds: float = 30) -> dict[str, Any]:
        return {"name": "Test Project"}

    def timelines(self, timeout_seconds: float = 30) -> list[dict[str, Any]]:
        return [{"index": 1, "name": "Main"}]

    def current_timeline(self, timeout_seconds: float = 30) -> dict[str, Any]:
        return {"name": "Main"}


def _fresh_state() -> dict[str, Any]:
    return {
        "bridge_version": "0.1.0",
        "protocol_version": "1.0",
        "status": "ready",
        "last_heartbeat": datetime.now(timezone.utc).isoformat(),
        "capabilities": {"bridge.ping": True},
    }


def test_mcp_exposes_only_m3_read_only_tools() -> None:
    application = AgentApplication(
        resolve=StubResolveReader(),
        state_loader=_fresh_state,
    )
    server = create_server(application)

    async def exercise_server() -> tuple[Any, Any, Any, Any, set[str]]:
        async with Client(server) as client:
            tools = await client.list_tools()
            names = {tool.name for tool in tools.tools}
            assert all(
                tool.annotations is not None
                and tool.annotations.read_only_hint is True
                and tool.annotations.destructive_hint is False
                for tool in tools.tools
            )

            project = await client.call_tool("resolve_get_project", {})
            timelines = await client.call_tool("resolve_list_timelines", {})
            timeline = await client.call_tool("resolve_get_timeline", {})
            status = await client.call_tool("video_agent_status", {})
        return project, timelines, timeline, status, names

    project, timelines, timeline, status, names = asyncio.run(exercise_server())

    assert names == {
        "video_agent_status",
        "resolve_get_project",
        "resolve_list_timelines",
        "resolve_get_timeline",
    }
    assert project.structured_content == {"project": {"name": "Test Project"}}
    assert timelines.structured_content == {
        "timelines": [{"index": 1, "name": "Main"}]
    }
    assert timeline.structured_content == {"timeline": {"name": "Main"}}
    assert status.structured_content["healthy"] is True
