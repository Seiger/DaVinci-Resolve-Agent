"""Provider-neutral filesystem command client."""

from __future__ import annotations

import json
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Protocol
from uuid import uuid4

from agent.contracts import ContractValidationError, validate_contract
from agent.paths import runtime_directory
from transports.filesystem import (
    FilesystemLayout,
    atomic_write_json,
    read_json_object,
)

PROTOCOL_VERSION = "1.0"


class AgentClientError(RuntimeError):
    """Base class for external command-client failures."""


class CommandTimeoutError(AgentClientError):
    """Raised when no response appears within the requested interval."""

    def __init__(self, command_id: str, timeout_seconds: float) -> None:
        self.command_id = command_id
        self.timeout_seconds = timeout_seconds
        super().__init__(
            f"Command {command_id} timed out after {timeout_seconds:g}s. "
            "Run ResolveBridge inside Resolve and retry."
        )


class BridgeCommandError(AgentClientError):
    """Raised when the bridge returns a structured command error."""

    def __init__(
        self,
        *,
        code: str,
        message: str,
        retryable: bool,
    ) -> None:
        self.code = code
        self.retryable = retryable
        retry_hint = " Retry is allowed." if retryable else ""
        super().__init__(f"{code}: {message}.{retry_hint}")


class BridgeProtocolError(AgentClientError):
    """Raised when a bridge response violates the protocol."""


class CommandClient(Protocol):
    """Provider-neutral interface implemented by command transports."""

    def request(
        self,
        *,
        provider: str,
        action: str,
        arguments: dict[str, Any] | None = None,
        timeout_seconds: float = 30,
        idempotency_key: str | None = None,
        create_backup: bool = False,
        allow_destructive: bool = False,
    ) -> Any:
        """Submit a provider command and return its result."""
        ...


class FilesystemCommandClient:
    """Submit validated commands and await atomic filesystem responses."""

    def __init__(
        self,
        runtime_root: Path | None = None,
        *,
        poll_interval_seconds: float = 0.1,
    ) -> None:
        if poll_interval_seconds <= 0:
            raise ValueError("poll_interval_seconds must be greater than zero.")
        root = runtime_directory() if runtime_root is None else runtime_root
        self._layout = FilesystemLayout(root)
        self._poll_interval_seconds = poll_interval_seconds
        self._layout.ensure_directories()

    def request(
        self,
        *,
        provider: str,
        action: str,
        arguments: dict[str, Any] | None = None,
        timeout_seconds: float = 30,
        idempotency_key: str | None = None,
        create_backup: bool = False,
        allow_destructive: bool = False,
    ) -> Any:
        """Submit one allowlisted command and return its validated result."""
        if timeout_seconds <= 0:
            raise ValueError("timeout_seconds must be greater than zero.")
        if idempotency_key is not None and not idempotency_key:
            raise ValueError("idempotency_key must not be empty.")

        command_id = str(uuid4())
        stable_key = command_id if idempotency_key is None else idempotency_key
        now = datetime.now(timezone.utc)
        command = {
            "protocol_version": PROTOCOL_VERSION,
            "command_id": command_id,
            "idempotency_key": stable_key,
            "created_at": now.isoformat().replace("+00:00", "Z"),
            "expires_at": (now + timedelta(seconds=timeout_seconds + 5))
            .isoformat()
            .replace("+00:00", "Z"),
            "provider": provider,
            "action": action,
            "arguments": {} if arguments is None else arguments,
            "safety": {
                "allow_destructive": allow_destructive,
                "create_backup": create_backup,
            },
        }
        try:
            validate_contract("command", command)
        except ContractValidationError as error:
            raise BridgeProtocolError(str(error)) from error

        command_path = self._layout.commands / f"{command_id}.json"
        response_path = self._layout.responses / f"{command_id}.json"
        atomic_write_json(command_path, command)
        return self._await_response(
            command_id=command_id,
            response_path=response_path,
            timeout_seconds=timeout_seconds,
        )

    def _await_response(
        self,
        *,
        command_id: str,
        response_path: Path,
        timeout_seconds: float,
    ) -> Any:
        deadline = time.monotonic() + timeout_seconds
        last_read_error: OSError | None = None
        while time.monotonic() < deadline:
            if response_path.is_file():
                try:
                    return self._read_response(command_id, response_path)
                except OSError as error:
                    # Windows may briefly deny access while another process
                    # finishes publishing the atomically replaced file.
                    last_read_error = error
            time.sleep(self._poll_interval_seconds)
        if last_read_error is not None:
            raise BridgeProtocolError(
                f"Bridge response {response_path.name} remained unreadable: "
                f"{last_read_error}"
            ) from last_read_error
        raise CommandTimeoutError(command_id, timeout_seconds)

    @staticmethod
    def _read_response(command_id: str, response_path: Path) -> Any:
        try:
            response = read_json_object(response_path)
            validate_contract("response", response)
        except (
            ValueError,
            json.JSONDecodeError,
            ContractValidationError,
        ) as error:
            raise BridgeProtocolError(
                f"Bridge response {response_path.name} is invalid: {error}"
            ) from error

        if response["command_id"] != command_id:
            raise BridgeProtocolError(
                "Bridge response command_id does not match the submitted command."
            )
        if response["status"] == "success":
            return response["result"]

        error_payload = response["error"]
        if not isinstance(error_payload, dict):
            raise BridgeProtocolError("Bridge error response has no error object.")
        raise BridgeCommandError(
            code=str(error_payload["code"]),
            message=str(error_payload["message"]),
            retryable=bool(error_payload["retryable"]),
        )
