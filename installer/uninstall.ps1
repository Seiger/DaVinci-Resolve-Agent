[CmdletBinding()]
param(
    [Parameter(Mandatory = $false)]
    [Nullable[bool]]$PreserveConfig = $null,

    [Parameter(Mandatory = $false)]
    [Nullable[bool]]$PreserveLogs = $null,

    [Parameter(Mandatory = $false)]
    [bool]$PreserveBackups = $true,

    [Parameter(Mandatory = $false)]
    [bool]$PreservePlans = $true,

    [Parameter(Mandatory = $false)]
    [bool]$PreserveAudioReports = $true,

    [Parameter(Mandatory = $false)]
    [bool]$PreserveProcessedAudio = $true,

    [Parameter(Mandatory = $false)]
    [bool]$PreserveRenderOutput = $true
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

. (Join-Path $PSScriptRoot "common.ps1")

$repositoryRoot = Split-Path -Parent $PSScriptRoot
$paths = Get-AgentPaths -RepositoryRoot $repositoryRoot

$keepConfig = Resolve-PreservationChoice `
    -Prompt "Preserve local configuration?" `
    -ProvidedValue $PreserveConfig
$keepLogs = Resolve-PreservationChoice `
    -Prompt "Preserve runtime logs?" `
    -ProvidedValue $PreserveLogs

if (Test-Path -LiteralPath $paths.BridgeTarget -PathType Leaf) {
    $bridgeCanBeRemoved = $false
    $targetHash = (
        Get-FileHash -LiteralPath $paths.BridgeTarget -Algorithm SHA256
    ).Hash
    if (Test-Path -LiteralPath $paths.BridgeHashMarker -PathType Leaf) {
        $recordedHash = (
            Get-Content -LiteralPath $paths.BridgeHashMarker -Raw
        ).Trim()
        $bridgeCanBeRemoved = $recordedHash -eq $targetHash
    } elseif (Test-Path -LiteralPath $paths.BridgeSource -PathType Leaf) {
        $sourceHash = (Get-FileHash -LiteralPath $paths.BridgeSource -Algorithm SHA256).Hash
        $bridgeCanBeRemoved = $sourceHash -eq $targetHash
    }

    if ($bridgeCanBeRemoved) {
        Remove-Item -LiteralPath $paths.BridgeTarget -Force
        Write-Host "Removed installed Resolve bridge: $($paths.BridgeTarget)"
    } else {
        Write-Warning (
            "Preserved modified Resolve bridge because it differs from this " +
            "repository: $($paths.BridgeTarget)"
        )
    }
}

if (Test-Path -LiteralPath $paths.BridgeHashMarker -PathType Leaf) {
    Remove-Item -LiteralPath $paths.BridgeHashMarker -Force
}

if (
    -not (Test-Path -LiteralPath $paths.BridgeTarget) -and
    (Test-Path -LiteralPath $paths.BridgeBackup -PathType Leaf)
) {
    Move-Item -LiteralPath $paths.BridgeBackup -Destination $paths.BridgeTarget
    Write-Host "Restored previous Resolve bridge: $($paths.BridgeTarget)"
}

if (Test-Path -LiteralPath $paths.VirtualEnvironment) {
    Remove-Item -LiteralPath $paths.VirtualEnvironment -Recurse -Force
    Write-Host "Removed virtual environment: $($paths.VirtualEnvironment)"
}

if (-not $keepConfig -and (Test-Path -LiteralPath $paths.ConfigRoot)) {
    Remove-Item -LiteralPath $paths.ConfigRoot -Recurse -Force
    Write-Host "Removed application configuration: $($paths.ConfigRoot)"
} elseif ($keepConfig) {
    Write-Host "Preserved application configuration: $($paths.ConfigRoot)"
}

if (Test-Path -LiteralPath $paths.RuntimeRoot) {
    if (
        $keepLogs -or
        $PreserveBackups -or
        $PreservePlans -or
        $PreserveAudioReports
    ) {
        $preservedPaths = @()
        if ($keepLogs) {
            $preservedPaths += $paths.LogsRoot
        }
        if ($PreserveBackups) {
            $preservedPaths += $paths.BackupsRoot
        }
        if ($PreservePlans) {
            $preservedPaths += $paths.PlansRoot
        }
        if ($PreserveAudioReports) {
            $preservedPaths += $paths.AudioReportsRoot
        }
        Get-ChildItem -LiteralPath $paths.RuntimeRoot -Force |
            Where-Object { $_.FullName -notin $preservedPaths } |
            Remove-Item -Recurse -Force
        if ($keepLogs) {
            Write-Host "Preserved runtime logs: $($paths.LogsRoot)"
        }
        if ($PreserveBackups) {
            Write-Host "Preserved project backups: $($paths.BackupsRoot)"
        }
        if ($PreservePlans) {
            Write-Host "Preserved rough-cut plans: $($paths.PlansRoot)"
        }
        if ($PreserveAudioReports) {
            Write-Host "Preserved audio reports: $($paths.AudioReportsRoot)"
        }
    } else {
        Remove-Item -LiteralPath $paths.RuntimeRoot -Recurse -Force
        Write-Host (
            "Removed application runtime, logs, project backups, and plans: " +
            $paths.RuntimeRoot
        )
    }
}

if (
    -not $PreserveProcessedAudio -and
    (Test-Path -LiteralPath $paths.ProcessedAudioRoot)
) {
    Remove-Item -LiteralPath $paths.ProcessedAudioRoot -Recurse -Force
    Write-Host "Removed derived audio: $($paths.ProcessedAudioRoot)"
} elseif ($PreserveProcessedAudio) {
    Write-Host "Preserved derived audio: $($paths.ProcessedAudioRoot)"
}

if (
    -not $PreserveRenderOutput -and
    (Test-Path -LiteralPath $paths.RenderOutputRoot)
) {
    Remove-Item -LiteralPath $paths.RenderOutputRoot -Recurse -Force
    Write-Host "Removed rendered outputs: $($paths.RenderOutputRoot)"
} elseif ($PreserveRenderOutput) {
    Write-Host "Preserved rendered outputs: $($paths.RenderOutputRoot)"
}

Write-Host "Uninstallation completed. Repository, media, and Resolve projects were not removed."
