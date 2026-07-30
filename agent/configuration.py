"""Configuration loading for repository defaults."""

from __future__ import annotations

import sys
from importlib import resources
from pathlib import Path
from typing import Any

from agent.paths import config_file

if sys.version_info >= (3, 11):
    import tomllib
else:  # pragma: no cover - exercised on Python 3.10
    import tomli as tomllib


class ConfigurationError(ValueError):
    """Raised when the application configuration is invalid."""


def load_default_config() -> dict[str, Any]:
    """Load and minimally validate the packaged default configuration."""
    config_resource = resources.files("config").joinpath("default.toml")
    with config_resource.open("rb") as config_file:
        loaded: dict[str, Any] = tomllib.load(config_file)

    required_sections = ("agent", "runtime", "resolve", "safety")
    missing_sections = [
        section for section in required_sections if section not in loaded
    ]
    if missing_sections:
        missing = ", ".join(missing_sections)
        raise ConfigurationError(f"Missing required configuration sections: {missing}")

    return loaded


def load_config(path: Path | None = None) -> dict[str, Any]:
    """Load the machine-local config, falling back to packaged defaults."""
    local_path = config_file() if path is None else path
    if not local_path.is_file():
        return load_default_config()

    try:
        with local_path.open("rb") as config_stream:
            loaded: dict[str, Any] = tomllib.load(config_stream)
    except (OSError, tomllib.TOMLDecodeError) as error:
        raise ConfigurationError(
            f"Local configuration is unreadable: {error}"
        ) from error

    required_sections = ("agent", "runtime", "resolve", "safety", "media")
    missing_sections = [
        section for section in required_sections if section not in loaded
    ]
    if missing_sections:
        missing = ", ".join(missing_sections)
        raise ConfigurationError(
            f"Local configuration is missing sections: {missing}"
        )
    return loaded
