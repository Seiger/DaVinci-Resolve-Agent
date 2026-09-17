"""Project creation preserves current work and rejects unsafe replays."""

from pathlib import Path
from typing import Any

import pytest

from agent.application import AgentApplication
from agent.contracts import validate_contract
from bridges.resolve.ResolveBridge import (
    BridgeOperationError,
    _execute_write_command,
    _validate_write_arguments,
    ensure_runtime_directories,
)


class Project:
    """Minimal documented project API used by the creation action."""

    def __init__(self, name: str) -> None:
        self.name = name
        self.rendering = False

    def GetName(self) -> str:
        return self.name

    def GetUniqueId(self) -> str:
        return "id-" + self.name

    def IsRenderingInProgress(self) -> bool:
        return self.rendering


class Manager:
    """Record API order and simulate creation, save and export failures."""

    def __init__(self, current: Project | None) -> None:
        self.current = current
        self.names = [] if current is None else [current.name]
        self.calls: list[str] = []
        self.save_ok = True
        self.export_ok = True
        self.create_ok = True
        self.select_created = True

    def GetCurrentProject(self) -> Project | None:
        return self.current

    def GetProjectListInCurrentFolder(self) -> list[str]:
        return self.names

    def SaveProject(self) -> bool:
        self.calls.append("save")
        return self.save_ok

    def ExportProject(self, name: str, path: str, stills: bool) -> bool:
        self.calls.append("export")
        assert self.current is not None and name == self.current.name
        if self.export_ok:
            Path(path).write_text("backup", encoding="utf-8")
        return self.export_ok

    def CreateProject(self, name: str) -> Project | None:
        self.calls.append("create")
        if not self.create_ok:
            return None
        assert name not in self.names
        self.names.append(name)
        project = Project(name)
        if self.select_created:
            self.current = project
        return project


class Resolve:
    """Expose just the project manager without a MediaPool dependency."""

    def __init__(self, manager: Manager) -> None:
        self.manager = manager

    def GetProjectManager(self) -> Manager:
        return self.manager


def command(name: str = "sMailer") -> dict[str, Any]:
    """Return the canonical creation envelope with explicit confirmation."""
    return {
        "protocol_version": "1.0",
        "provider": "resolve",
        "command_id": "new-project",
        "idempotency_key": "new-project",
        "created_at": "2026-09-17T10:00:00Z",
        "expires_at": "2026-09-17T10:05:00Z",
        "action": "create_project",
        "arguments": {"name": name, "confirm_create": True},
        "safety": {"create_backup": True, "allow_destructive": False},
    }


@pytest.mark.parametrize("opened", [True, False])
def test_create_project_backup_order_and_replay(tmp_path: Path, opened: bool) -> None:
    manager = Manager(Project("Existing") if opened else None)
    directories = ensure_runtime_directories(tmp_path)
    envelope = command()
    validate_contract("command", envelope)
    result, _ = _execute_write_command(Resolve(manager), envelope, directories)
    assert result["project"] == {"project_id": "id-sMailer", "name": "sMailer"}
    assert result["previous_project_id"] == ("id-Existing" if opened else None)
    assert bool(result["backup_path"]) is opened
    assert manager.calls == (["save", "export"] if opened else []) + ["create", "save"]
    calls = list(manager.calls)
    manager.current = Project("Unrelated")
    replay, warnings = _execute_write_command(Resolve(manager), envelope, directories)
    assert replay == result and warnings
    assert manager.calls == calls
    assert manager.current.name == "Unrelated"


@pytest.mark.parametrize("name", ["", " ", " padded", "padded ", "a\nb", "a" * 129])
def test_invalid_project_names_are_rejected(name: str) -> None:
    with pytest.raises(ValueError):
        _validate_write_arguments("create_project", command(name)["arguments"])
    with pytest.raises(ValueError):
        AgentApplication().resolve_create_project(name, confirm_create=True)


def test_missing_confirmation_rejected_before_dispatch() -> None:
    with pytest.raises(ValueError):
        AgentApplication().resolve_create_project("sMailer", confirm_create=False)
    args = command()["arguments"]
    args["confirm_create"] = False
    with pytest.raises(ValueError):
        _validate_write_arguments("create_project", args)


@pytest.mark.parametrize("failure", ["collision", "render", "save", "export"])
def test_preflight_failure_never_creates_project(tmp_path: Path, failure: str) -> None:
    previous = Project("Existing")
    manager = Manager(previous)
    if failure == "collision":
        manager.names.append("SMAILER")
    elif failure == "render":
        previous.rendering = True
    elif failure == "save":
        manager.save_ok = False
    else:
        manager.export_ok = False
    with pytest.raises(BridgeOperationError):
        _execute_write_command(
            Resolve(manager), command(), ensure_runtime_directories(tmp_path)
        )
    assert "create" not in manager.calls
    assert manager.current is previous


@pytest.mark.parametrize("failure", ["create", "readback", "save"])
def test_partial_failure_is_not_reported_as_success(
    tmp_path: Path, failure: str
) -> None:
    manager = Manager(None)
    manager.create_ok = failure != "create"
    manager.select_created = failure != "readback"
    manager.save_ok = failure != "save"
    directories = ensure_runtime_directories(tmp_path)
    with pytest.raises(BridgeOperationError):
        _execute_write_command(Resolve(manager), command(), directories)
    if failure != "create":
        with pytest.raises(BridgeOperationError, match="already exists"):
            _execute_write_command(Resolve(manager), command(), directories)
        assert manager.calls.count("create") == 1


def test_idempotency_key_cannot_be_reused_for_another_name(tmp_path: Path) -> None:
    manager = Manager(None)
    directories = ensure_runtime_directories(tmp_path)
    _execute_write_command(Resolve(manager), command(), directories)
    with pytest.raises(BridgeOperationError):
        _execute_write_command(Resolve(manager), command("Another"), directories)
    assert manager.calls.count("create") == 1
