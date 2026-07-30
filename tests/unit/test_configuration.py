"""Configuration loading tests."""

from agent.configuration import load_default_config


def test_default_configuration_loads() -> None:
    config = load_default_config()

    assert config["agent"]["provider"] == "resolve"
    assert config["runtime"]["root"].startswith("${LOCALAPPDATA}")
    assert config["safety"]["allow_destructive"] is False

