"""Reserve a same-key attempt only after an exact native pre-import rejection."""
from __future__ import annotations

import hashlib
import json
import math
import shutil
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any
from uuid import UUID

from bridges.resolve import ResolveBridge as bridge
from providers.resolve.automatic_connection import process_alive
from providers.resolve.lua_editing import atomic_json
from providers.resolve.marker_supervisor import Profile, read_active
from providers.resolve.marker_transport import MarkerSlot
from providers.resolve.preset_envelope import read_payload
from providers.resolve.remote_sdk import RemoteSDK
from providers.resolve.sdk_api import SDK_MUTATIONS


class ImportRetryError(RuntimeError):
    """Missing or changed proof never authorizes another native mutation."""

    code = "ORIGINAL_SDK_OPERATION_REQUIRES_RECOVERY"


@dataclass(frozen=True)
class ImportRetry:
    """One lock-scoped reservation; the SDK must freshly verify this project."""

    active: dict[str, Any]
    project_id: str


def _check(condition: bool, reason: str) -> None:
    if not condition:
        raise ImportRetryError(reason)


def _safe(path: Path) -> Path:
    for candidate in (path, *path.parents):
        if candidate.is_symlink() or (
            candidate.exists()
            and getattr(candidate.lstat(), "st_file_attributes", 0) & 0x400
        ):
            raise ImportRetryError("Linked import retry evidence.")
    return path


def _read(path: Path) -> dict[str, Any]:
    _safe(path)
    with path.open("rb") as stream:
        raw = stream.read(4 * 1024 * 1024 + 1)
    _check(len(raw) <= 4 * 1024 * 1024, "Import retry evidence exceeds its bound.")
    value = json.loads(raw)
    _check(isinstance(value, dict), "Invalid import retry evidence.")
    return dict(value)


def _hash(path: Path) -> str:
    digest = hashlib.sha256()
    with _safe(path).open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _bound_reply(trace: dict[str, Any], reply: dict[str, Any]) -> None:
    raw = bytes.fromhex(reply["request_hex"])
    _check(hashlib.sha256(raw).hexdigest() == trace["request_sha256"],
           "Native import acknowledgement hash changed.")
    _check(json.loads(raw) == {"operation": trace["operation"],
                              "call": trace["call"]},
           "Native import acknowledgement belongs to another request.")
    packet = trace["packet"]
    part = packet["arguments"]["sdk"]
    count = math.ceil(len(raw) / 2000)
    _check(packet["session"] == trace["session"]
           and packet["id"] == trace["message_id"]
           and part == {"id": trace["id"], "seq": count, "count": count,
                        "data": raw[(count - 1) * 2000:].decode("ascii")}
           and trace["part"] == count,
           "Original SDK packet changed.")


class _Snapshot:
    def __init__(self, reply: dict[str, Any]) -> None:
        self.reply = reply

    def exchange(self, payload: dict[str, Any]) -> dict[str, Any]:
        _check(payload == {"kind": "root"}, "Original project identity is uncached.")
        return self.reply


def _proof(
    profile: Profile, command: dict[str, Any], owner: dict[str, Any],
    ledger: dict[str, Any], active: dict[str, Any],
) -> tuple[dict[str, Any], dict[str, Any], str, list[Path]]:
    root = _safe(Path(owner["runtime"]))
    _check(root.resolve().parent == profile.runtime_base.resolve(),
           "Original import runtime is outside its profile.")
    _check(all(owner.get(k) == active.get(k) for k in
               ("runtime", "session", "generation")), "Import generation changed.")
    _check(owner.get("transport") == "lua_marker_preset",
           "An import retry cannot switch native transport.")
    fingerprint = bridge._request_fingerprint(command)
    old_id = owner["command_id"]
    _check(isinstance(old_id, str) and str(UUID(old_id)) == old_id,
           "Original import command UUID is invalid.")
    _check(old_id != command["command_id"], "An attempt cannot redispatch itself.")
    original_path = profile.runtime_base / "failed" / (old_id + ".json")
    original = bridge.validate_command(_read(original_path), allow_expired=True)
    _check(original["action"] == "import_media"
           and original["idempotency_key"] == command["idempotency_key"]
           and original["command_id"] == old_id
           and bridge._request_fingerprint(original) == fingerprint
           and original["arguments"] == command["arguments"]
           and original["safety"] == command["safety"]
           and original["safety"] == {"create_backup": True,
                                      "allow_destructive": False},
           "Original import arguments/key changed.")
    _check(owner["fingerprint"] == fingerprint
           and owner["phase"] in {"completed", "uncertain", "dispatch_started"}
           and ledger.get("phase") == owner["phase"]
           and ledger.get("command_id") == old_id
           and ledger.get("session") == owner["session"]
           and ledger.get("fingerprint") == fingerprint,
           "Import owner and SDK ledger disagree.")
    response_path = profile.runtime_base / "responses" / (old_id + ".json")
    failed = _read(response_path)
    _check(failed.get("command_id") == old_id and failed.get("status") == "error"
           and failed.get("error", {}).get("code") in {
               "RESOLVE_OPERATION_FAILED", "SDK_OPERATION_EXPIRED"},
           "Original import is not a failed attempt.")
    if owner["phase"] == "completed":
        _check(owner.get("response") == failed and ledger.get("response") == failed,
               "Terminal import responses disagree.")
    else:
        _check(owner.get("response") is None and ledger.get("response") is None,
               "Uncertain import contains a conflicting terminal response.")
    receipt = bridge._receipt_path(profile.runtime_base / "state",
                                   command["idempotency_key"])
    _check(not _safe(receipt).exists(), "Import already has a canonical receipt.")
    backup = _safe(Path(failed["error"]["details"]["backup_path"]))
    _check(backup.resolve().parent == (profile.runtime_base / "backups").resolve()
           and backup.is_file() and backup.stat().st_size > 0,
           "Original import backup is missing.")
    records: list[tuple[Path, dict[str, Any]]] = []
    for count, path in enumerate(_safe(root / "sdk-trace").glob("*.json")):
        _check(count < 4096, "Import trace discovery exceeds its bound.")
        trace = _read(path)
        if trace.get("operation", {}).get("id") == UUID(old_id).hex:
            op = trace["operation"]
            _check(trace.get("session") == owner["session"]
                   and op.get("action") == "import_media"
                   and op.get("fingerprint") == fingerprint
                   and op.get("create_backup") is True
                   and op.get("allow_destructive") is False
                   and op.get("expires") == int(datetime.fromisoformat(
                       original["expires_at"].replace("Z", "+00:00")).timestamp())
                   and path.name == trace["id"] + ".json",
                   "Original import trace scope changed.")
            records.append((path, trace))
    imports = [t for _, t in records if t["call"].get("method") == "ImportMedia"]
    _check(len(imports) == 1, "Import invocation history is ambiguous.")
    rejection = imports[0]
    _check(rejection.get("phase") in {"completed", "uncertain", "dispatch_started"}
           and rejection["call"].get("kind") == "call"
           and rejection["call"].get("arguments") == {
               "a": [{"a": original["arguments"]["paths"]}]},
           "Native import paths changed.")
    outputs = [root / ("sdk-" + rejection["id"] + suffix)
               for suffix in (".preset", ".ready.preset")]
    replies = [read_payload(_safe(p), session=owner["session"],
                           command_id=rejection["id"], direction="O") for p in outputs]
    reply = replies[0]
    _check(reply == replies[1] and reply.get("error") == "SDK_OPERATION_EXPIRED"
           and reply.get("result") is None and reply.get("objects") == {},
           "No exact pre-ImportMedia rejection acknowledgement.")
    _bound_reply(rejection, reply)
    roots = []
    saves, exports = 0, 0
    for _, trace in records:
        if trace is rejection:
            continue
        _check(trace.get("phase") == "completed"
               and trace.get("response", {}).get("error") is None,
               "Another RPC in the original import is uncertain.")
        _bound_reply(trace, trace["response"])
        call = trace["call"]
        method = call.get("method")
        _check(method not in SDK_MUTATIONS - {"SaveProject"},
               "Another mutation exists in the original import.")
        if call.get("kind") == "root":
            roots.append(trace["response"])
        elif method == "SaveProject":
            _check(trace["response"]["result"] is True, "Save was not acknowledged.")
            saves += 1
        elif method == "ExportProject":
            args = call["arguments"].get("a", [])
            _check(len(args) == 3 and Path(args[1]) == backup and args[2] is False
                   and trace["response"]["result"] is True,
                   "Backup was not acknowledged.")
            exports += 1
    _check(len(roots) == 1 and saves > 0 and exports == 1,
           "Original import context/backup is ambiguous.")
    manager = RemoteSDK(_Snapshot(roots[0])).root().GetProjectManager()
    project = manager.GetCurrentProject()
    project_id = project.GetUniqueId()
    _check(isinstance(project_id, str) and 1 <= len(project_id) <= 128,
           "Original project UUID is unavailable.")
    # This token has pre-call meaning in the fixed adapter only. Do not accept
    # replies from a modified runtime implementation or an arbitrary SDK error.
    sdk_source = Path(bridge.__file__).with_name("ResolveLuaSDK.lua")
    native_source = root / "marker-bridge.lua"
    _check(_safe(native_source).stat().st_size <= 4 * 1024 * 1024,
           "Native adapter source exceeds its bound.")
    _check(sdk_source.read_text(encoding="utf-8") in
           _safe(native_source).read_text(encoding="utf-8"),
           "Native import rejection semantics changed.")
    evidence = [original_path, response_path, backup, native_source, sdk_source,
                *outputs, *[p for p, _ in records]]
    return original, rejection, project_id, evidence


def _archive_slots(root: Path, owner: dict[str, Any], rejection: dict[str, Any],
                   archive: Path) -> None:
    for name, base in (("operation", root), ("rpc", root / "sdk-rpc")):
        inbox = _safe(base / "inbox")
        if not inbox.exists():
            continue
        slot = MarkerSlot.occupied(base, owner["session"], 4096)
        expected = (slot.request.get("action") == "sdk_operation"
                    and slot.identity == UUID(owner["command_id"]).hex)
        _check(slot.request == rejection["packet"] if name == "rpc" else expected,
               "A foreign native slot is still pending.")
        target = archive / name / "inbox"
        _check(target.resolve().is_relative_to(root.resolve()),
               "Import packet archive escapes its runtime.")
        target.parent.mkdir()
        inbox.rename(target)
        archived = MarkerSlot.occupied(target.parent, owner["session"], 4096)
        _check(archived.packet == slot.packet and archived.owner == slot.owner,
               "Archived import packet changed.")


def prepare_import_retry(
    profile: Profile, command: dict[str, Any],
) -> ImportRetry | None:
    """Caller keeps operation.lock through dispatch; no native call is made here.

    A new command UUID is an attempt, never a new logical key. The old response,
    owner, ledger, trace, preset acknowledgements and packet bytes are retained.
    A crash after reservation fails closed; it never retries an uncertain attempt.
    """
    if command["action"] != "import_media":
        return None
    key = hashlib.sha256(command["idempotency_key"].encode()).hexdigest()
    owner_path = profile.state_directory / "sdk-write-owners" / (key + ".json")
    if not _safe(owner_path).exists():
        return None
    owner = _read(owner_path)
    if owner.get("transport") != "lua_marker_preset":
        return None
    if owner.get("phase") == "completed":
        response = owner.get("response", {})
        _check(isinstance(response, dict), "Invalid terminal import response.")
        if response.get("status") == "success":
            return None
        error = response.get("error", {})
        _check(isinstance(error, dict), "Invalid terminal import error.")
        if error.get("code") != "SDK_OPERATION_EXPIRED":
            return None
    try:
        active = read_active(profile)
        _check(active is not None, "Original import generation is unavailable.")
        assert active is not None
        ledger_path = profile.runtime_base / "state/sdk-operations" / (key + ".json")
        ledger = _read(ledger_path)
        original, rejection, project_id, evidence = _proof(
            profile, command, owner, ledger, active)
        _check(process_alive(active["process"]), "Original Resolve process changed.")
        _check(not any((profile.runtime_base / "processing").glob("*.json")),
               "Another canonical command is still processing.")
        for path in owner_path.parent.glob("*.json"):
            if path != owner_path:
                _check(_read(path).get("phase") == "completed",
                       "Another SDK write requires recovery.")
        root = Path(owner["runtime"])
        archive = _safe(root / ("rejected-import-" + UUID(owner["command_id"]).hex))
        journal_path = _safe(profile.state_directory / "import-retries" / key /
                             (owner["command_id"] + ".json"))
        _check(not archive.exists() and not journal_path.exists(),
               "An earlier import reservation requires recovery.")
        # Preflight every occupied slot before archiving evidence or ownership.
        for base in (root, root / "sdk-rpc"):
            if _safe(base / "inbox").exists():
                slot = MarkerSlot.occupied(base, owner["session"], 4096)
                _check((slot.request == rejection["packet"]) if base != root else (
                    slot.request.get("action") == "sdk_operation"
                    and slot.identity == UUID(owner["command_id"]).hex),
                    "A foreign native slot is still pending.")
        bridge.validate_command(command)
        from mcp_server.managed_marker import claim_write_key

        claim_write_key(profile, active, command["idempotency_key"], route="sdk")
        journal_path.parent.mkdir(parents=True, exist_ok=True)
        archive.mkdir()
        hashes = {str(p): _hash(p) for p in [owner_path, ledger_path, *evidence]}
        journal = {
            "phase": "proof_verified", "original_owner": owner,
            "original_sdk_ledger": ledger, "original_command": original,
            "evidence_hashes": hashes, "archive": str(archive),
            "project_id": project_id, "rejection": "SDK_OPERATION_EXPIRED",
            "native_rpc_id": rejection["id"], "new_command": command,
        }
        atomic_json(journal_path, journal)
        for index, path in enumerate([owner_path, *evidence]):
            destination = archive / f"{index:03}-{path.name}"
            shutil.copy2(path, destination)
            _check(_hash(destination) == hashes[str(path)], "Import evidence changed.")
        _archive_slots(root, owner, rejection, archive)
        _check(all(_hash(p) == hashes[str(p)] for p in [owner_path, ledger_path,
                                                        *evidence]),
               "Import proof changed before reservation.")
        bridge.validate_command(command)
        journal["phase"] = "retry_reserved"
        atomic_json(journal_path, journal)
        retry_info = {"journal": str(journal_path), "project_id": project_id,
                      "previous_command_id": owner["command_id"]}
        previous = {k: v for k, v in owner.items() if k != "response"}
        reservation = {**previous, "command_id": command["command_id"],
                       "phase": "retry_prepared", "import_retry": retry_info}
        # Archive the old ledger rather than deleting or reusing its attempt ID.
        # The new ledger is created by SDKCommandClient only after this fence.
        atomic_json(owner_path, reservation)
        ledger_path.rename(archive / "previous-sdk-ledger.json")
        return ImportRetry(active=active, project_id=project_id)
    except ImportRetryError:
        raise
    except (OSError, ValueError, KeyError, TypeError, RuntimeError) as error:
        raise ImportRetryError("Import retry proof is missing or invalid.") from error
