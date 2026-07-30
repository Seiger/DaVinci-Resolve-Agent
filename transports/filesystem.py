"""Provider-neutral filesystem transport primitives."""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class FilesystemLayout:
    """Filesystem queue layout rooted in the local runtime directory."""

    root: Path

    @property
    def commands(self) -> Path:
        return self.root / "commands"

    @property
    def processing(self) -> Path:
        return self.root / "processing"

    @property
    def responses(self) -> Path:
        return self.root / "responses"

    @property
    def failed(self) -> Path:
        return self.root / "failed"

    @property
    def state(self) -> Path:
        return self.root / "state"

    @property
    def logs(self) -> Path:
        return self.root / "logs"

    @property
    def backups(self) -> Path:
        return self.root / "backups"

    @property
    def plans(self) -> Path:
        return self.root / "plans"

    @property
    def audio_reports(self) -> Path:
        return self.root / "audio-reports"

    def directories(self) -> tuple[Path, ...]:
        """Return every directory owned by the runtime layout."""
        return (
            self.commands,
            self.processing,
            self.responses,
            self.failed,
            self.state,
            self.logs,
            self.backups,
            self.plans,
            self.audio_reports,
        )

    def ensure_directories(self) -> None:
        """Create the complete runtime layout idempotently."""
        for directory in self.directories():
            directory.mkdir(parents=True, exist_ok=True)


def atomic_write_json(path: Path, payload: dict[str, Any]) -> None:
    """Write a JSON object atomically beside its final destination."""
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary_path = path.with_name(f"{path.name}.tmp")
    with temporary_path.open("w", encoding="utf-8", newline="\n") as output:
        json.dump(payload, output, ensure_ascii=False, indent=2, sort_keys=True)
        output.write("\n")
        output.flush()
        os.fsync(output.fileno())
    temporary_path.replace(path)


def read_json_object(path: Path) -> dict[str, Any]:
    """Read a JSON object from disk."""
    with path.open("r", encoding="utf-8") as input_file:
        loaded = json.load(input_file)
    if not isinstance(loaded, dict):
        raise ValueError(f"Expected a JSON object in {path}.")
    return loaded
