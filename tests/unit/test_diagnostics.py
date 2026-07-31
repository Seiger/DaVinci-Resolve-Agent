"""Safe local diagnostics bundle tests."""

from __future__ import annotations

import json
from pathlib import Path

from agent.contracts import validate_contract
from agent.diagnostics import DiagnosticsBundleBuilder
from transports.filesystem import atomic_write_json, read_json_object


def _environment() -> dict[str, str]:
    return {
        "APPDATA": r"C:\Users\private\AppData\Roaming",
        "LOCALAPPDATA": r"C:\Users\private\AppData\Local",
        "USERPROFILE": r"C:\Users\private",
    }


def _write_config(path: Path) -> None:
    path.write_text(
        """
[agent]
log_level = "INFO"
provider = "resolve"
command_timeout_seconds = 30
api_token = "do-not-share"

[runtime]
root = "C:/Users/private/AppData/Local/DaVinciResolveAgent/runtime"

[resolve]
scripts_category = "Edit"
poll_interval_ms = 500

[safety]
allow_destructive = false
create_backup = true

[media]
allowed_roots = ["C:/Users/private/Videos"]
""".strip(),
        encoding="utf-8",
    )


def test_bundle_redacts_config_paths_and_log_secrets(
    tmp_path: Path,
) -> None:
    runtime_root = tmp_path / "runtime"
    config_path = tmp_path / "config.toml"
    _write_config(config_path)
    log_path = runtime_root / "logs" / "agent.log"
    log_path.parent.mkdir(parents=True)
    log_path.write_text(
        "token=abc123\n"
        r'path=C:\Users\private\Videos\clip.wav' "\n",
        encoding="utf-8",
    )
    atomic_write_json(
        runtime_root / "state" / "bridge.json",
        {
            "bridge_version": "0.1.0",
            "protocol_version": "1.0",
            "status": "ready",
            "resolve_version": "21.0.3.7",
            "last_heartbeat": "2026-07-31T12:00:00Z",
            "capabilities": {"project.read": True},
            "project_name": "Private Project",
        },
    )

    output = DiagnosticsBundleBuilder(
        runtime_root,
        config_path,
        _environment(),
    ).create()
    bundle = read_json_object(output)

    validate_contract("diagnostics-bundle", bundle)
    serialized = json.dumps(bundle)
    assert "do-not-share" not in serialized
    assert "abc123" not in serialized
    assert "C:\\\\Users\\\\private" not in serialized
    assert bundle["config"]["agent"]["api_token"] == "[REDACTED]"
    assert bundle["bridge"]["capabilities"] == {"project.read": True}
    assert "project_name" not in bundle["bridge"]
    assert bundle["logs"][0]["lines"][0] == "token=[REDACTED]"


def test_bundle_collects_bounded_failed_metadata_without_arguments(
    tmp_path: Path,
) -> None:
    runtime_root = tmp_path / "runtime"
    config_path = tmp_path / "missing.toml"
    for index in range(22):
        atomic_write_json(
            runtime_root / "failed" / f"command-{index:02}.json",
            {
                "command_id": f"command-{index:02}",
                "provider": "resolve",
                "action": "import_media",
                "created_at": "2026-07-31T12:00:00Z",
                "idempotency_key": "private-key",
                "arguments": {"paths": ["C:/private/video.mp4"]},
                "safety": {
                    "allow_destructive": False,
                    "create_backup": True,
                },
            },
        )

    output = DiagnosticsBundleBuilder(
        runtime_root,
        config_path,
        _environment(),
    ).create()
    bundle = read_json_object(output)

    assert len(bundle["failed_commands"]) == 20
    serialized = json.dumps(bundle["failed_commands"])
    assert "arguments" not in serialized
    assert "idempotency_key" not in serialized
    assert "private-key" not in serialized
    assert "video.mp4" not in serialized


def test_bundle_succeeds_without_bridge_logs_or_failures(
    tmp_path: Path,
) -> None:
    output = DiagnosticsBundleBuilder(
        tmp_path / "runtime",
        tmp_path / "missing.toml",
        _environment(),
    ).create()
    bundle = read_json_object(output)

    assert bundle["config_source"] == "packaged_default"
    assert bundle["bridge"]["available"] is False
    assert bundle["logs"] == []
    assert bundle["failed_commands"] == []
    assert bundle["warnings"] == [
        "Cached Resolve bridge state is unavailable or invalid."
    ]


def test_bundle_treats_invalid_cached_heartbeat_as_unavailable(
    tmp_path: Path,
) -> None:
    runtime_root = tmp_path / "runtime"
    atomic_write_json(
        runtime_root / "state" / "bridge.json",
        {
            "bridge_version": "0.1.0",
            "protocol_version": "1.0",
            "status": "ready",
            "last_heartbeat": "not-a-timestamp",
            "capabilities": {"bridge.ping": True},
        },
    )

    output = DiagnosticsBundleBuilder(
        runtime_root,
        tmp_path / "missing.toml",
        _environment(),
    ).create()
    bundle = read_json_object(output)

    assert bundle["bridge"]["available"] is False
    assert bundle["bridge"]["capabilities"] == {}
