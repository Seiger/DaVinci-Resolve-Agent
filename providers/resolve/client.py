"""Typed Resolve adapter over the provider-neutral command client."""

from __future__ import annotations

from typing import Any, cast

from agent.client import BridgeProtocolError, CommandClient, FilesystemCommandClient
from agent.contracts import ContractValidationError, validate_contract
from agent.rendering import DEFAULT_RENDER_PROFILE


class ResolveProviderClient:
    """Expose the explicitly allowlisted Resolve command surface."""

    def __init__(
        self,
        command_client: CommandClient | None = None,
    ) -> None:
        self._client = (
            FilesystemCommandClient() if command_client is None else command_client
        )

    def _request(self, action: str, timeout_seconds: float) -> Any:
        return self._client.request(
            provider="resolve",
            action=action,
            timeout_seconds=timeout_seconds,
        )

    def ping(self, timeout_seconds: float = 30) -> str:
        result = self._request("ping", timeout_seconds)
        if not isinstance(result, dict) or result.get("message") != "pong":
            raise BridgeProtocolError("Resolve ping response is invalid.")
        return "pong"

    def bridge_info(self, timeout_seconds: float = 30) -> dict[str, Any]:
        return self._object_result("get_bridge_info", timeout_seconds)

    def capabilities(self, timeout_seconds: float = 30) -> dict[str, bool | str]:
        result = self._object_result("get_capabilities", timeout_seconds)
        try:
            validate_contract("capability", result)
        except ContractValidationError as error:
            raise BridgeProtocolError(str(error)) from error
        return cast(dict[str, bool | str], result)

    def current_project(self, timeout_seconds: float = 30) -> dict[str, Any] | None:
        return self._optional_object_result("get_current_project", timeout_seconds)

    def timelines(self, timeout_seconds: float = 30) -> list[dict[str, Any]]:
        result = self._request("list_timelines", timeout_seconds)
        if not isinstance(result, list) or not all(
            isinstance(item, dict) for item in result
        ):
            raise BridgeProtocolError("Resolve timelines response is invalid.")
        return cast(list[dict[str, Any]], result)

    def current_timeline(
        self,
        timeout_seconds: float = 30,
    ) -> dict[str, Any] | None:
        return self._optional_object_result("get_current_timeline", timeout_seconds)

    def render_environment(
        self,
        timeout_seconds: float = 30,
    ) -> dict[str, Any]:
        """Return documented render formats, presets, current values, and jobs."""
        result = self._object_result("get_render_environment", timeout_seconds)
        if (
            not isinstance(result.get("formats"), list)
            or not isinstance(result.get("current"), dict)
            or not isinstance(result.get("presets"), list)
            or not isinstance(result.get("jobs"), list)
            or not isinstance(result.get("mp4_h264_resolutions"), list)
        ):
            raise BridgeProtocolError(
                "Resolve get_render_environment response is invalid."
            )
        return result

    def import_media(
        self,
        paths: list[str],
        *,
        timeout_seconds: float = 30,
        idempotency_key: str | None = None,
    ) -> dict[str, Any]:
        """Import validated media paths with a mandatory project backup."""
        result = self._client.request(
            provider="resolve",
            action="import_media",
            arguments={"paths": paths},
            timeout_seconds=timeout_seconds,
            idempotency_key=idempotency_key,
            create_backup=True,
        )
        return self._object_value("import_media", result)

    def create_timeline(
        self,
        name: str,
        *,
        timeout_seconds: float = 30,
        idempotency_key: str | None = None,
    ) -> dict[str, Any]:
        """Create an empty timeline with a mandatory project backup."""
        result = self._client.request(
            provider="resolve",
            action="create_timeline",
            arguments={"name": name},
            timeout_seconds=timeout_seconds,
            idempotency_key=idempotency_key,
            create_backup=True,
        )
        return self._object_value("create_timeline", result)

    def append_clip(
        self,
        timeline_id: str,
        asset_id: str,
        *,
        timeout_seconds: float = 30,
        idempotency_key: str | None = None,
    ) -> dict[str, Any]:
        """Append a media-pool asset with a mandatory project backup."""
        result = self._client.request(
            provider="resolve",
            action="append_clip",
            arguments={
                "timeline_id": timeline_id,
                "asset_id": asset_id,
            },
            timeout_seconds=timeout_seconds,
            idempotency_key=idempotency_key,
            create_backup=True,
        )
        return self._object_value("append_clip", result)

    def insert_clip(
        self,
        timeline_id: str,
        asset_id: str,
        source_start_frame: int,
        source_end_frame: int,
        position_frames: int,
        track_type: str,
        track_index: int,
        *,
        timeout_seconds: float = 30,
        idempotency_key: str | None = None,
    ) -> dict[str, Any]:
        """Insert one bounded source range with a mandatory project backup."""
        result = self._client.request(
            provider="resolve",
            action="insert_clip",
            arguments={
                "timeline_id": timeline_id,
                "asset_id": asset_id,
                "source_start_frame": source_start_frame,
                "source_end_frame": source_end_frame,
                "position_frames": position_frames,
                "track_type": track_type,
                "track_index": track_index,
            },
            timeout_seconds=timeout_seconds,
            idempotency_key=idempotency_key,
            create_backup=True,
        )
        return self._object_value("insert_clip", result)

    def set_clip_enabled(
        self,
        timeline_id: str,
        timeline_item_id: str,
        enabled: bool,
        *,
        timeout_seconds: float = 30,
        idempotency_key: str | None = None,
    ) -> dict[str, Any]:
        """Set one timeline item enabled state after a project backup."""
        result = self._client.request(
            provider="resolve",
            action="set_clip_enabled",
            arguments={
                "timeline_id": timeline_id,
                "timeline_item_id": timeline_item_id,
                "enabled": enabled,
            },
            timeout_seconds=timeout_seconds,
            idempotency_key=idempotency_key,
            create_backup=True,
        )
        return self._object_value("set_clip_enabled", result)

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
        """Add a timeline marker with a mandatory project backup."""
        result = self._client.request(
            provider="resolve",
            action="add_marker",
            arguments={
                "timeline_id": timeline_id,
                "frame": frame,
                "color": color,
                "name": name,
                "note": note,
                "duration": duration,
            },
            timeout_seconds=timeout_seconds,
            idempotency_key=idempotency_key,
            create_backup=True,
        )
        return self._object_value("add_marker", result)

    def prepare_render_job(
        self,
        custom_name: str,
        *,
        profile: str = DEFAULT_RENDER_PROFILE,
        timeout_seconds: float = 30,
        idempotency_key: str | None = None,
    ) -> dict[str, Any]:
        """Add one fixed safe render job with a mandatory project backup."""
        result = self._client.request(
            provider="resolve",
            action="prepare_render_job",
            arguments={"custom_name": custom_name, "profile": profile},
            timeout_seconds=timeout_seconds,
            idempotency_key=idempotency_key,
            create_backup=True,
        )
        return self._object_value("prepare_render_job", result)

    def render_job_status(
        self,
        job_id: str,
        *,
        timeout_seconds: float = 30,
    ) -> dict[str, Any]:
        """Return documented status for one queued render job."""
        result = self._client.request(
            provider="resolve",
            action="get_render_job_status",
            arguments={"job_id": job_id},
            timeout_seconds=timeout_seconds,
        )
        return self._object_value("get_render_job_status", result)

    def start_render_job(
        self,
        job_id: str,
        *,
        timeout_seconds: float = 30,
        idempotency_key: str | None = None,
    ) -> dict[str, Any]:
        """Start one agent-prepared render job after a project backup."""
        result = self._client.request(
            provider="resolve",
            action="start_render_job",
            arguments={"job_id": job_id},
            timeout_seconds=timeout_seconds,
            idempotency_key=idempotency_key,
            create_backup=True,
        )
        return self._object_value("start_render_job", result)

    def _object_result(
        self,
        action: str,
        timeout_seconds: float,
    ) -> dict[str, Any]:
        result = self._request(action, timeout_seconds)
        if not isinstance(result, dict):
            raise BridgeProtocolError(f"Resolve {action} response is invalid.")
        return result

    def _optional_object_result(
        self,
        action: str,
        timeout_seconds: float,
    ) -> dict[str, Any] | None:
        result = self._request(action, timeout_seconds)
        if result is None:
            return None
        if not isinstance(result, dict):
            raise BridgeProtocolError(f"Resolve {action} response is invalid.")
        return result

    @staticmethod
    def _object_value(action: str, result: Any) -> dict[str, Any]:
        if not isinstance(result, dict):
            raise BridgeProtocolError(f"Resolve {action} response is invalid.")
        return result
