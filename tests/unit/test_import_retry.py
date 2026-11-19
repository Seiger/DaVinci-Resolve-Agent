"""Only exact native pre-call rejection permits a same-key import attempt."""
from __future__ import annotations

import asyncio
import copy
import hashlib
import json
import struct
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any
from uuid import UUID, uuid4

import pytest
from mcp import Client
from test_resolve_bridge_writes import FakeTimelineItem
from test_sdk_command_client import Channel, queued, setup_worker

from agent.client import (
    BridgeCommandError,
    BridgeProtocolError,
    FilesystemCommandClient,
)
from bridges.resolve import ResolveBridge as bridge
from mcp_server.automatic import AutomaticServer
from mcp_server.server import create_server
from providers.resolve import import_retry as module
from providers.resolve.lua_editing import atomic_json
from providers.resolve.marker_transport import MarkerSlot
from providers.resolve.preset_envelope import HEADER, payload_name
from providers.resolve.sdk_command_client import SDKCommandClient
from providers.resolve.sdk_worker import SDKWorker


def preset(path: Path, session: str, identity: str, reply: dict[str, Any]) -> None:
    name = payload_name(session, identity, "O", reply).encode("utf-16be")
    data = struct.pack(">II", 2, len(name)) + name + b"opaque fixture"
    path.write_bytes(HEADER + b"\n" + data.hex().encode())


def fixture(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, *, terminal: bool = False,
    slots: bool = False,
) -> tuple[SDKWorker, Any, dict[str, Any]]:
    worker, native, active = setup_worker(tmp_path, monkeypatch)
    active["process"] = {"pid": 123, "creation_time": "original-token"}
    monkeypatch.setattr(module, "read_active", lambda profile: active)
    monkeypatch.setattr(module, "process_alive", lambda process: True)
    media = tmp_path / "picture.mp4"
    media.touch()
    atomic_json(worker.root / "state/media-policy.json", {
        "policy_version": "1.0", "allowed_roots": [str(tmp_path)]})
    path = queued(worker, "import_media", {"paths": [str(media)]}, "original-key")
    command = json.loads(path.read_text())
    old = datetime.now(timezone.utc) - timedelta(minutes=10)
    command.update(created_at=old.isoformat(),
                   expires_at=(old + timedelta(minutes=2)).isoformat())
    atomic_json(path, command)
    identity = command["command_id"]
    fingerprint = bridge._request_fingerprint(command)
    key = hashlib.sha256(b"original-key").hexdigest()
    root = Path(active["runtime"])
    marker_source = root / "marker-bridge.lua"
    marker_source.write_text(marker_source.read_text(encoding="utf8") + "\n" +
        Path(bridge.__file__).with_name("ResolveLuaSDK.lua").read_text(encoding="utf8"),
        encoding="utf8")
    owner_path = worker.profile.state_directory / "sdk-write-owners" / (key + ".json")
    owner_path.parent.mkdir(exist_ok=True)
    phase = "completed" if terminal else "uncertain"
    owner = {"runtime": str(root), "generation": active["generation"],
             "session": active["session"], "fingerprint": fingerprint,
             "command_id": identity, "phase": phase, "transport": "lua_marker_preset"}
    ledger_path = worker.root / "state/sdk-operations" / (key + ".json")
    ledger_path.parent.mkdir(exist_ok=True)
    ledger = {k: owner[k] for k in ("session", "fingerprint", "command_id", "phase")}
    backup = worker.root / "backups/original.drp"
    backup.write_bytes(b"original acknowledged native backup")
    failed = {"protocol_version": "1.0", "command_id": identity, "status": "error",
              "started_at": old.isoformat(), "finished_at": old.isoformat(),
              "result": None, "warnings": [], "error": {
                  "code": "SDK_OPERATION_EXPIRED" if terminal else
                          "RESOLVE_OPERATION_FAILED",
                  "message": "Original import timed out", "retryable": False,
                  "details": {"backup_path": str(backup)}}}
    response_path = worker.root / "responses" / path.name
    atomic_json(response_path, failed)
    if terminal:
        owner["response"] = failed
        ledger["response"] = failed
    atomic_json(owner_path, owner)
    atomic_json(ledger_path, ledger)
    path.rename(worker.root / "failed" / path.name)
    operation = {"id": UUID(identity).hex, "action": "import_media",
                 "fingerprint": fingerprint, "create_backup": True,
                 "allow_destructive": False,
                 "expires": int(datetime.fromisoformat(command["expires_at"])
                                .timestamp())}
    traces = root / "sdk-trace"
    traces.mkdir()

    def trace(call: dict[str, Any], result: Any, objects: dict[str, Any],
              error: str | None = None) -> dict[str, Any]:
        rpc_id, message_id = uuid4().hex, uuid4().hex
        raw = json.dumps({"operation": operation, "call": call},
                         ensure_ascii=True, separators=(",", ":")).encode()
        packet = {"session": active["session"], "id": message_id, "action": "ping",
                  "expires": operation["expires"], "arguments": {"sdk": {
                      "id": rpc_id, "seq": 1, "count": 1,
                      "data": raw.decode("ascii")}}}
        reply = {"result": result, "objects": objects, "error": error,
                 "request_hex": raw.hex()}
        record = {"session": active["session"], "id": rpc_id,
                  "operation": operation, "call": call, "message_id": message_id,
                  "packet": packet, "part": 1,
                  "request_sha256": hashlib.sha256(raw).hexdigest(),
                  "phase": "uncertain" if error else "completed"}
        if not error:
            record["response"] = reply
        atomic_json(traces / (rpc_id + ".json"), record)
        if error:
            for suffix in (".preset", ".ready.preset"):
                preset(root / ("sdk-" + rpc_id + suffix), active["session"],
                       rpc_id, reply)
        return record

    def obj(method: str, result: Any) -> dict[str, Any]:
        return {"methods": [method], "cache": [
            {"method": method, "arguments": {"a": []}, "result": result}]}

    root_trace = trace({"kind": "root"}, {"r": "resolve"}, {
        "resolve": obj("GetProjectManager", {"r": "manager"}),
        "manager": obj("GetCurrentProject", {"r": "project"}),
        "project": obj("GetUniqueId", native.project.GetUniqueId()),
    })
    trace({"kind": "call", "object": "manager", "method": "SaveProject",
           "arguments": {"a": []}}, True, {})
    trace({"kind": "call", "object": "manager", "method": "ExportProject",
           "arguments": {"a": [native.project.GetName(), str(backup), False]}},
          True, {})
    rejected = trace({"kind": "call", "object": "pool", "method": "ImportMedia",
                      "arguments": {"a": [{"a": [str(media)]}]}},
                     None, {}, "SDK_OPERATION_EXPIRED")
    if slots:
        (root / "sdk-rpc").mkdir()
        MarkerSlot(root / "sdk-rpc", rejected["packet"], 4096).publish(
            time.monotonic() + 30)
        MarkerSlot(root, {"session": active["session"], "id": UUID(identity).hex,
                         "action": "sdk_operation", "expires": operation["expires"]},
                   4096).publish(time.monotonic() + 30)
    monkeypatch.setattr(worker.connection, "ensure", lambda **kw: pytest.fail(
        "An import retry must not bootstrap or open a project"))
    monkeypatch.setattr(worker, "_select_route", lambda active: pytest.fail(
        "An import retry must not switch native transport"))
    context = {"root": root, "owner": owner_path, "ledger": ledger_path,
               "old_command": command, "arguments": command["arguments"],
               "rejection": rejected, "root_trace": root_trace, "active": active,
               "response": response_path, "backup": backup}
    return worker, native, context


def snapshots(context: dict[str, Any]) -> dict[str, bytes]:
    root = context["root"]
    paths = [context["owner"], context["ledger"], context["response"],
             context["backup"], *root.rglob("*.json"), *root.glob("*.preset")]
    return {str(p): p.read_bytes() for p in paths if p.is_file()
            and not (p.is_relative_to(root) and "lease" in p.relative_to(root).parts)}


@pytest.mark.parametrize("terminal,slots", [(False, True), (True, False)])
def test_same_key_retries_once_and_preserves_history_and_timelines(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, terminal: bool, slots: bool,
) -> None:
    worker, native, context = fixture(tmp_path, monkeypatch,
                                      terminal=terminal, slots=slots)
    before = snapshots(context)
    timeline = native.project.media_pool.CreateEmptyTimeline("Existing timeline")
    native.project.current_timeline = timeline
    timeline.items = [
        FakeTimelineItem("existing-video", "Video", timeline_start=100,
                         timeline_end=200, source_start=0, source_end=100),
        FakeTimelineItem("existing-audio", "Audio", timeline_start=100,
                         timeline_end=200, source_start=0, source_end=100,
                         track_type="audio"),
    ]
    timelines = bridge._list_timeline_items(native, timeline.GetUniqueId())
    retry = queued(worker, "import_media", context["arguments"], "original-key")
    worker.process(retry)
    result = json.loads((worker.root / "responses" / retry.name).read_text())
    assert result["status"] == "success", result
    assert len(native.project.media_pool.root.clips) == 1
    assert bridge._list_timeline_items(native, timeline.GetUniqueId()) == timelines
    assert native.project_manager.export_count == 1
    owner = json.loads(context["owner"].read_text())
    assert owner["command_id"] == retry.stem and owner["phase"] == "completed"
    assert json.loads(context["ledger"].read_text())["command_id"] == retry.stem
    journal = json.loads(Path(owner["import_retry"]["journal"]).read_text())
    assert journal["original_command"]["idempotency_key"] == "original-key"
    archive = Path(journal["archive"])
    assert (archive / "previous-sdk-ledger.json").read_bytes() == before[
        str(context["ledger"])]
    if slots:
        assert MarkerSlot.occupied(archive / "rpc", context["active"]["session"],
                                   4096).request == context["rejection"]["packet"]
        assert MarkerSlot.occupied(archive / "operation",
            context["active"]["session"], 4096).identity == UUID(
                context["old_command"]["command_id"]).hex
    assert journal["original_owner"]["command_id"] == context["old_command"][
        "command_id"]
    for path, data in before.items():
        if (Path(path) not in (context["owner"], context["ledger"])
                and Path(path).exists()):
            assert Path(path).read_bytes() == data
    for _ in range(2):
        replay = queued(worker, "import_media", context["arguments"], "original-key")
        worker.process(replay)
        response = worker.root / "responses" / replay.name
        replay_result = json.loads(response.read_text())
        assert replay_result["result"] == result["result"]
    assert len(native.project.media_pool.root.clips) == 1
    assert native.project_manager.export_count == 1


@pytest.mark.parametrize("change", [
    "missing_ready", "changed_reply", "other_error", "trace_hash", "changed_paths",
    "changed_safety", "changed_key", "session", "generation", "process", "transport",
    "ledger", "backup", "native_source", "root_identity", "extra_import", "receipt",
    "foreign_packet", "reservation", "conflicting_response", "invalid_command_id",
])
def test_unverified_or_changed_evidence_never_imports(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, change: str,
) -> None:
    worker, native, c = fixture(tmp_path, monkeypatch, slots=change == "foreign_packet")
    root, rejected = c["root"], c["rejection"]
    ready = root / ("sdk-" + rejected["id"] + ".ready.preset")
    trace_path = root / "sdk-trace" / (rejected["id"] + ".json")
    arguments, key = c["arguments"], "original-key"
    if change == "missing_ready":
        ready.unlink()
    elif change in {"changed_reply", "other_error"}:
        reply = {"error": "SDK_PROJECT_CHANGED" if change == "other_error" else
                 "SDK_OPERATION_EXPIRED", "objects": {}, "result": None,
                 "request_hex": rejected["packet"]["arguments"]["sdk"][
                     "data"].encode().hex()}
        if change == "changed_reply":
            reply["request_hex"] = "00"
        for suffix in (".preset", ".ready.preset"):
            preset(root / ("sdk-" + rejected["id"] + suffix),
                   c["active"]["session"], rejected["id"], reply)
    elif change == "trace_hash":
        rejected["request_sha256"] = "0" * 64
        atomic_json(trace_path, rejected)
    elif change == "changed_paths":
        arguments = {"paths": [str(tmp_path / "other.mp4")]}
    elif change == "changed_key":
        key = "other-key"
    elif change in {"session", "generation"}:
        c["active"][change] = "changed"
    elif change == "process":
        monkeypatch.setattr(module, "process_alive", lambda process: False)
    elif change == "transport":
        owner = json.loads(c["owner"].read_text())
        owner["transport"] = "python_sdk"
        atomic_json(c["owner"], owner)
    elif change == "ledger":
        ledger = json.loads(c["ledger"].read_text())
        ledger["fingerprint"] = "0" * 64
        atomic_json(c["ledger"], ledger)
    elif change == "conflicting_response":
        ledger = json.loads(c["ledger"].read_text())
        ledger["response"] = {"status": "success", "result": {"items": []}}
        atomic_json(c["ledger"], ledger)
    elif change == "invalid_command_id":
        owner = json.loads(c["owner"].read_text())
        owner["command_id"] = "../../outside"
        atomic_json(c["owner"], owner)
    elif change == "backup":
        c["backup"].unlink()
    elif change == "native_source":
        (root / "marker-bridge.lua").write_text("changed")
    elif change == "root_identity":
        t = c["root_trace"]
        t["response"]["objects"]["project"]["cache"] = []
        atomic_json(root / "sdk-trace" / (t["id"] + ".json"), t)
    elif change == "extra_import":
        other = copy.deepcopy(rejected)
        other["id"] = uuid4().hex
        atomic_json(root / "sdk-trace" / (other["id"] + ".json"), other)
    elif change == "receipt":
        receipt = bridge._receipt_path(worker.root / "state", "original-key")
        receipt.parent.mkdir()
        atomic_json(receipt, {})
    elif change == "foreign_packet":
        owner = root / "sdk-rpc/inbox/.owner.json"
        value = json.loads(owner.read_text())
        value["id"] = uuid4().hex
        atomic_json(owner, value)
    elif change == "reservation":
        (root / ("rejected-import-" + UUID(c["old_command"]["command_id"]).hex)).mkdir()
    retry = queued(worker, "import_media", arguments, key)
    if change == "changed_safety":
        value = json.loads(retry.read_text())
        value["safety"]["allow_destructive"] = True
        atomic_json(retry, value)
    before = snapshots(c)
    with pytest.raises((RuntimeError, ValueError)):
        worker.process(retry)
    for path, data in before.items():
        assert Path(path).read_bytes() == data
    assert native.project_manager.export_count == 0
    assert native.project.media_pool.root.clips == []


def test_changed_native_project_cannot_import_after_reservation(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    worker, native, c = fixture(tmp_path, monkeypatch)
    monkeypatch.setattr(native.project, "GetUniqueId", lambda: "changed-project")
    monkeypatch.setattr(native.project_manager, "SaveProject", lambda: pytest.fail(
        "A changed project must not be saved by the import retry"))
    retry = queued(worker, "import_media", c["arguments"], "original-key")
    with pytest.raises(BridgeProtocolError, match="project changed"):
        worker.process(retry)
    assert native.project_manager.export_count == 0
    assert native.project.media_pool.root.clips == []
    assert json.loads(c["owner"].read_text())["phase"] == "uncertain"


@pytest.mark.parametrize("terminal", [False, True])
def test_timeout_of_new_attempt_is_not_permission_to_import_again(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, terminal: bool,
) -> None:
    worker, native, c = fixture(tmp_path, monkeypatch, terminal=terminal)
    import providers.resolve.sdk_worker as worker_module

    class LostReply(Channel):
        def exchange(self, payload: dict[str, Any]) -> dict[str, Any]:
            reply = super().exchange(payload)
            if payload.get("method") == "ImportMedia":
                raise TimeoutError("Outcome unknown after native import")
            return reply

    monkeypatch.setattr(worker_module, "SDKCommandClient",
        lambda root, session, **kw: SDKCommandClient(root, session, **kw,
            channel_factory=lambda operation, timeout: LostReply(native)))
    retry = queued(worker, "import_media", c["arguments"], "original-key")
    with pytest.raises(BridgeProtocolError, match="failed after dispatch"):
        worker.process(retry)
    assert len(native.project.media_pool.root.clips) == 1
    assert "response" not in json.loads(c["owner"].read_text())
    again = queued(worker, "import_media", c["arguments"], "original-key")
    with pytest.raises(module.ImportRetryError):
        worker.process(again)
    assert len(native.project.media_pool.root.clips) == 1


def test_mcp_reports_import_failure_code_and_stable_key() -> None:
    class Service:
        def resolve_import_media(self, *args: Any, **kw: Any) -> dict[str, Any]:
            assert kw["idempotency_key"] == "original-key"
            raise BridgeCommandError(code="ORIGINAL_SDK_OPERATION_REQUIRES_RECOVERY",
                                     message="No proven pre-import rejection",
                                     retryable=False)

    async def exercise() -> None:
        async with Client(create_server(Service())) as client:  # type: ignore[arg-type]
            result = await client.call_tool("resolve_import_media", {
                "paths": ["picture.mp4"], "idempotency_key": "original-key"})
            assert result.is_error
            assert result.structured_content is not None
            assert result.structured_content["code"] == (
                "ORIGINAL_SDK_OPERATION_REQUIRES_RECOVERY")
    asyncio.run(exercise())


def test_concurrent_same_key_requests_share_one_import(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    worker, native, c = fixture(tmp_path, monkeypatch)
    paths = [queued(worker, "import_media", c["arguments"], "original-key")
             for _ in range(2)]
    with ThreadPoolExecutor(max_workers=2) as pool:
        list(pool.map(worker.process, paths))
    assert len(native.project.media_pool.root.clips) == 1
    assert native.project_manager.export_count == 1
    results = [json.loads((worker.root / "responses" / p.name).read_text())
               for p in paths]
    assert results[0]["result"] == results[1]["result"]


def test_interrupted_reservation_never_dispatches_a_second_attempt(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    worker, native, c = fixture(tmp_path, monkeypatch)
    original_atomic = atomic_json

    def interrupted(path: Path, value: dict[str, Any]) -> None:
        original_atomic(path, value)
        if path == c["owner"] and value.get("phase") == "retry_prepared":
            raise OSError("Simulated interruption after durable reservation")

    monkeypatch.setattr(module, "atomic_json", interrupted)
    for _ in range(2):
        path = queued(worker, "import_media", c["arguments"], "original-key")
        with pytest.raises(module.ImportRetryError):
            worker.process(path)
    assert native.project_manager.export_count == 0
    assert native.project.media_pool.root.clips == []
    assert json.loads(c["owner"].read_text())["phase"] == "retry_prepared"


@pytest.mark.parametrize("missing_ack", [False, True])
def test_automatic_mcp_routes_original_key_before_native_readiness(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, missing_ack: bool,
) -> None:
    worker, native, c = fixture(tmp_path, monkeypatch)
    if missing_ack:
        (c["root"] / ("sdk-" + c["rejection"]["id"] + ".ready.preset")).unlink()
    monkeypatch.setattr("agent.resolve_watch.start_hidden", lambda profile: pytest.fail(
        "Tests must not start a native watcher"))
    server = AutomaticServer(worker.profile, start_worker=False)

    async def no_readiness(**kw: Any) -> None:
        pytest.fail("A known import key must reach recovery before bootstrap")

    monkeypatch.setattr(server, "_ready", no_readiness)
    client = FilesystemCommandClient(worker.root)

    class Service:
        def resolve_import_media(self, paths: list[str], *, timeout_seconds: float,
                                 idempotency_key: str) -> Any:
            return client.request(provider="resolve", action="import_media",
                arguments={"paths": paths}, timeout_seconds=timeout_seconds,
                idempotency_key=idempotency_key, create_backup=True)

    server.primary = create_server(Service())  # type: ignore[arg-type]

    def process_once() -> None:
        deadline = time.monotonic() + 30
        while time.monotonic() < deadline:
            paths = list(worker.directories["commands"].glob("*.json"))
            if paths:
                try:
                    worker.process(paths[0])
                except module.ImportRetryError as error:
                    worker._error(paths[0], error.code, str(error))
                return
            time.sleep(0.01)
        raise AssertionError("No import reached the canonical queue")

    async def exercise() -> None:
        async with Client(server) as mcp:
            with ThreadPoolExecutor(max_workers=1) as pool:
                for _ in range(1 if missing_ack else 2):
                    future = pool.submit(process_once)
                    result = await mcp.call_tool("resolve_import_media", {
                        **c["arguments"], "idempotency_key": "original-key",
                        "timeout_seconds": 60})
                    future.result(timeout=30)
                    assert result.is_error is missing_ack
                    if missing_ack:
                        assert result.structured_content is not None
                        assert result.structured_content["code"] == (
                            "ORIGINAL_SDK_OPERATION_REQUIRES_RECOVERY")
    asyncio.run(exercise())
    assert len(native.project.media_pool.root.clips) == (0 if missing_ack else 1)
