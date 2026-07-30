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

    def import_media(
        self,
        paths: list[str],
        *,
        timeout_seconds: float = 30,
        idempotency_key: str | None = None,
    ) -> dict[str, Any]:
        return {"items": [{"asset_id": "asset-1", "name": paths[0]}]}

    def create_timeline(
        self,
        name: str,
        *,
        timeout_seconds: float = 30,
        idempotency_key: str | None = None,
    ) -> dict[str, Any]:
        return {"timeline": {"timeline_id": "timeline-1", "name": name}}

    def append_clip(
        self,
        timeline_id: str,
        asset_id: str,
        *,
        timeout_seconds: float = 30,
        idempotency_key: str | None = None,
    ) -> dict[str, Any]:
        return {"timeline_id": timeline_id, "asset_id": asset_id}

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
        return {"timeline_id": timeline_id, "frame": frame, "color": color}


class StubMediaPolicy:
    def prepare_import(self, paths: list[str]) -> list[str]:
        return paths


def _fresh_state() -> dict[str, Any]:
    return {
        "bridge_version": "0.1.0",
        "protocol_version": "1.0",
        "status": "ready",
        "last_heartbeat": datetime.now(timezone.utc).isoformat(),
        "capabilities": {"bridge.ping": True},
    }


def test_mcp_exposes_fixed_m4_tool_surface() -> None:
    application = AgentApplication(
        resolve=StubResolveReader(),
        state_loader=_fresh_state,
        media_policy=StubMediaPolicy(),
    )
    server = create_server(application)

    async def exercise_server() -> tuple[dict[str, Any], set[str]]:
        async with Client(server) as client:
            tools = await client.list_tools()
            names = {tool.name for tool in tools.tools}
            annotations = {
                tool.name: tool.annotations for tool in tools.tools
            }
            assert all(
                annotation is not None
                and annotation.destructive_hint is False
                for annotation in annotations.values()
            )
            status_annotations = annotations["video_agent_status"]
            import_annotations = annotations["resolve_import_media"]
            assert status_annotations is not None
            assert import_annotations is not None
            assert status_annotations.read_only_hint is True
            assert import_annotations.read_only_hint is False

            results = {
                "project": await client.call_tool("resolve_get_project", {}),
                "timelines": await client.call_tool(
                    "resolve_list_timelines",
                    {},
                ),
                "timeline": await client.call_tool(
                    "resolve_get_timeline",
                    {},
                ),
                "status": await client.call_tool("video_agent_status", {}),
                "imported": await client.call_tool(
                    "resolve_import_media",
                    {"paths": ["sample.wav"]},
                ),
                "created": await client.call_tool(
                    "resolve_create_timeline",
                    {"name": "M4 Timeline"},
                ),
                "appended": await client.call_tool(
                    "resolve_append_clip",
                    {"timeline_id": "timeline-1", "asset_id": "asset-1"},
                ),
                "marker": await client.call_tool(
                    "resolve_add_marker",
                    {
                        "timeline_id": "timeline-1",
                        "frame": 0,
                        "color": "Green",
                    },
                ),
            }
        return results, names

    results, names = asyncio.run(exercise_server())

    assert names == {
        "video_agent_status",
        "resolve_get_project",
        "resolve_list_timelines",
        "resolve_get_timeline",
        "resolve_import_media",
        "resolve_create_timeline",
        "resolve_append_clip",
        "resolve_add_marker",
    }
    assert results["project"].structured_content == {
        "project": {"name": "Test Project"}
    }
    assert results["timelines"].structured_content == {
        "timelines": [{"index": 1, "name": "Main"}]
    }
    assert results["timeline"].structured_content == {
        "timeline": {"name": "Main"}
    }
    assert results["status"].structured_content["healthy"] is True
    assert results["imported"].structured_content["items"][0]["asset_id"] == (
        "asset-1"
    )
    assert results["created"].structured_content["timeline"]["timeline_id"] == (
        "timeline-1"
    )
    assert results["appended"].structured_content["asset_id"] == "asset-1"
    assert results["marker"].structured_content["color"] == "Green"
