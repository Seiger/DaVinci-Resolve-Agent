[CmdletBinding()]
param(
    [Parameter(Mandatory = $false)]
    [string]$DataRoot
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

. (Join-Path $PSScriptRoot "common.ps1")

$repositoryRoot = Split-Path -Parent $PSScriptRoot
$paths = Get-AgentPaths -RepositoryRoot $repositoryRoot -DataRoot $DataRoot
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
    "from importlib.metadata import distributions; " +
    "versions={d.metadata['Name'].lower(): d.version for d in distributions()}; " +
    "print(versions.get('pip', '0.0') + '|' + " +
    "versions.get('setuptools', '0.0'))"
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
Write-StorageManifest -Paths $paths
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
    $paths.SubtitleReceiptsRoot,
    $paths.EditingRecipeRunsRoot,
    $paths.VisualTreatmentsRoot,
    $paths.AnimationTemplateRunsRoot,
    $paths.ColorTreatmentRunsRoot,
    $paths.TakeSelectionsRoot,
    $paths.TakeSelectionReviewsRoot,
    $paths.TakeSequencesRoot,
    $paths.TakeSequenceBindingsRoot,
    $paths.TakeSequenceMediaImportsRoot,
    $paths.TakeSequenceTimelineApplicationsRoot,
    $paths.TakeSequenceQcReportsRoot,
    $paths.TakeSequenceQcReviewsRoot,
    $paths.TakeSequenceRendersRoot,
    $paths.TranscriptionModelsRoot,
    $paths.DiagnosticsRoot,
    $paths.ProcessedAudioRoot,
    $paths.RenderOutputRoot,
    $paths.SubtitleOutputRoot,
    $paths.AudioSourceRoot,
    $paths.LogsRoot
)) {
    New-Item -ItemType Directory -Path $runtimeDirectory -Force | Out-Null
}
Write-Host "Managed data root: $($paths.DataRoot)"

if (-not (Test-Path -LiteralPath $paths.ConfigFile)) {
    $defaultConfig = Join-Path $repositoryRoot "config\default.toml"
    Copy-Item -LiteralPath $defaultConfig -Destination $paths.ConfigFile
    Write-Host "Created local configuration: $($paths.ConfigFile)"
} else {
    Write-Host "Preserved existing local configuration: $($paths.ConfigFile)"
}
$storageConfigUpdater = Join-Path (
    Join-Path $repositoryRoot "installer"
) "update_storage_config.py"
& $venvPython $storageConfigUpdater $paths.ConfigFile $paths.DataRoot
if ($LASTEXITCODE -ne 0) {
    throw "Failed to update local storage configuration."
}
Write-Host "Updated local storage configuration: $($paths.ConfigFile)"

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

if (-not (
    Test-Path -LiteralPath $paths.AnimationTemplateManifestSource -PathType Leaf
)) {
    throw (
        "Animation template manifest not found: " +
        $paths.AnimationTemplateManifestSource
    )
}
if (-not (
    Test-Path -LiteralPath $paths.AnimationTemplateSource -PathType Leaf
)) {
    throw "Animation template source not found: $($paths.AnimationTemplateSource)"
}
$animationManifest = Get-Content `
    -LiteralPath $paths.AnimationTemplateManifestSource `
    -Raw | ConvertFrom-Json
$animationSourceHash = (
    Get-FileHash -LiteralPath $paths.AnimationTemplateSource -Algorithm SHA256
).Hash.ToLowerInvariant()
if ($animationManifest.asset_sha256 -ne $animationSourceHash) {
    throw "Animation template source differs from its packaged manifest."
}

$animationTargetRoot = Split-Path -Parent $paths.AnimationTemplateTarget
New-Item -ItemType Directory -Path $animationTargetRoot -Force | Out-Null
if (Test-Path -LiteralPath $paths.AnimationTemplateTarget -PathType Leaf) {
    $animationTargetHash = (
        Get-FileHash `
            -LiteralPath $paths.AnimationTemplateTarget `
            -Algorithm SHA256
    ).Hash.ToLowerInvariant()
    $animationTargetIsManaged = $false
    if (
        Test-Path `
            -LiteralPath $paths.AnimationTemplateHashMarker `
            -PathType Leaf
    ) {
        $recordedHash = (
            Get-Content -LiteralPath $paths.AnimationTemplateHashMarker -Raw
        ).Trim().ToLowerInvariant()
        $animationTargetIsManaged = $recordedHash -eq $animationTargetHash
    }
    if (
        $animationSourceHash -ne $animationTargetHash -and
        -not $animationTargetIsManaged -and
        -not (
            Test-Path `
                -LiteralPath $paths.AnimationTemplateBackup `
                -PathType Leaf
        )
    ) {
        Copy-Item `
            -LiteralPath $paths.AnimationTemplateTarget `
            -Destination $paths.AnimationTemplateBackup
        Write-Host (
            "Backed up existing Resolve animation template: " +
            $paths.AnimationTemplateBackup
        )
    }
}
Copy-Item `
    -LiteralPath $paths.AnimationTemplateSource `
    -Destination $paths.AnimationTemplateTarget `
    -Force
[System.IO.File]::WriteAllText(
    $paths.AnimationTemplateHashMarker,
    "$animationSourceHash`n",
    [System.Text.UTF8Encoding]::new($false)
)
Write-Host (
    "Installed Resolve animation template: $($paths.AnimationTemplateTarget)"
)

Write-Host "Installation completed."
Write-Host "Next manual steps:"
Write-Host "1. Restart DaVinci Resolve so it rescans user scripts and templates."
Write-Host "2. Open a project."
Write-Host "3. Run Workspace > Scripts > Edit > ResolveBridge."
Write-Host "4. Return here and run .\installer\verify.ps1"
