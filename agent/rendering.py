"""Provider-neutral validation for safe M7 render-job preparation."""

from __future__ import annotations

import unicodedata

RENDER_PRESET_NAME = "youtube-1080p-h264-v1"
MAX_RENDER_NAME_LENGTH = 128
FORBIDDEN_FILENAME_CHARACTERS = frozenset('<>:"/\\|?*')


class RenderPreparationError(ValueError):
    """Raised when a render-job request violates the fixed M7 policy."""


def validate_render_name(custom_name: str) -> str:
    """Return a normalized safe filename stem without accepting a path."""
    normalized = unicodedata.normalize("NFC", custom_name).strip()
    if not normalized or len(normalized) > MAX_RENDER_NAME_LENGTH:
        raise RenderPreparationError(
            "custom_name must contain 1 to 128 characters."
        )
    if normalized in {".", ".."}:
        raise RenderPreparationError("custom_name must be a filename stem.")
    if any(
        character in FORBIDDEN_FILENAME_CHARACTERS
        or ord(character) < 32
        for character in normalized
    ):
        raise RenderPreparationError(
            "custom_name contains a path separator or invalid filename character."
        )
    if normalized.endswith((".", " ")):
        raise RenderPreparationError(
            "custom_name must not end with a dot or space."
        )
    return normalized
