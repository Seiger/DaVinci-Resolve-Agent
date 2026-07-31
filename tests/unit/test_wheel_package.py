"""Wheel package boundary tests."""

from __future__ import annotations

import zipfile
from pathlib import Path

import pytest

from scripts.check_wheel import (
    EXPECTED_ENTRY_POINTS,
    REQUIRED_MEMBERS,
    WheelValidationError,
    validate_wheel_directory,
)

DIST_INFO = "davinci_resolve_agent-0.1.0.dist-info"


def _valid_members() -> dict[str, str]:
    members = {name: "fixture" for name in REQUIRED_MEMBERS}
    members[f"{DIST_INFO}/METADATA"] = (
        "Metadata-Version: 2.4\n"
        "Name: davinci-resolve-agent\n"
        "Version: 0.1.0\n"
        "Requires-Python: <3.13,>=3.10\n"
    )
    entry_points = "\n".join(
        f"{name} = {target}" for name, target in EXPECTED_ENTRY_POINTS.items()
    )
    members[f"{DIST_INFO}/entry_points.txt"] = (
        f"[console_scripts]\n{entry_points}\n"
    )
    return members


def _write_wheel(
    directory: Path,
    *,
    filename: str = "davinci_resolve_agent-0.1.0-py3-none-any.whl",
    members: dict[str, str] | None = None,
) -> Path:
    directory.mkdir(parents=True, exist_ok=True)
    wheel = directory / filename
    with zipfile.ZipFile(wheel, mode="w") as archive:
        for name, contents in (members or _valid_members()).items():
            archive.writestr(name, contents)
    return wheel


def test_valid_wheel_package_passes(tmp_path: Path) -> None:
    wheel = _write_wheel(tmp_path)

    assert validate_wheel_directory(tmp_path) == wheel


def test_wheel_package_rejects_missing_required_member(tmp_path: Path) -> None:
    members = _valid_members()
    members.pop("contracts/examples/commands.json")
    _write_wheel(tmp_path, members=members)

    with pytest.raises(WheelValidationError, match="missing required members"):
        validate_wheel_directory(tmp_path)


def test_wheel_package_rejects_unsafe_archive_path(tmp_path: Path) -> None:
    members = _valid_members()
    members["../escape.py"] = "unsafe"
    _write_wheel(tmp_path, members=members)

    with pytest.raises(WheelValidationError, match="Unsafe wheel archive path"):
        validate_wheel_directory(tmp_path)


def test_wheel_package_requires_exactly_one_wheel(tmp_path: Path) -> None:
    _write_wheel(tmp_path)
    _write_wheel(
        tmp_path,
        filename="davinci_resolve_agent-0.1.0-1-py3-none-any.whl",
    )

    with pytest.raises(WheelValidationError, match="exactly one wheel"):
        validate_wheel_directory(tmp_path)
