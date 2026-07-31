"""Windows CI policy tests."""

from pathlib import Path


def _workflow_text() -> str:
    return (
        Path(__file__).parents[2]
        / ".github"
        / "workflows"
        / "windows-ci.yml"
    ).read_text(encoding="utf-8")


def test_windows_ci_covers_supported_python_versions() -> None:
    workflow = _workflow_text()

    assert "runs-on: windows-latest" in workflow
    assert '- "3.10"' in workflow
    assert '- "3.11"' in workflow
    assert '- "3.12"' in workflow
    assert "python -m pytest -q" in workflow
    assert "davinci-agent --version" in workflow


def test_windows_ci_has_read_only_security_boundary() -> None:
    workflow = _workflow_text()

    assert "permissions:\n  contents: read" in workflow
    assert "persist-credentials: false" in workflow
    assert "actions/checkout@v7" in workflow
    assert "actions/setup-python@v6" in workflow
    for forbidden in (
        "pull_request_target:",
        "workflow_run:",
        "contents: write",
        "secrets.",
        "git push",
        "deploy",
    ):
        assert forbidden not in workflow.lower()


def test_windows_ci_runs_static_and_powershell_checks() -> None:
    workflow = _workflow_text()

    assert "python -m ruff check ." in workflow
    assert "python -m mypy ." in workflow
    assert r".\scripts\check-powershell-syntax.ps1" in workflow
