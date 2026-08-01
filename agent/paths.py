"""Platform path resolution without machine-specific absolute paths."""

from __future__ import annotations

import os
from collections.abc import Mapping
from pathlib import Path

APPLICATION_DIRECTORY_NAME = "DaVinciResolveAgent"


class PathConfigurationError(ValueError):
    """Raised when a required platform directory is unavailable."""


def _environment_value(name: str, environment: Mapping[str, str] | None) -> str:
    source = os.environ if environment is None else environment
    value = source.get(name)
    if not value:
        raise PathConfigurationError(
            f"Required Windows environment variable {name} is not set."
        )
    return value


def config_directory(environment: Mapping[str, str] | None = None) -> Path:
    """Return the per-user application configuration directory."""
    return (
        Path(_environment_value("APPDATA", environment))
        / APPLICATION_DIRECTORY_NAME
    )


def config_file(environment: Mapping[str, str] | None = None) -> Path:
    """Return the per-user application configuration file."""
    return config_directory(environment) / "config.toml"


def runtime_directory(environment: Mapping[str, str] | None = None) -> Path:
    """Return the per-user local runtime directory."""
    return (
        Path(_environment_value("LOCALAPPDATA", environment))
        / APPLICATION_DIRECTORY_NAME
        / "runtime"
    )


def logs_directory(environment: Mapping[str, str] | None = None) -> Path:
    """Return the per-user runtime logs directory."""
    return runtime_directory(environment) / "logs"


def plans_directory(environment: Mapping[str, str] | None = None) -> Path:
    """Return the per-user review-only rough-cut plans directory."""
    return runtime_directory(environment) / "plans"


def rough_cut_apply_directory(
    environment: Mapping[str, str] | None = None,
) -> Path:
    """Return durable receipts for bounded rough-cut apply attempts."""
    return runtime_directory(environment) / "rough-cut-applies"


def synchronized_pairs_directory(
    environment: Mapping[str, str] | None = None,
) -> Path:
    """Return durable progress receipts for synchronized pair assembly."""
    return runtime_directory(environment) / "synchronized-pairs"


def picture_in_picture_directory(
    environment: Mapping[str, str] | None = None,
) -> Path:
    """Return durable receipts for synchronized webcam layouts."""
    return runtime_directory(environment) / "picture-in-picture"


def synchronized_links_directory(
    environment: Mapping[str, str] | None = None,
) -> Path:
    """Return durable receipts for synchronized screen link workflows."""
    return runtime_directory(environment) / "synchronized-links"


def pause_compactions_directory(
    environment: Mapping[str, str] | None = None,
) -> Path:
    """Return durable receipts for synchronized pause-compaction applies."""
    return runtime_directory(environment) / "pause-compactions"


def pause_compaction_finalizations_directory(
    environment: Mapping[str, str] | None = None,
) -> Path:
    """Return durable receipts for compacted timeline finalization."""
    return runtime_directory(environment) / "pause-compaction-finalizations"


def finalized_render_preparations_directory(
    environment: Mapping[str, str] | None = None,
) -> Path:
    """Return durable receipts for finalized timeline render preparation."""
    return runtime_directory(environment) / "finalized-render-preparations"


def finalized_render_executions_directory(
    environment: Mapping[str, str] | None = None,
) -> Path:
    """Return durable receipts for finalized timeline render execution."""
    return runtime_directory(environment) / "finalized-render-executions"


def audio_reports_directory(
    environment: Mapping[str, str] | None = None,
) -> Path:
    """Return the per-user runtime audio reports directory."""
    return runtime_directory(environment) / "audio-reports"


def diagnostics_directory(
    environment: Mapping[str, str] | None = None,
) -> Path:
    """Return the managed local diagnostics output directory."""
    return runtime_directory(environment) / "diagnostics"


def processed_audio_directory(
    environment: Mapping[str, str] | None = None,
) -> Path:
    """Return the durable per-user derived audio directory."""
    return (
        Path(_environment_value("USERPROFILE", environment))
        / "Videos"
        / APPLICATION_DIRECTORY_NAME
        / "processed"
    )


def render_output_directory(
    environment: Mapping[str, str] | None = None,
) -> Path:
    """Return the fixed durable output directory for prepared render jobs."""
    return (
        Path(_environment_value("USERPROFILE", environment))
        / "Videos"
        / APPLICATION_DIRECTORY_NAME
        / "renders"
    )
