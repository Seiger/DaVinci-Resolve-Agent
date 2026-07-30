"""M7 render-job request policy tests."""

import pytest

from agent.rendering import (
    DEFAULT_RENDER_PROFILE,
    RenderPreparationError,
    validate_render_job_id,
    validate_render_name,
    validate_render_profile,
)


def test_render_name_accepts_a_filename_stem() -> None:
    assert validate_render_name("  Урок 01  ") == "Урок 01"


@pytest.mark.parametrize(
    "custom_name",
    ["", ".", "..", "folder/video", "video.", "video|name"],
)
def test_render_name_rejects_paths_and_invalid_names(custom_name: str) -> None:
    with pytest.raises(RenderPreparationError):
        validate_render_name(custom_name)


def test_render_job_id_accepts_an_opaque_identifier() -> None:
    job_id = "0510aff9-fab2-4d17-b7e7-38c37b2b2ed2"

    assert validate_render_job_id(job_id) == job_id


@pytest.mark.parametrize("job_id", ["", "../job", "job id", "x" * 129])
def test_render_job_id_rejects_unsafe_values(job_id: str) -> None:
    with pytest.raises(RenderPreparationError):
        validate_render_job_id(job_id)


def test_render_profiles_are_a_fixed_allowlist() -> None:
    default = validate_render_profile(DEFAULT_RENDER_PROFILE)
    ultra_hd = validate_render_profile("youtube-2160p-h264-v1")

    assert (default.width, default.height) == (1920, 1080)
    assert (ultra_hd.width, ultra_hd.height) == (3840, 2160)
    with pytest.raises(RenderPreparationError, match="Unsupported"):
        validate_render_profile("custom-8k")
