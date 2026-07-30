"""Provider-neutral interface shared by future editor integrations."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Protocol


class VideoEditorProvider(Protocol):
    """Minimum discovery contract for future video editor providers."""

    @property
    def provider_id(self) -> str:
        """Return a stable provider identifier."""
        ...

    def capabilities(self) -> Mapping[str, object]:
        """Report verified provider capabilities without assuming support."""
        ...

