"""Typed read-only adapter over the provider-neutral command client."""

from __future__ import annotations

from typing import Any, cast

from agent.client import BridgeProtocolError, CommandClient, FilesystemCommandClient
from agent.contracts import ContractValidationError, validate_contract


class ResolveProviderClient:
    """Expose only the read-only M1 Resolve command allowlist."""

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
