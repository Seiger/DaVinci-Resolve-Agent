"""Provider-neutral application services exposed to user-facing adapters."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any, Protocol

from agent.bridge_state import (
    DEFAULT_HEARTBEAT_MAX_AGE_SECONDS,
    bridge_is_healthy,
    heartbeat_age_seconds,
    load_bridge_state,
)
from providers.resolve import ResolveProviderClient

MAX_COMMAND_TIMEOUT_SECONDS = 300.0


class ResolveReader(Protocol):
    """Read-only Resolve operations required by the application layer."""

    def current_project(self, timeout_seconds: float = 30) -> dict[str, Any] | None:
        """Return the current project."""

    def timelines(self, timeout_seconds: float = 30) -> list[dict[str, Any]]:
        """Return timelines in the current project."""

    def current_timeline(
        self,
        timeout_seconds: float = 30,
    ) -> dict[str, Any] | None:
        """Return the current timeline."""


class AgentApplication:
    """Coordinate core status and provider operations for external adapters."""

    def __init__(
        self,
        resolve: ResolveReader | None = None,
        state_loader: Callable[[], dict[str, Any]] = load_bridge_state,
    ) -> None:
        self._resolve = ResolveProviderClient() if resolve is None else resolve
        self._state_loader = state_loader

    def status(
        self,
        max_age_seconds: int = DEFAULT_HEARTBEAT_MAX_AGE_SECONDS,
    ) -> dict[str, Any]:
        """Return cached bridge state with computed health information."""
        if max_age_seconds < 1:
            raise ValueError("max_age_seconds must be greater than zero.")

        state = self._state_loader()
        return {
            "healthy": bridge_is_healthy(
                state,
                max_age_seconds=max_age_seconds,
            ),
            "heartbeat_age_seconds": heartbeat_age_seconds(state),
            "bridge": state,
        }

    def resolve_get_project(
        self,
        timeout_seconds: float = 30,
    ) -> dict[str, Any] | None:
        """Return the current Resolve project through the provider."""
        return self._resolve.current_project(
            self._validated_timeout(timeout_seconds)
        )

    def resolve_list_timelines(
        self,
        timeout_seconds: float = 30,
    ) -> list[dict[str, Any]]:
        """Return Resolve timelines through the provider."""
        return self._resolve.timelines(self._validated_timeout(timeout_seconds))

    def resolve_get_timeline(
        self,
        timeout_seconds: float = 30,
    ) -> dict[str, Any] | None:
        """Return the current Resolve timeline through the provider."""
        return self._resolve.current_timeline(
            self._validated_timeout(timeout_seconds)
        )

    @staticmethod
    def _validated_timeout(timeout_seconds: float) -> float:
        if not 0 < timeout_seconds <= MAX_COMMAND_TIMEOUT_SECONDS:
            raise ValueError(
                "timeout_seconds must be greater than zero and no more than 300."
            )
        return timeout_seconds
