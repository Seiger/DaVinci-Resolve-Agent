"""Opt-in MCP prototype with a bounded, guarded Lua editing surface."""

from __future__ import annotations

import argparse
import asyncio
from pathlib import Path
from typing import Any

from mcp.server import MCPServer
from mcp.types import ToolAnnotations

from providers.resolve.lua_cleanup import cleanup_responses
from providers.resolve.lua_transport import LuaSnapshotClient, prepare


def create_server(root: Path) -> MCPServer:
    client = LuaSnapshotClient(root)
    server = MCPServer(
        name="davinci-resolve-lua-experimental",
        instructions=(
            "Experimental Lua snapshot bridge. Requires a saved open "
            "project and a manually bootstrapped bridge (two-hour lifetime). "
            "Requests run without mouse or keyboard input. Each request exports "
            "the project locally; not suitable for large projects. Writes require "
            "expected project ID, confirmation, and a stable idempotency key. "
            "After a timeout never retry with a new key: the edit may have happened."
        ),
    )
    read = ToolAnnotations(
        read_only_hint=True,
        destructive_hint=False,
        idempotent_hint=True,
        open_world_hint=False,
    )

    @server.tool(annotations=read)
    async def resolve_lua_ping(timeout_seconds: float = 30) -> dict[str, Any]:
        """Verify a fresh background round-trip; requires an open project."""
        return await asyncio.to_thread(client.request, "ping", timeout_seconds)

    @server.tool(annotations=read)
    async def resolve_lua_get_project(timeout_seconds: float = 30) -> dict[str, Any]:
        """Read project identity from a fresh export; no project edits or save."""
        return await asyncio.to_thread(
            client.request, "get_current_project", timeout_seconds
        )

    @server.tool(
        annotations=ToolAnnotations(
            read_only_hint=False, destructive_hint=False, open_world_hint=False
        )
    )
    async def resolve_lua_stop(timeout_seconds: float = 30) -> dict[str, Any]:
        """Stop the Lua loop after a final export acknowledges the request."""
        return await asyncio.to_thread(client.request, "stop", timeout_seconds)

    write = ToolAnnotations(
        read_only_hint=False,
        destructive_hint=False,
        idempotent_hint=True,
        open_world_hint=False,
    )

    @server.tool(annotations=write)
    async def resolve_lua_import_media(
        paths: list[str],
        expected_project_id: str,
        idempotency_key: str,
        confirm: bool = False,
        timeout_seconds: float = 60,
    ) -> dict[str, Any]:
        """Import 1–20 files from session media roots; reject already imported paths.

        Saves and exports a backup before import, then verifies file paths and
        saves. No files are copied, deleted or changed. Reuse the same key on retry.
        """
        return await asyncio.to_thread(
            client.request,
            "import_media",
            timeout_seconds,
            arguments={"paths": paths},
            expected_project_id=expected_project_id,
            confirm=confirm,
            idempotency_key=idempotency_key,
        )

    @server.tool(annotations=write)
    async def resolve_lua_create_timeline(
        name: str,
        expected_project_id: str,
        idempotency_key: str,
        confirm: bool = False,
        timeout_seconds: float = 60,
    ) -> dict[str, Any]:
        """Create an empty named timeline after backup; reject existing exact names.

        Uses the project's current timeline defaults, verifies creation, and saves.
        """
        return await asyncio.to_thread(
            client.request,
            "create_timeline",
            timeout_seconds,
            arguments={"name": name},
            expected_project_id=expected_project_id,
            confirm=confirm,
            idempotency_key=idempotency_key,
        )

    @server.tool(annotations=write)
    async def resolve_lua_append_clip(
        timeline_name: str,
        media_path: str,
        expected_project_id: str,
        idempotency_key: str,
        start_frame: int | None = None,
        end_frame: int | None = None,
        confirm: bool = False,
        timeout_seconds: float = 60,
    ) -> dict[str, Any]:
        """Append imported media to one uniquely named timeline after backup.

        Optional zero-based source start/end frames are both inclusive. Omit both
        for the whole clip. No insert/overwrite/delete. Verifies new item IDs and
        source identity, then saves. Reuse the same key to avoid duplicate clips.
        """
        return await asyncio.to_thread(
            client.request,
            "append_clip",
            timeout_seconds,
            arguments={
                "timeline_name": timeline_name,
                "media_path": media_path,
                "start_frame": start_frame,
                "end_frame": end_frame,
            },
            expected_project_id=expected_project_id,
            confirm=confirm,
            idempotency_key=idempotency_key,
        )

    @server.tool(annotations=write)
    async def resolve_lua_set_clip_properties(
        timeline_name: str,
        track_type: str,
        track_index: int,
        item_index: int,
        expected_media_path: str,
        properties: dict[str, float],
        expected_project_id: str,
        idempotency_key: str,
        confirm: bool = False,
        timeout_seconds: float = 60,
    ) -> dict[str, Any]:
        """Set and verify clip gain or framing after backup.

        Track and item indices are one-based; source path must match. Audio allows
        AudioVolume (-60..12 dB). Video allows ZoomX/Y (.1..4), Pan/Tilt and Opacity.
        """
        return await asyncio.to_thread(
            client.request,
            "set_clip_properties",
            timeout_seconds,
            arguments={
                "timeline_name": timeline_name,
                "track_type": track_type,
                "track_index": track_index,
                "item_index": item_index,
                "expected_media_path": expected_media_path,
                "properties": properties,
            },
            expected_project_id=expected_project_id,
            idempotency_key=idempotency_key,
            confirm=confirm,
        )

    @server.tool(annotations=write)
    async def resolve_lua_add_subtitles(
        timeline_name: str,
        subtitle_path: str,
        expected_project_id: str,
        idempotency_key: str,
        confirm: bool = False,
        timeout_seconds: float = 60,
    ) -> dict[str, Any]:
        """Import bounded UTF-8 SRT captions into a timeline without existing subtitles.

        Backs up first, verifies cue count and first/last timing. SRT must be in
        session media roots. Render burns captions into the picture.
        """
        return await asyncio.to_thread(
            client.request,
            "add_subtitles",
            timeout_seconds,
            arguments={"timeline_name": timeline_name, "subtitle_path": subtitle_path},
            expected_project_id=expected_project_id,
            idempotency_key=idempotency_key,
            confirm=confirm,
        )

    @server.tool(annotations=write)
    async def resolve_lua_prepare_render(
        timeline_name: str,
        expected_project_id: str,
        idempotency_key: str,
        confirm: bool = False,
        timeout_seconds: float = 60,
    ) -> dict[str, Any]:
        """Queue a backed-up 1080p H.264 MP4 with audio and burnt captions.

        Uses installed YouTube - 1080p preset. Output is a new managed session
        directory; no existing video is overwritten. Returns owned render job ID.
        """
        return await asyncio.to_thread(
            client.request,
            "prepare_render",
            timeout_seconds,
            arguments={"timeline_name": timeline_name},
            expected_project_id=expected_project_id,
            idempotency_key=idempotency_key,
            confirm=confirm,
        )

    @server.tool(annotations=write)
    async def resolve_lua_start_render(
        job_id: str,
        expected_project_id: str,
        idempotency_key: str,
        confirm: bool = False,
        timeout_seconds: float = 60,
    ) -> dict[str, Any]:
        """Start only a job prepared by this running bridge; never blindly resubmit.

        Returns when started, not when the file is ready. Poll render status.
        """
        return await asyncio.to_thread(
            client.request,
            "start_render",
            timeout_seconds,
            arguments={"job_id": job_id},
            expected_project_id=expected_project_id,
            idempotency_key=idempotency_key,
            confirm=confirm,
        )

    @server.tool(annotations=read)
    async def resolve_lua_get_render_status(
        job_id: str,
        expected_project_id: str,
        timeout_seconds: float = 30,
    ) -> dict[str, Any]:
        """Read owned job status and verify completed video output."""
        return await asyncio.to_thread(
            client.request,
            "get_render_status",
            timeout_seconds,
            arguments={"job_id": job_id},
            expected_project_id=expected_project_id,
        )

    @server.tool(
        annotations=ToolAnnotations(
            read_only_hint=False,
            destructive_hint=True,
            idempotent_hint=True,
            open_world_hint=False,
        )
    )
    async def resolve_lua_cleanup_responses(confirm: bool = False) -> dict[str, Any]:
        """Preview or delete response snapshots after an acknowledged session stop.

        Keeps every backup, render, receipt and script. Refuses uncertain writes.
        Defaults to preview; confirm=True deletes only the eligible response files.
        """
        return await asyncio.to_thread(cleanup_responses, root, confirm=confirm)

    return server


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--runtime", type=Path, required=True)
    parser.add_argument("--prepare", action="store_true")
    parser.add_argument("--media-root", type=Path, action="append", default=[])
    args = parser.parse_args()
    if args.prepare:
        print(prepare(args.runtime, args.media_root))
    else:
        create_server(args.runtime).run()


if __name__ == "__main__":
    main()
