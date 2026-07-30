"""Provider-neutral validation for safe M7 render-job preparation."""

from __future__ import annotations

import re
import unicodedata

RENDER_PRESET_NAME = "youtube-1080p-h264-v1"
MAX_RENDER_NAME_LENGTH = 128
FORBIDDEN_FILENAME_CHARACTERS = frozenset('<>:"/\\|?*')
RENDER_JOB_ID_PATTERN = re.compile(r"^[A-Za-z0-9._:-]{1,128}$")


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


def validate_render_job_id(job_id: str) -> str:
    """Return a validated opaque Resolve render-job identifier."""
    if not isinstance(job_id, str) or not RENDER_JOB_ID_PATTERN.fullmatch(job_id):
        raise RenderPreparationError(
            "job_id must contain 1 to 128 safe identifier characters."
        )
    return job_id
