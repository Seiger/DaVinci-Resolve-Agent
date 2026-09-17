"""Opt-in Lua prototype using a local mailbox and DRP snapshots.

The mailbox contains client-generated Lua literals, never caller-supplied code.
It must remain in a trusted local directory, like the installed bridge itself.
No GUI automation is imported or invoked by this transport.
"""

from __future__ import annotations

import json
import math
import os
import re
import time
import zipfile
from pathlib import Path
from typing import Any
from uuid import uuid4
from xml.etree import ElementTree as ET

from agent.client import BridgeProtocolError, CommandTimeoutError
from providers.resolve.lua_editing import (
    WRITE_ACTIONS,
    WriteReceipt,
    atomic_json,
    bounded_text,
    lua_value,
    validate_edit,
)
from providers.resolve.lua_finishing import (
    FINISH_ACTIONS,
    validate_finishing,
    verify_video,
)


class LuaCommandTimeoutError(CommandTimeoutError):
    """A missing prototype response, without suggesting the Python bridge."""

    def __init__(self, command_id: str, timeout_seconds: float) -> None:
        super().__init__(command_id, timeout_seconds)
        self.args = (
            "No experimental Lua response within the timeout. Open a saved "
            "project and start this session's bridge.lua in the Lua console; "
            "the loop stops after two hours. Export failures also time out.",
        )


def lua_string(value: str) -> str:
    """Encode UTF-8 as fixed-width decimal escapes, without executable syntax."""
    return '"' + "".join(f"\\{byte:03d}" for byte in value.encode("utf-8")) + '"'


def prepare(root: Path, media_roots: list[Path] | None = None) -> Path:
    """Create a new isolated session; never overwrite a running session."""
    root = root.resolve()
    root.mkdir(parents=True, exist_ok=False)
    session = uuid4().hex
    roots = [path.resolve().as_posix() for path in (media_roots or [])]
    if any(not Path(path).is_dir() for path in roots):
        raise ValueError("Every allowed media root must be an existing directory.")
    source = (
        Path(__file__).resolve().parents[2]
        / "bridges"
        / "resolve"
        / "ResolveLuaBridge.lua"
    ).read_text(encoding="utf-8")
    source = source.replace('"__RUNTIME_ROOT__"', lua_string(root.as_posix()))
    source = source.replace('"__SESSION__"', lua_string(session))
    source = source.replace("__MEDIA_ROOTS__", lua_value(roots))
    (root / "bridge.lua").write_text(source, encoding="utf-8")
    editing = (
        Path(__file__).resolve().parents[2]
        / "bridges"
        / "resolve"
        / "ResolveLuaEditing.lua"
    )
    (root / "editing.lua").write_text(
        editing.read_text(encoding="utf-8"), encoding="utf-8"
    )
    (root / "finishing.lua").write_text(
        editing.with_name("ResolveLuaFinishing.lua").read_text(encoding="utf-8"),
        encoding="utf-8",
    )
    (root / "session.json").write_text(
        json.dumps({"session": session, "protocol": 3, "media_roots": roots}),
        encoding="utf-8",
    )
    (root / "request.lua").write_text("return nil\n", encoding="ascii")
    return root / "bridge.lua"


def read_project_snapshot(path: Path) -> dict[str, str]:
    """Read only the bounded project XML, without extracting archive paths."""
    if path.stat().st_size > 512 * 1024 * 1024:
        raise BridgeProtocolError("Experimental DRP response exceeds 512 MiB.")
    with zipfile.ZipFile(path) as archive:
        info = archive.getinfo("project.xml")
        if info.file_size > 16 * 1024 * 1024:
            raise BridgeProtocolError("Project XML exceeds 16 MiB.")
        data = archive.read(info)
    if b"<!DOCTYPE" in data.upper() or b"<!ENTITY" in data.upper():
        raise BridgeProtocolError("DTD/entity declarations are not accepted.")
    # Resolve's later payload can contain non-XML element names (for example
    # numeric configuration keys). Parse only its identity header, not that
    # undocumented project graph. Never rewrite/import the archive.
    end = data.find(b"</ProjectName>")
    if end < 0 or end > 1024 * 1024:
        raise BridgeProtocolError("Export has no bounded project identity header.")
    project = ET.fromstring(data[: end + len(b"</ProjectName>")] + b"</SM_Project>")
    name, identity = project.findtext("ProjectName"), project.get("DbId")
    if project.tag != "SM_Project" or not name or not identity:
        raise BridgeProtocolError("Export has no recognized project identity.")
    return {"name": name, "id": identity}


class LuaSnapshotClient:
    """One serialized request per session; requires an open Resolve project."""

    def __init__(self, root: Path) -> None:
        self.root = root.resolve()
        metadata = json.loads((self.root / "session.json").read_text(encoding="utf-8"))
        self.session = metadata["session"]
        self.protocol = metadata.get("protocol", 1)
        self.media_roots = [Path(p) for p in metadata.get("media_roots", [])]
        if not isinstance(self.session, str) or len(self.session) != 32:
            raise ValueError("Invalid Lua session.")

    def request(
        self,
        action: str,
        timeout_seconds: float = 30,
        *,
        arguments: dict[str, Any] | None = None,
        expected_project_id: str | None = None,
        confirm: bool = False,
        idempotency_key: str | None = None,
    ) -> dict[str, Any]:
        if (self.root / "stopped.json").exists():
            raise ValueError(
                "Session is stopped. Prepare a new runtime before restarting."
            )
        if (
            action
            not in {"ping", "get_current_project", "stop", "get_render_status"}
            | WRITE_ACTIONS
            | FINISH_ACTIONS
        ):
            raise ValueError("Unsupported experimental Lua action.")
        if not math.isfinite(timeout_seconds) or not 0 < timeout_seconds <= 120:
            raise ValueError("Timeout must be finite and between 0 and 120 seconds.")
        write = action in WRITE_ACTIONS | FINISH_ACTIONS
        status_request = action == "get_render_status"
        if (action in FINISH_ACTIONS or status_request) and self.protocol != 3:
            raise ValueError("Finishing requires a new protocol-3 session.")
        normalized: dict[str, Any] = {}
        receipt = None
        if write:
            if self.protocol not in {2, 3} or confirm is not True:
                raise ValueError(
                    "Editing requires a protocol-2 or protocol-3 session "
                    "and explicit confirmation."
                )
            project_id = bounded_text(expected_project_id, "Expected project ID")
            bounded_text(idempotency_key, "Idempotency key")
            validator = (
                validate_finishing if action in FINISH_ACTIONS else validate_edit
            )
            normalized = validator(action, arguments or {}, self.media_roots)
            assert idempotency_key is not None
            receipt = WriteReceipt(
                self.root, idempotency_key, action, project_id, normalized
            )
        elif status_request:
            bounded_text(expected_project_id, "Expected project ID")
            if confirm or idempotency_key:
                raise ValueError("Status is read-only.")
            normalized = validate_finishing(action, arguments or {}, self.media_roots)
        elif arguments or expected_project_id or confirm or idempotency_key:
            raise ValueError("Read requests accept no editing arguments.")
        owned_job = None
        if action in {"start_render", "get_render_status"}:
            for path in (self.root / "receipts").glob("*.json"):
                saved = json.loads(path.read_text(encoding="utf-8"))
                saved_result = saved.get("result", {})
                if (
                    saved.get("status") == "completed"
                    and saved_result.get("action") == "prepare_render"
                    and saved_result.get("job_id") == normalized["job_id"]
                    and saved_result.get("project", {}).get("id") == expected_project_id
                ):
                    owned_job = saved_result
                    break
            if owned_job is None:
                raise ValueError("Render job is not owned by this session and project.")
        lock = self.root / "client.lock"
        # Exclusive filesystem ownership also prevents independent MCP processes
        # from overwriting each other's mailbox. A crash leaves an explicit lock.
        with lock.open("x", encoding="ascii") as stream:
            stream.write(str(os.getpid()))
        command_id = uuid4().hex
        response = self.root / (
            f"{command_id}.ok.drp" if write else f"{command_id}.drp"
        )
        pending = self.root / f"{command_id}.tmp"
        try:
            if (self.root / "stopped.json").exists():
                raise ValueError("Session is stopped. Prepare a new runtime.")
            if receipt:
                replay = receipt.replay()
                if replay is not None:
                    return replay
                receipt.begin(command_id)
            if action == "prepare_render":
                (self.root / "renders" / command_id).mkdir(parents=True, exist_ok=False)
            expires = math.ceil(time.time() + timeout_seconds)
            payload = (
                "return {session="
                + lua_string(self.session)
                + ",id="
                + lua_string(command_id)
                + ",action="
                + lua_string(action)
                + f",expires={expires}"
                + (
                    (",confirm=true,project_id=" if write else ",project_id=")
                    + lua_string(str(expected_project_id))
                    + ",arguments="
                    + lua_value(normalized)
                    if write or status_request
                    else ""
                )
                + "}\n"
            )
            pending.write_text(payload, encoding="ascii")
            pending.replace(self.root / "request.lua")
            deadline = time.monotonic() + timeout_seconds
            while time.monotonic() < deadline:
                try:
                    errors = (
                        list(self.root.glob(f"{command_id}.error_*.drp"))
                        if write or status_request
                        else []
                    )
                    if errors:
                        read_project_snapshot(
                            errors[0]
                        )  # wait for a complete error export
                        code = (
                            errors[0].name.split(".error_", 1)[1].removesuffix(".drp")
                        )
                        if receipt and code in {
                            "INVALID_ARGUMENTS",
                            "PROJECT_CHANGED",
                            "RENDERING",
                            "NAME_EXISTS",
                            "MEDIA_NOT_ALLOWED",
                            "ASSET_EXISTS",
                            "AMBIGUOUS_ASSET",
                            "AMBIGUOUS_TIMELINE",
                            "POOL_TOO_LARGE",
                            "TIMELINE_TOO_LARGE",
                            "TIMELINE_NOT_FOUND",
                            "ASSET_NOT_FOUND",
                            "INVALID_RANGE",
                            "BACKUP_SAVE_FAILED",
                            "BACKUP_EXPORT_FAILED",
                            "EXPIRED",
                            "ITEM_NOT_FOUND",
                            "SOURCE_CHANGED",
                            "SUBTITLES_EXIST",
                            "EMPTY_TIMELINE",
                            "JOB_NOT_OWNED",
                            "JOB_ALREADY_STARTED",
                        }:
                            receipt.reject(code)
                        raise BridgeProtocolError(
                            f"Lua edit failed: {code}. No automatic retry; "
                            "inspect the receipt and backup."
                        )
                    token = None
                    if action == "prepare_render" or status_request:
                        matches = list(self.root.glob(f"{command_id}.ok_*.drp"))
                        if not matches:
                            raise FileNotFoundError("Waiting for typed response.")
                        if len(matches) != 1:
                            raise BridgeProtocolError("Ambiguous typed response.")
                        response = matches[0]
                        token = response.name[len(command_id) + 4 : -4]
                    project = read_project_snapshot(response)
                except (OSError, zipfile.BadZipFile, EOFError, KeyError, ET.ParseError):
                    # ExportProject creates the file before writing the ZIP footer.
                    time.sleep(0.1)
                    continue
                if write:
                    if project["id"] != expected_project_id:
                        raise BridgeProtocolError(
                            "Write response belongs to another project; "
                            "outcome is uncertain."
                        )
                    backup = self.root / f"{command_id}.before.drp"
                    if read_project_snapshot(backup)["id"] != expected_project_id:
                        raise BridgeProtocolError("Write backup identity mismatch.")
                    result: dict[str, Any] = {
                        "status": "completed",
                        "action": action,
                        "project": project,
                        "arguments": normalized,
                        "backup_path": str(backup),
                        "response_path": str(response),
                        "replayed": False,
                        "readback_verified_by": "ResolveLuaFinishing"
                        if action in FINISH_ACTIONS
                        else "ResolveLuaEditing",
                    }
                    if action == "prepare_render":
                        if not token or not re.fullmatch(
                            r"job_[a-zA-Z0-9-]{1,64}", token
                        ):
                            raise BridgeProtocolError(
                                "Invalid render job acknowledgement."
                            )
                        result.update(
                            job_id=token[4:],
                            output_path=str(
                                self.root / "renders" / command_id / "video.mp4"
                            ),
                        )
                    assert receipt is not None
                    receipt.complete(result)
                    return result
                if status_request:
                    if project["id"] != expected_project_id or token not in {
                        "state_complete",
                        "state_failed",
                        "state_running",
                        "state_queued",
                        "state_unknown",
                    }:
                        raise BridgeProtocolError(
                            "Invalid render status acknowledgement."
                        )
                    assert owned_job is not None
                    result = {
                        "status": token[6:],
                        "job_id": normalized["job_id"],
                        "project": project,
                    }
                    if token == "state_complete":
                        result["output"] = verify_video(Path(owned_job["output_path"]))
                    return result
                if action == "ping":
                    return {"message": "pong", "transport": "experimental_lua_snapshot"}
                if action == "stop":
                    atomic_json(self.root / "stopped.json", {"session": self.session})
                    return {"status": "stopping"}
                return {"project": project, "source": "exported_snapshot"}
            raise LuaCommandTimeoutError(command_id, timeout_seconds)
        finally:
            try:
                (self.root / "request.lua").write_text("return nil\n", encoding="ascii")
                pending.unlink(missing_ok=True)
                # Retain archives locally for diagnosis; never upload/commit them.
            finally:
                lock.unlink(missing_ok=True)
