[CmdletBinding()]
param()

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$repositoryRoot = Split-Path -Parent $PSScriptRoot
$temporaryRoot = [System.IO.Path]::GetFullPath(
    [System.IO.Path]::GetTempPath()
)
$sandboxRoot = Join-Path $temporaryRoot (
    "DaVinciResolveAgent-Installer-{0}" -f [Guid]::NewGuid()
)
$sandboxRoot = [System.IO.Path]::GetFullPath($sandboxRoot)
$sandboxRepository = Join-Path $sandboxRoot "repository"
$sentinel = Join-Path $sandboxRoot "outside-installer.txt"

$originalEnvironment = @{
    APPDATA = $env:APPDATA
    LOCALAPPDATA = $env:LOCALAPPDATA
    PIP_CACHE_DIR = $env:PIP_CACHE_DIR
    USERPROFILE = $env:USERPROFILE
}

function Assert-PathExists {
    param(
        [Parameter(Mandatory = $true)]
        [string]$LiteralPath,

        [Parameter(Mandatory = $true)]
        [ValidateSet("Container", "Leaf")]
        [string]$PathType
    )

    if (-not (Test-Path -LiteralPath $LiteralPath -PathType $PathType)) {
        throw "Expected $PathType was not created: $LiteralPath"
    }
}

function Assert-LastExitCode {
    param(
        [Parameter(Mandatory = $true)]
        [string]$Operation
    )

    if ($LASTEXITCODE -ne 0) {
        throw "$Operation failed with exit code $LASTEXITCODE."
    }
}

try {
    if (
        -not $sandboxRoot.StartsWith(
            $temporaryRoot,
            [StringComparison]::OrdinalIgnoreCase
        ) -or
        [System.IO.Path]::GetFileName($sandboxRoot) -notlike (
            "DaVinciResolveAgent-Installer-*"
        )
    ) {
        throw "Refusing to use an unsafe installer test root: $sandboxRoot"
    }

    New-Item -ItemType Directory -Path $sandboxRepository -Force | Out-Null
    [System.IO.File]::WriteAllText(
        $sentinel,
        "preserve",
        [System.Text.UTF8Encoding]::new($false)
    )

    $trackedFiles = @(
        & git -C $repositoryRoot ls-files
    )
    Assert-LastExitCode -Operation "Tracked-file discovery"
    if ($trackedFiles.Count -eq 0) {
        throw "No tracked repository files were found."
    }

    foreach ($relativePath in $trackedFiles) {
        $source = Join-Path $repositoryRoot $relativePath
        if (-not (Test-Path -LiteralPath $source -PathType Leaf)) {
            throw "Tracked source file is missing: $source"
        }
        $destination = Join-Path $sandboxRepository $relativePath
        $destinationParent = Split-Path -Parent $destination
        New-Item -ItemType Directory -Path $destinationParent -Force |
            Out-Null
        Copy-Item -LiteralPath $source -Destination $destination
    }

    $env:APPDATA = Join-Path $sandboxRoot "AppData\Roaming"
    $env:LOCALAPPDATA = Join-Path $sandboxRoot "AppData\Local"
    $env:PIP_CACHE_DIR = Join-Path $sandboxRoot "pip-cache"
    $env:USERPROFILE = Join-Path $sandboxRoot "User"
    foreach ($profileRoot in @(
        $env:APPDATA,
        $env:LOCALAPPDATA,
        $env:PIP_CACHE_DIR,
        $env:USERPROFILE
    )) {
        New-Item -ItemType Directory -Path $profileRoot -Force | Out-Null
    }

    $resolveScripts = Join-Path $env:APPDATA (
        "Blackmagic Design\DaVinci Resolve\Support\Fusion\Scripts\Edit"
    )
    $bridgeTarget = Join-Path $resolveScripts "ResolveBridge.py"
    $bridgeBackup = "$bridgeTarget.davinci-agent-backup"
    $configRoot = Join-Path $env:APPDATA "DaVinciResolveAgent"
    $configFile = Join-Path $configRoot "config.toml"
    $runtimeRoot = Join-Path (
        Join-Path $env:LOCALAPPDATA "DaVinciResolveAgent"
    ) "runtime"

    New-Item -ItemType Directory -Path $resolveScripts -Force | Out-Null
    New-Item -ItemType Directory -Path $configRoot -Force | Out-Null
    [System.IO.File]::WriteAllText(
        $bridgeTarget,
        "# pre-existing bridge`n",
        [System.Text.UTF8Encoding]::new($false)
    )
    [System.IO.File]::WriteAllText(
        $configFile,
        "# pre-existing config`n",
        [System.Text.UTF8Encoding]::new($false)
    )

    $install = Join-Path $sandboxRepository "installer\install.ps1"
    & $install

    $venvPython = Join-Path (
        $sandboxRepository
    ) ".venv\Scripts\python.exe"
    $cli = Join-Path (
        $sandboxRepository
    ) ".venv\Scripts\davinci-agent.exe"
    Assert-PathExists -LiteralPath $venvPython -PathType Leaf
    Assert-PathExists -LiteralPath $cli -PathType Leaf
    Assert-PathExists -LiteralPath $configFile -PathType Leaf
    Assert-PathExists -LiteralPath $runtimeRoot -PathType Container
    Assert-PathExists -LiteralPath $bridgeTarget -PathType Leaf
    Assert-PathExists -LiteralPath $bridgeBackup -PathType Leaf
    Assert-PathExists -LiteralPath (
        "$bridgeTarget.davinci-agent.sha256"
    ) -PathType Leaf

    $preservedConfig = Get-Content -LiteralPath $configFile -Raw
    if ($preservedConfig -ne "# pre-existing config`n") {
        throw "Installer replaced the pre-existing local configuration."
    }

    & $venvPython -c (
        "import agent, mcp_server; " +
        "from agent.configuration import load_default_config; " +
        "load_default_config(); print(agent.__version__)"
    )
    Assert-LastExitCode -Operation "Installed package import"
    & $cli --version
    Assert-LastExitCode -Operation "Installed CLI version check"

    & $install
    if (-not (Test-Path -LiteralPath $bridgeBackup -PathType Leaf)) {
        throw "Installer rerun removed the pre-existing bridge backup."
    }

    $uninstall = Join-Path $sandboxRepository "installer\uninstall.ps1"
    & $uninstall `
        -PreserveConfig $false `
        -PreserveLogs $false `
        -PreserveBackups $false `
        -PreservePlans $false `
        -PreserveAudioReports $false `
        -PreserveProcessedAudio $false `
        -PreserveRenderOutput $false

    if (Test-Path -LiteralPath (Join-Path $sandboxRepository ".venv")) {
        throw "Uninstaller did not remove its virtual environment."
    }
    if (Test-Path -LiteralPath $configRoot) {
        throw "Uninstaller did not remove the sandbox configuration."
    }
    if (Test-Path -LiteralPath $runtimeRoot) {
        throw "Uninstaller did not remove the sandbox runtime."
    }

    Assert-PathExists -LiteralPath $bridgeTarget -PathType Leaf
    $restoredBridge = Get-Content -LiteralPath $bridgeTarget -Raw
    if ($restoredBridge -ne "# pre-existing bridge`n") {
        throw "Uninstaller did not restore the pre-existing bridge."
    }
    Assert-PathExists -LiteralPath $sentinel -PathType Leaf

    Write-Host (
        "Installer lifecycle OK: isolated install, rerun, and uninstall passed."
    )
} finally {
    $env:APPDATA = $originalEnvironment.APPDATA
    $env:LOCALAPPDATA = $originalEnvironment.LOCALAPPDATA
    $env:PIP_CACHE_DIR = $originalEnvironment.PIP_CACHE_DIR
    $env:USERPROFILE = $originalEnvironment.USERPROFILE

    if (
        (Test-Path -LiteralPath $sandboxRoot) -and
        $sandboxRoot.StartsWith(
            $temporaryRoot,
            [StringComparison]::OrdinalIgnoreCase
        ) -and
        [System.IO.Path]::GetFileName($sandboxRoot) -like (
            "DaVinciResolveAgent-Installer-*"
        )
    ) {
        Remove-Item -LiteralPath $sandboxRoot -Recurse -Force
    }
}
