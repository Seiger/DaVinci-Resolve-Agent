"""Boundaries of the opt-in Lua snapshot transport, not live Resolve tests."""

from __future__ import annotations

import json
import re
import threading
import time
import zipfile
from pathlib import Path
from xml.etree import ElementTree as ET

import pytest

from agent.client import BridgeProtocolError, CommandTimeoutError
from providers.resolve.lua_transport import (
    LuaSnapshotClient,
    lua_string,
    prepare,
    read_project_snapshot,
)


def snapshot(path: Path, xml: bytes | None = None) -> None:
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr(
            "project.xml",
            xml
            or (
                b'<SM_Project DbId="test-id"><ProjectName>A &amp; B</ProjectName>'
                b"<Config><1>non-standard Resolve key</1></Config></SM_Project>"
            ),
        )


def test_snapshot_reads_identity_without_parsing_resolve_configuration(
    tmp_path: Path,
) -> None:
    path = tmp_path / "project.drp"
    snapshot(path)
    assert read_project_snapshot(path) == {"id": "test-id", "name": "A & B"}


@pytest.mark.parametrize(
    "xml",
    [
        b'<!DOCTYPE x [<!ENTITY x "bad">]><SM_Project/>',
        b"<SM_Project><ProjectName>missing id</ProjectName></SM_Project>",
        b'<NotProject DbId="id"><ProjectName>x</ProjectName></NotProject>',
        b'<SM_Project DbId="id"/>',
    ],
)
def test_snapshot_rejects_unrecognized_or_entity_payload(
    tmp_path: Path, xml: bytes
) -> None:
    path = tmp_path / "bad.drp"
    snapshot(path, xml)
    with pytest.raises((BridgeProtocolError, ET.ParseError)):
        read_project_snapshot(path)


def test_lua_literal_cannot_inject_code() -> None:
    value = '"; os.execute("bad"); --\nшлях\\'
    encoded = lua_string(value)
    assert re.fullmatch(r'"(?:\\[0-9]{3})*"', encoded)
    assert bytes(int(v) for v in re.findall(r"\\([0-9]{3})", encoded)).decode() == value


def test_prepare_never_overwrites_existing_session(tmp_path: Path) -> None:
    root = tmp_path / "session"
    script = prepare(root)
    assert "__RUNTIME_ROOT__" not in script.read_text(encoding="utf-8")
    with pytest.raises(FileExistsError):
        prepare(root)


@pytest.mark.parametrize(
    "action,timeout", [("eval", 1), ("ping", float("nan")), ("ping", 0)]
)
def test_rejects_bad_requests_before_publishing(
    tmp_path: Path, action: str, timeout: float
) -> None:
    root = tmp_path / "session"
    prepare(root)
    with pytest.raises(ValueError):
        LuaSnapshotClient(root).request(action, timeout)
    assert (root / "request.lua").read_text() == "return nil\n"
    assert not (root / "client.lock").exists()


def test_timeout_clears_mailbox_and_lock(tmp_path: Path) -> None:
    root = tmp_path / "session"
    prepare(root)
    with pytest.raises(CommandTimeoutError):
        LuaSnapshotClient(root).request("ping", 0.01)
    assert (root / "request.lua").read_text() == "return nil\n"
    assert not (root / "client.lock").exists()


def test_busy_session_preserves_owner_request(tmp_path: Path) -> None:
    root = tmp_path / "session"
    prepare(root)
    (root / "client.lock").write_text("owner")
    (root / "request.lua").write_text("owner request")
    with pytest.raises(FileExistsError):
        LuaSnapshotClient(root).request("ping")
    assert (root / "request.lua").read_text() == "owner request"


def test_fresh_response_correlates_and_waits_for_complete_zip(tmp_path: Path) -> None:
    root = tmp_path / "session"
    prepare(root)
    snapshot(root / ("0" * 32 + ".drp"))  # stale response must not satisfy request

    def responder() -> None:
        for _ in range(100):
            payload = (root / "request.lua").read_text()
            found = re.search(r',id="((?:\\[0-9]{3})+)"', payload)
            if found:
                identity = bytes(
                    int(v) for v in re.findall(r"\\([0-9]{3})", found[1])
                ).decode()
                response = root / f"{identity}.drp"
                response.write_bytes(b"PK")  # incomplete export appears first
                time.sleep(0.15)
                snapshot(response)
                return
            time.sleep(0.01)

    worker = threading.Thread(target=responder)
    worker.start()
    try:
        result = LuaSnapshotClient(root).request("get_current_project", 3)
        assert result["project"] == {"id": "test-id", "name": "A & B"}
    finally:
        worker.join(timeout=4)
    assert json.loads((root / "session.json").read_text())["session"]
