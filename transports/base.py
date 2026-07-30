"""Transport-neutral marker interface."""

from __future__ import annotations

from typing import Protocol


class Transport(Protocol):
    """Minimum identity contract for future local transports."""

    @property
    def transport_id(self) -> str:
        """Return a stable transport identifier."""
        ...

