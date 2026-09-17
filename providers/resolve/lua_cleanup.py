"""Explicit cleanup of acknowledged stopped sessions; never removes backups."""

from __future__ import annotations

import json
import os
import re
from pathlib import Path
from typing import Any


def cleanup_responses(root: Path, *, confirm: bool = False) -> dict[str, Any]:
    root = root.resolve()
    metadata = json.loads((root / "session.json").read_text(encoding="utf-8"))
    stopped = json.loads((root / "stopped.json").read_text(encoding="utf-8"))
    if stopped.get("session") != metadata.get("session"):
        raise ValueError("Session has no matching acknowledged stop.")
    lock = root / "client.lock"
    with lock.open("x", encoding="ascii") as stream:
        stream.write(str(os.getpid()))
    try:
        if (root / "request.lua").read_text(encoding="ascii").strip() != "return nil":
            raise ValueError("Session mailbox is not idle.")
        for path in (root / "receipts").glob("*.json"):
            if json.loads(path.read_text(encoding="utf-8")).get("status") == "pending":
                raise ValueError("An uncertain write needs its diagnostic responses.")
        candidates = []
        for path in root.glob("*.drp"):
            if re.fullmatch(
                r"[0-9a-f]{32}(?:\.accepted|\.ok(?:_[A-Za-z0-9_-]+)?|\.error_[A-Z_]+)?\.drp",
                path.name,
            ):
                if path.is_symlink() or path.resolve().parent != root:
                    raise ValueError("Response path escapes the session directory.")
                candidates.append(path)
        total = sum(path.stat().st_size for path in candidates)
        if confirm is True:
            for path in candidates:
                path.unlink()
        return {
            "status": "cleaned" if confirm is True else "preview",
            "files": len(candidates),
            "bytes": total,
            "preserved": ["backups", "renders", "receipts", "scripts", "other files"],
        }
    finally:
        lock.unlink(missing_ok=True)
