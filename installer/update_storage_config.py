"""Update only resolved storage paths in the machine-local TOML config."""

from __future__ import annotations

import argparse
import os
import re
from pathlib import Path

SECTION_PATTERN = re.compile(r"(?m)^\[([A-Za-z0-9_.-]+)\][ \t]*$")


class StorageConfigUpdateError(ValueError):
    """Raised when the bounded TOML update cannot be completed safely."""


def update_storage_config(config_path: Path, data_root: Path) -> None:
    """Atomically update three installer-owned storage keys."""
    resolved_root = data_root.resolve()
    if not resolved_root.is_absolute() or resolved_root == Path(resolved_root.anchor):
        raise StorageConfigUpdateError(
            "data_root must be an absolute non-volume-root path."
        )
    try:
        text = config_path.read_text(encoding="utf-8")
    except OSError as error:
        raise StorageConfigUpdateError(f"Config is unreadable: {error}") from error
    newline = "\r\n" if "\r\n" in text else "\n"
    root_value = resolved_root.as_posix()
    updated = _set_string(text, "runtime", "root", f"{root_value}/runtime", newline)
    updated = _set_string(
        updated,
        "media",
        "managed_root",
        f"{root_value}/media",
        newline,
    )
    updated = _set_string(updated, "storage", "data_root", root_value, newline)
    temporary = config_path.with_name(f"{config_path.name}.tmp")
    try:
        with temporary.open("w", encoding="utf-8", newline="") as stream:
            stream.write(updated)
            stream.flush()
            os.fsync(stream.fileno())
        temporary.replace(config_path)
    except OSError as error:
        temporary.unlink(missing_ok=True)
        raise StorageConfigUpdateError(f"Config update failed: {error}") from error


def _set_string(
    text: str,
    section: str,
    key: str,
    value: str,
    newline: str,
) -> str:
    if '"' in value or "\n" in value or "\r" in value:
        raise StorageConfigUpdateError("Storage path contains unsafe TOML text.")
    matches = list(SECTION_PATTERN.finditer(text))
    section_match = next(
        (match for match in matches if match.group(1) == section),
        None,
    )
    assignment = f'{key} = "{value}"'
    if section_match is None:
        separator = "" if not text or text.endswith(("\n", "\r")) else newline
        return f"{text}{separator}{newline}[{section}]{newline}{assignment}{newline}"
    section_end = next(
        (
            match.start()
            for match in matches
            if match.start() > section_match.start()
        ),
        len(text),
    )
    body_start = section_match.end()
    body = text[body_start:section_end]
    key_pattern = re.compile(rf"(?m)^[ \t]*{re.escape(key)}[ \t]*=.*$")
    key_match = key_pattern.search(body)
    if key_match is not None:
        absolute_start = body_start + key_match.start()
        absolute_end = body_start + key_match.end()
        return f"{text[:absolute_start]}{assignment}{text[absolute_end:]}"
    insertion = f"{newline}{assignment}"
    return f"{text[:body_start]}{insertion}{text[body_start:]}"


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("config_path", type=Path)
    parser.add_argument("data_root", type=Path)
    arguments = parser.parse_args()
    update_storage_config(arguments.config_path, arguments.data_root)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
