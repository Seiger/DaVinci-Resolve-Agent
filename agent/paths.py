"""Platform path resolution without machine-specific absolute paths."""

from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path

from agent import storage

PathConfigurationError = storage.StorageConfigurationError


def config_directory(environment: Mapping[str, str] | None = None) -> Path:
    """Return the per-user application configuration directory."""
    return storage.config_directory(environment)


def config_file(environment: Mapping[str, str] | None = None) -> Path:
    """Return the per-user application configuration file."""
    return storage.config_file(environment)


def runtime_directory(environment: Mapping[str, str] | None = None) -> Path:
    """Return the configured local runtime directory."""
    return storage.runtime_root(environment)


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
    return storage.managed_media_root(environment) / "processed"


def subtitle_output_directory(
    environment: Mapping[str, str] | None = None,
) -> Path:
    """Return the durable per-user generated subtitle directory."""
    return storage.managed_media_root(environment) / "subtitles"


def transcription_models_directory(
    environment: Mapping[str, str] | None = None,
) -> Path:
    """Return the managed local cache for speech-to-text models."""
    return runtime_directory(environment) / "models" / "faster-whisper"


def subtitle_receipts_directory(
    environment: Mapping[str, str] | None = None,
) -> Path:
    """Return durable receipts for generated subtitle applications."""
    return runtime_directory(environment) / "subtitle-receipts"


def editing_recipe_runs_directory(
    environment: Mapping[str, str] | None = None,
) -> Path:
    """Return durable receipts for declarative editing recipe runs."""
    return runtime_directory(environment) / "editing-recipe-runs"


def visual_treatments_directory(
    environment: Mapping[str, str] | None = None,
) -> Path:
    """Return durable receipts for confirmed title and reframing workflows."""
    return runtime_directory(environment) / "visual-treatments"


def baseline_edit_runs_directory(
    environment: Mapping[str, str] | None = None,
) -> Path:
    """Return durable receipts for baseline end-to-end edit runs."""
    return runtime_directory(environment) / "baseline-edit-runs"


def broll_applications_directory(
    environment: Mapping[str, str] | None = None,
) -> Path:
    """Return durable receipts for reviewed B-roll applications."""
    return runtime_directory(environment) / "broll-applications"


def animation_template_runs_directory(
    environment: Mapping[str, str] | None = None,
) -> Path:
    """Return durable receipts for confirmed animation-template runs."""
    return runtime_directory(environment) / "animation-template-runs"


def color_treatment_runs_directory(
    environment: Mapping[str, str] | None = None,
) -> Path:
    """Return durable receipts for confirmed color-treatment runs."""
    return runtime_directory(environment) / "color-treatment-runs"


def take_selections_directory(
    environment: Mapping[str, str] | None = None,
) -> Path:
    """Return durable M54 technical take-selection reports."""
    return runtime_directory(environment) / "take-selections"


def take_selection_reviews_directory(
    environment: Mapping[str, str] | None = None,
) -> Path:
    """Return immutable human review records for M54 selections."""
    return runtime_directory(environment) / "take-selection-reviews"


def take_sequences_directory(
    environment: Mapping[str, str] | None = None,
) -> Path:
    """Return immutable M54.4 approved take-sequence plans."""
    return runtime_directory(environment) / "take-sequences"


def take_sequence_bindings_directory(
    environment: Mapping[str, str] | None = None,
) -> Path:
    """Return M55 machine-local approved-sequence source bindings."""
    return runtime_directory(environment) / "take-sequence-bindings"


def take_sequence_media_imports_directory(
    environment: Mapping[str, str] | None = None,
) -> Path:
    """Return durable M55 confirmed Media Pool import receipts."""
    return runtime_directory(environment) / "take-sequence-media-imports"


def take_sequence_timeline_applications_directory(
    environment: Mapping[str, str] | None = None,
) -> Path:
    """Return durable M55.6 duplicate-timeline application receipts."""
    return runtime_directory(environment) / "take-sequence-timeline-applications"


def take_sequence_qc_reports_directory(
    environment: Mapping[str, str] | None = None,
) -> Path:
    """Return durable M55.7 structural sequence QC reports."""
    return runtime_directory(environment) / "take-sequence-qc-reports"


def take_sequence_qc_reviews_directory(
    environment: Mapping[str, str] | None = None,
) -> Path:
    """Return immutable M55.7 human sequence QC reviews."""
    return runtime_directory(environment) / "take-sequence-qc-reviews"


def render_output_directory(
    environment: Mapping[str, str] | None = None,
) -> Path:
    """Return the fixed durable output directory for prepared render jobs."""
    return storage.managed_media_root(environment) / "renders"


def audio_source_directory(
    environment: Mapping[str, str] | None = None,
) -> Path:
    """Return the managed directory for full-timeline PCM WAV exports."""
    return storage.managed_media_root(environment) / "audio-sources"


def finalized_audio_extractions_directory(
    environment: Mapping[str, str] | None = None,
) -> Path:
    """Return durable receipts for finalized timeline audio extraction."""
    return runtime_directory(environment) / "finalized-audio-extractions"


def finalized_audio_integrations_directory(
    environment: Mapping[str, str] | None = None,
) -> Path:
    """Return durable receipts for cleaned-audio timeline integration."""
    return runtime_directory(environment) / "finalized-audio-integrations"
