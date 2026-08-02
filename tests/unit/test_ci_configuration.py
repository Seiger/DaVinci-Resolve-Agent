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


def test_windows_ci_builds_and_installs_wheel_package() -> None:
    workflow = _workflow_text()

    assert "wheel-package:" in workflow
    assert "name: Wheel package" in workflow
    assert "timeout-minutes: 10" in workflow
    assert "python -m pip wheel --no-deps --no-build-isolation" in workflow
    assert r"python .\scripts\check_wheel.py .\dist" in workflow
    assert "python -m pip uninstall --yes davinci-resolve-agent" in workflow
    assert "python -m pip install --no-deps $wheels[0].FullName" in workflow
    assert "Push-Location $env:RUNNER_TEMP" in workflow
    assert "Packaged resources OK" in workflow


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
    assert 'StartsWith("# pre-existing config`n")' in script
    assert "Installer did not update its three managed storage paths." in script


def test_installer_lifecycle_runs_offline_verification() -> None:
    repository_root = Path(__file__).parents[2]
    lifecycle = (
        repository_root / "scripts" / "test-installer-lifecycle.ps1"
    ).read_text(encoding="utf-8")
    verification = (
        repository_root / "installer" / "verify.ps1"
    ).read_text(encoding="utf-8")
    common = (
        repository_root / "installer" / "common.ps1"
    ).read_text(encoding="utf-8")

    assert "-SkipResolveConnection" in lifecycle
    assert 'Assert-LastExitCode -Operation "Offline installer verification"' in (
        lifecycle
    )
    assert "[switch]$SkipResolveConnection" in verification
    assert "load_config(Path(sys.argv[1]))" in verification
    assert "Test-DirectoryWriteAccess" in verification
    assert "if ($SkipResolveConnection)" in verification
    assert "& $cli status" in verification
    assert "'bridge.ping'" in verification
    assert "function Test-DirectoryWriteAccess" in common
    assert "[System.IO.FileMode]::CreateNew" in common
    assert "Remove-Item -LiteralPath $probePath -Force" in common


def test_installer_and_verifier_cover_all_take_sequence_directories() -> None:
    repository_root = Path(__file__).parents[2]
    common = (repository_root / "installer" / "common.ps1").read_text(
        encoding="utf-8"
    )
    install = (repository_root / "installer" / "install.ps1").read_text(
        encoding="utf-8"
    )
    verify = (repository_root / "installer" / "verify.ps1").read_text(
        encoding="utf-8"
    )
    lifecycle = (
        repository_root / "scripts" / "test-installer-lifecycle.ps1"
    ).read_text(encoding="utf-8")

    paths = {
        "TakeSequencesRoot": "take-sequences",
        "TakeSequenceBindingsRoot": "take-sequence-bindings",
        "TakeSequenceMediaImportsRoot": "take-sequence-media-imports",
        "TakeSequenceTimelineApplicationsRoot": (
            "take-sequence-timeline-applications"
        ),
        "TakeSequenceQcReportsRoot": "take-sequence-qc-reports",
        "TakeSequenceQcReviewsRoot": "take-sequence-qc-reviews",
        "TakeSequenceRendersRoot": "take-sequence-renders",
    }
    for property_name, directory_name in paths.items():
        assert property_name in common
        assert f"$paths.{property_name}" in install
        assert f"$paths.{property_name}" in verify
        assert f'"{directory_name}"' in lifecycle
