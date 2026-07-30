"""M7 render-job request policy tests."""

import pytest

from agent.rendering import RenderPreparationError, validate_render_name


def test_render_name_accepts_a_filename_stem() -> None:
    assert validate_render_name("  Урок 01  ") == "Урок 01"


@pytest.mark.parametrize(
    "custom_name",
    ["", ".", "..", "folder/video", "video.", "video|name"],
)
def test_render_name_rejects_paths_and_invalid_names(custom_name: str) -> None:
    with pytest.raises(RenderPreparationError):
        validate_render_name(custom_name)
