"""CLI tests."""

import json

import pytest

import agent.cli
from agent.cli import main


def test_version_command(capsys: pytest.CaptureFixture[str]) -> None:
    with pytest.raises(SystemExit) as exit_info:
        main(["--version"])

    assert exit_info.value.code == 0
    assert capsys.readouterr().out.strip() == "davinci-agent 0.1.0"


class StubResolveClient:
    def workspace_snapshot(self, timeout_seconds: float = 30) -> dict[str, object]:
        assert timeout_seconds == 12
        return {
            "project": {"name": "Test Project"},
            "timelines": [{"timeline_id": "timeline-1", "name": "Main"}],
            "current_timeline": {
                "timeline_id": "timeline-1",
                "name": "Main",
            },
            "timeline_items": {"items": [{"timeline_item_id": "item-1"}]},
            "media_pool": {"items": [{"asset_id": "asset-1"}]},
            "render": {"formats": [{"format": "mp4"}]},
        }

    def render_environment(self, timeout_seconds: float = 30) -> dict[str, object]:
        assert timeout_seconds == 12
        return {
            "formats": [],
            "current": {"format": "mp4", "codec": "H264"},
            "presets": [],
            "jobs": [],
        }


def test_render_options_command_prints_json(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setattr(
        agent.cli,
        "_create_resolve_client",
        lambda: StubResolveClient(),
    )

    assert main(
        [
            "resolve",
            "render-options",
            "--timeout-seconds",
            "12",
            "--json",
        ]
    ) == 0
    output = json.loads(capsys.readouterr().out)
    assert output["current"] == {"format": "mp4", "codec": "H264"}


def test_workspace_snapshot_command_prints_summary(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setattr(
        agent.cli,
        "_create_resolve_client",
        lambda: StubResolveClient(),
    )

    assert main(
        ["resolve", "snapshot", "--timeout-seconds", "12"]
    ) == 0
    assert capsys.readouterr().out.splitlines() == [
        "Project: Test Project",
        "Timelines: 1",
        "Current timeline: Main",
        "Timeline items: 1",
        "Media Pool items: 1",
        "Render formats: 1",
    ]
