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


def test_windows_ci_runs_isolated_installer_lifecycle() -> None:
    workflow = _workflow_text()

    assert "installer-lifecycle:" in workflow
    assert "name: Installer lifecycle" in workflow
    assert "timeout-minutes: 15" in workflow
    assert r".\scripts\test-installer-lifecycle.ps1" in workflow


def test_installer_lifecycle_script_has_bounded_sandbox() -> None:
    script = (
        Path(__file__).parents[2]
        / "scripts"
        / "test-installer-lifecycle.ps1"
    ).read_text(encoding="utf-8")

    assert "[System.IO.Path]::GetTempPath()" in script
    assert "DaVinciResolveAgent-Installer-" in script
    assert "outside-installer.txt" in script
    assert "$env:APPDATA = Join-Path $sandboxRoot" in script
    assert "$env:LOCALAPPDATA = Join-Path $sandboxRoot" in script
    assert "$env:PIP_CACHE_DIR = Join-Path $sandboxRoot" in script
    assert "$env:USERPROFILE = Join-Path $sandboxRoot" in script
    assert "-PreserveConfig $false" in script
    assert "-PreserveLogs $false" in script
    assert "Remove-Item -LiteralPath $sandboxRoot -Recurse -Force" in script
