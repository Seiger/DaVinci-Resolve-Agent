"""Provider-neutral validation for safe M7 render-job preparation."""

from __future__ import annotations

import re
import unicodedata
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from agent.paths import render_output_directory

DEFAULT_RENDER_PROFILE = "youtube-1080p-h264-v1"
MAX_RENDER_NAME_LENGTH = 128
FORBIDDEN_FILENAME_CHARACTERS = frozenset('<>:"/\\|?*')
RENDER_JOB_ID_PATTERN = re.compile(r"^[A-Za-z0-9._:-]{1,128}$")


@dataclass(frozen=True, slots=True)
class RenderProfile:
    """One fixed, provider-neutral export profile."""

    name: str
    width: int
    height: int


RENDER_PROFILES = {
    "youtube-1080p-h264-v1": RenderProfile(
        name="youtube-1080p-h264-v1",
        width=1920,
        height=1080,
    ),
    "youtube-2160p-h264-v1": RenderProfile(
        name="youtube-2160p-h264-v1",
        width=3840,
        height=2160,
    ),
}


class RenderPreparationError(ValueError):
    """Raised when a render-job request violates the fixed M7 policy."""


class RenderOutputVerificationError(ValueError):
    """Raised when render status cannot identify one safe managed output."""


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


def validate_render_profile(profile: str) -> RenderProfile:
    """Return one allowlisted render profile."""
    try:
        return RENDER_PROFILES[profile]
    except (KeyError, TypeError) as error:
        supported = ", ".join(sorted(RENDER_PROFILES))
        raise RenderPreparationError(
            f"Unsupported render profile. Expected one of: {supported}."
        ) from error


def verify_render_output(
    render_status: Mapping[str, Any],
    *,
    expected_directory: Path | None = None,
) -> dict[str, Any]:
    """Verify one completed render as a non-empty managed MP4 file."""
    job = render_status.get("job")
    status = render_status.get("status")
    if not isinstance(job, Mapping) or not isinstance(status, Mapping):
        raise RenderOutputVerificationError(
            "Render status must contain job and status objects."
        )

    job_id = render_status.get("job_id")
    if not isinstance(job_id, str) or not job_id:
        raise RenderOutputVerificationError(
            "Render status must contain a non-empty job_id."
        )

    target_value = job.get("TargetDir")
    filename_value = job.get("OutputFilename")
    if not isinstance(target_value, str) or not target_value:
        raise RenderOutputVerificationError(
            "Render job does not contain a target directory."
        )
    if (
        not isinstance(filename_value, str)
        or not filename_value
        or Path(filename_value).name != filename_value
        or Path(filename_value).suffix.casefold() != ".mp4"
    ):
        raise RenderOutputVerificationError(
            "Render job output must be one safe MP4 filename."
        )

    managed_directory = (
        render_output_directory()
        if expected_directory is None
        else expected_directory
    ).resolve()
    target_directory = Path(target_value).resolve()
    if target_directory != managed_directory:
        raise RenderOutputVerificationError(
            "Render job target is outside the managed output directory."
        )

    output_path = (target_directory / filename_value).resolve()
    if output_path.parent != managed_directory:
        raise RenderOutputVerificationError(
            "Render output path escapes the managed output directory."
        )

    exists = output_path.is_file()
    size_bytes = output_path.stat().st_size if exists else 0
    completion = status.get("CompletionPercentage")
    completed = (
        not isinstance(completion, bool)
        and isinstance(completion, (int, float))
        and completion == 100
    )
    non_empty = size_bytes > 0
    return {
        "job_id": job_id,
        "rendering_in_progress": bool(
            render_status.get("rendering_in_progress")
        ),
        "status": dict(status),
        "output": {
            "path": str(output_path),
            "exists": exists,
            "size_bytes": size_bytes,
        },
        "validation": {
            "completed": completed,
            "managed_path": True,
            "non_empty": non_empty,
            "passed": completed and exists and non_empty,
        },
    }
