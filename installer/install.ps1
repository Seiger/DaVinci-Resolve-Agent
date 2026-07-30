[CmdletBinding()]
param()

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

. (Join-Path $PSScriptRoot "common.ps1")

$repositoryRoot = Split-Path -Parent $PSScriptRoot
$paths = Get-AgentPaths -RepositoryRoot $repositoryRoot
$python = Find-CompatiblePython
$pythonArguments = @($python.Arguments)

Write-Host "Using Python $($python.Version) through '$($python.Command)'."

if (-not (Test-Path -LiteralPath $paths.VirtualEnvironment -PathType Container)) {
    Write-Host "Creating virtual environment..."
    & $python.Command @pythonArguments -m venv $paths.VirtualEnvironment
    if ($LASTEXITCODE -ne 0) {
        throw "Failed to create the virtual environment."
    }
}

$venvPython = Join-Path $paths.VirtualEnvironment "Scripts\python.exe"
if (-not (Test-Path -LiteralPath $venvPython -PathType Leaf)) {
    throw "The virtual environment exists but does not contain Scripts\python.exe."
}

$venvVersionText = & $venvPython -c (
    "import sys; print('.'.join(map(str, sys.version_info[:3])))"
)
if ($LASTEXITCODE -ne 0) {
    throw "Failed to inspect the virtual environment Python version."
}
$venvVersion = [Version]$venvVersionText.Trim()
if (-not (Test-SupportedPythonVersion -Version $venvVersion)) {
    throw (
        "The existing .venv uses unsupported Python $venvVersion. " +
        "Remove only .venv and run the installer again."
    )
}

$packagingVersions = & $venvPython -c (
    "import pip, setuptools; print(f'{pip.__version__}|{setuptools.__version__}')"
) 2>$null
$updatePackagingTools = $LASTEXITCODE -ne 0
if (-not $updatePackagingTools) {
    $versionParts = $packagingVersions.Trim().Split("|")
    $updatePackagingTools = (
        [Version]$versionParts[0] -lt [Version]"23.1" -or
        [Version]$versionParts[1] -lt [Version]"68.0"
    )
}

if ($updatePackagingTools) {
    Write-Host "Updating packaging tools inside the virtual environment..."
    & $venvPython -m pip install `
        --upgrade `
        "pip>=23.1" `
        "setuptools>=68" `
        --timeout 15 `
        --retries 2 `
        --disable-pip-version-check
    if ($LASTEXITCODE -ne 0) {
        throw (
            "Failed to update pip and setuptools in the virtual environment. " +
            "Check access to the configured Python package index."
        )
    }
} else {
    Write-Host "Packaging tools already satisfy the required versions."
}

Write-Host "Installing the package in editable mode..."
& $venvPython -m pip install `
    --editable $repositoryRoot `
    --no-build-isolation `
    --disable-pip-version-check
if ($LASTEXITCODE -ne 0) {
    throw "Editable package installation failed."
}

New-Item -ItemType Directory -Path $paths.ConfigRoot -Force | Out-Null
foreach ($runtimeDirectory in @(
    $paths.CommandsRoot,
    $paths.ProcessingRoot,
    $paths.ResponsesRoot,
    $paths.FailedRoot,
    $paths.StateRoot,
    $paths.ReceiptsRoot,
    $paths.BackupsRoot,
    $paths.PlansRoot,
    $paths.AudioReportsRoot,
    $paths.ProcessedAudioRoot,
    $paths.RenderOutputRoot,
    $paths.LogsRoot
)) {
    New-Item -ItemType Directory -Path $runtimeDirectory -Force | Out-Null
}

if (-not (Test-Path -LiteralPath $paths.ConfigFile)) {
    $defaultConfig = Join-Path $repositoryRoot "config\default.toml"
    Copy-Item -LiteralPath $defaultConfig -Destination $paths.ConfigFile
    Write-Host "Created local configuration: $($paths.ConfigFile)"
} else {
    Write-Host "Preserved existing local configuration: $($paths.ConfigFile)"
}

if (-not (Test-Path -LiteralPath $paths.BridgeSource -PathType Leaf)) {
    throw "Resolve bridge source not found: $($paths.BridgeSource)"
}

New-Item -ItemType Directory -Path $paths.ResolveScriptsRoot -Force | Out-Null
if (Test-Path -LiteralPath $paths.BridgeTarget -PathType Leaf) {
    $sourceHash = (Get-FileHash -LiteralPath $paths.BridgeSource -Algorithm SHA256).Hash
    $targetHash = (Get-FileHash -LiteralPath $paths.BridgeTarget -Algorithm SHA256).Hash
    $targetIsManaged = $false
    if (Test-Path -LiteralPath $paths.BridgeHashMarker -PathType Leaf) {
        $recordedHash = (
            Get-Content -LiteralPath $paths.BridgeHashMarker -Raw
        ).Trim()
        $targetIsManaged = $recordedHash -eq $targetHash
    }
    if ($sourceHash -ne $targetHash -and -not $targetIsManaged -and -not (
        Test-Path -LiteralPath $paths.BridgeBackup -PathType Leaf
    )) {
        Copy-Item -LiteralPath $paths.BridgeTarget -Destination $paths.BridgeBackup
        Write-Host "Backed up existing Resolve bridge: $($paths.BridgeBackup)"
    }
}
Copy-Item -LiteralPath $paths.BridgeSource -Destination $paths.BridgeTarget -Force
$installedHash = (
    Get-FileHash -LiteralPath $paths.BridgeTarget -Algorithm SHA256
).Hash
[System.IO.File]::WriteAllText(
    $paths.BridgeHashMarker,
    "$installedHash`n",
    [System.Text.UTF8Encoding]::new($false)
)
Write-Host "Installed Resolve bridge: $($paths.BridgeTarget)"

Write-Host "Installation completed."
Write-Host "Next manual steps:"
Write-Host "1. Restart DaVinci Resolve so it rescans user scripts."
Write-Host "2. Open a project."
Write-Host "3. Run Workspace > Scripts > Edit > ResolveBridge."
Write-Host "4. Return here and run .\installer\verify.ps1"
