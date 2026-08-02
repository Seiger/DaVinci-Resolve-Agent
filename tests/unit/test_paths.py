"""Platform path tests."""

from pathlib import Path, PureWindowsPath

from agent.paths import (
    animation_template_runs_directory,
    audio_reports_directory,
    audio_source_directory,
    broll_applications_directory,
    color_treatment_runs_directory,
    config_directory,
    diagnostics_directory,
    editing_recipe_runs_directory,
    finalized_audio_extractions_directory,
    finalized_audio_integrations_directory,
    finalized_render_executions_directory,
    finalized_render_preparations_directory,
    picture_in_picture_directory,
    plans_directory,
    processed_audio_directory,
    render_output_directory,
    runtime_directory,
    subtitle_output_directory,
    subtitle_receipts_directory,
    synchronized_links_directory,
    synchronized_pairs_directory,
    transcription_models_directory,
    visual_treatments_directory,
)


def test_runtime_paths_do_not_contain_a_hardcoded_user_name() -> None:
    first_environment = {
        "APPDATA": r"C:\Users\first-user\AppData\Roaming",
        "LOCALAPPDATA": r"C:\Users\first-user\AppData\Local",
        "USERPROFILE": r"C:\Users\first-user",
    }
    second_environment = {
        "APPDATA": r"D:\Profiles\second-user\Roaming",
        "LOCALAPPDATA": r"D:\Profiles\second-user\Local",
        "USERPROFILE": r"D:\Profiles\second-user",
    }

    first_runtime = runtime_directory(first_environment)
    second_runtime = runtime_directory(second_environment)

    assert first_runtime != second_runtime
    assert PureWindowsPath(str(first_runtime)).parts[-2:] == (
        "DaVinciResolveAgent",
        "runtime",
    )
    assert PureWindowsPath(str(second_runtime)).parts[-2:] == (
        "DaVinciResolveAgent",
        "runtime",
    )
    assert config_directory(first_environment) == (
        Path(first_environment["APPDATA"]) / "DaVinciResolveAgent"
    )
    assert plans_directory(first_environment) == first_runtime / "plans"
    assert synchronized_pairs_directory(first_environment) == (
        first_runtime / "synchronized-pairs"
    )
    assert picture_in_picture_directory(first_environment) == (
        first_runtime / "picture-in-picture"
    )
    assert synchronized_links_directory(first_environment) == (
        first_runtime / "synchronized-links"
    )
    assert finalized_render_preparations_directory(first_environment) == (
        first_runtime / "finalized-render-preparations"
    )
    assert finalized_render_executions_directory(first_environment) == (
        first_runtime / "finalized-render-executions"
    )
    assert finalized_audio_extractions_directory(first_environment) == (
        first_runtime / "finalized-audio-extractions"
    )
    assert finalized_audio_integrations_directory(first_environment) == (
        first_runtime / "finalized-audio-integrations"
    )
    assert audio_reports_directory(first_environment) == (
        first_runtime / "audio-reports"
    )
    assert subtitle_receipts_directory(first_environment) == (
        first_runtime / "subtitle-receipts"
    )
    assert editing_recipe_runs_directory(first_environment) == (
        first_runtime / "editing-recipe-runs"
    )
    assert visual_treatments_directory(first_environment) == (
        first_runtime / "visual-treatments"
    )
    assert broll_applications_directory(first_environment) == (
        first_runtime / "broll-applications"
    )
    assert animation_template_runs_directory(first_environment) == (
        first_runtime / "animation-template-runs"
    )
    assert color_treatment_runs_directory(first_environment) == (
        first_runtime / "color-treatment-runs"
    )
    assert transcription_models_directory(first_environment) == (
        first_runtime / "models" / "faster-whisper"
    )
    assert diagnostics_directory(first_environment) == (
        first_runtime / "diagnostics"
    )
    assert processed_audio_directory(first_environment) == (
        Path(r"C:\Users\first-user")
        / "Videos"
        / "DaVinciResolveAgent"
        / "processed"
    )
    assert render_output_directory(first_environment) == (
        Path(r"C:\Users\first-user")
        / "Videos"
        / "DaVinciResolveAgent"
        / "renders"
    )
    assert subtitle_output_directory(first_environment) == (
        Path(r"C:\Users\first-user")
        / "Videos"
        / "DaVinciResolveAgent"
        / "subtitles"
    )
    assert audio_source_directory(first_environment) == (
        Path(r"C:\Users\first-user")
        / "Videos"
        / "DaVinciResolveAgent"
        / "audio-sources"
    )
