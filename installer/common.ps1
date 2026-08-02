Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$script:MinimumPythonVersion = [Version]"3.10"
$script:MaximumPythonVersion = [Version]"3.12"
$script:ApplicationDirectoryName = "DaVinciResolveAgent"

function Test-SupportedPythonVersion {
    param(
        [Parameter(Mandatory = $true)]
        [Version]$Version
    )

    return (
        $Version.Major -eq 3 -and
        $Version.Minor -ge $script:MinimumPythonVersion.Minor -and
        $Version.Minor -le $script:MaximumPythonVersion.Minor
    )
}

function Find-CompatiblePython {
    $candidates = @(
        [PSCustomObject]@{ Command = "py"; Arguments = @("-3.12") },
        [PSCustomObject]@{ Command = "py"; Arguments = @("-3.11") },
        [PSCustomObject]@{ Command = "py"; Arguments = @("-3.10") },
        [PSCustomObject]@{ Command = "python"; Arguments = @() }
    )

    foreach ($candidate in $candidates) {
        if (-not (Get-Command $candidate.Command -ErrorAction SilentlyContinue)) {
            continue
        }

        $candidateArguments = @($candidate.Arguments)
        $versionText = & $candidate.Command @candidateArguments -c (
            "import sys; print('.'.join(map(str, sys.version_info[:3])))"
        ) 2>$null

        if ($LASTEXITCODE -ne 0 -or -not $versionText) {
            continue
        }

        $version = [Version]$versionText.Trim()
        if (Test-SupportedPythonVersion -Version $version) {
            return [PSCustomObject]@{
                Command = $candidate.Command
                Arguments = $candidateArguments
                Version = $version
            }
        }
    }

    throw "Python 3.10, 3.11, or 3.12 was not found through 'py' or 'python'."
}

function Get-AgentPaths {
    param(
        [Parameter(Mandatory = $true)]
        [string]$RepositoryRoot,

        [Parameter(Mandatory = $false)]
        [string]$DataRoot
    )

    if (-not $env:APPDATA) {
        throw "The APPDATA environment variable is not set."
    }
    if (-not $env:LOCALAPPDATA) {
        throw "The LOCALAPPDATA environment variable is not set."
    }
    if (-not $env:USERPROFILE) {
        throw "The USERPROFILE environment variable is not set."
    }

    $configRoot = Join-Path $env:APPDATA $script:ApplicationDirectoryName
    $storageManifest = Join-Path $configRoot "storage.json"
    if ($DataRoot) {
        $resolvedDataRoot = [System.IO.Path]::GetFullPath($DataRoot)
    } elseif (Test-Path -LiteralPath $storageManifest -PathType Leaf) {
        try {
            $storage = Get-Content -LiteralPath $storageManifest -Raw |
                ConvertFrom-Json
        } catch {
            throw "Storage manifest is unreadable: $storageManifest"
        }
        if (
            $storage.storage_version -ne "1.0" -or
            -not $storage.data_root
        ) {
            throw "Storage manifest does not match version 1.0: $storageManifest"
        }
        $resolvedDataRoot = [System.IO.Path]::GetFullPath(
            [string]$storage.data_root
        )
    } else {
        $resolvedDataRoot = Join-Path (
            $env:LOCALAPPDATA
        ) $script:ApplicationDirectoryName
    }
    $resolvedDataRoot = $resolvedDataRoot.TrimEnd(
        [System.IO.Path]::DirectorySeparatorChar,
        [System.IO.Path]::AltDirectorySeparatorChar
    )
    $volumeRoot = [System.IO.Path]::GetPathRoot($resolvedDataRoot).TrimEnd(
        [System.IO.Path]::DirectorySeparatorChar,
        [System.IO.Path]::AltDirectorySeparatorChar
    )
    if (-not [System.IO.Path]::IsPathFullyQualified($resolvedDataRoot)) {
        throw "DataRoot must be an absolute path: $resolvedDataRoot"
    }
    if ($resolvedDataRoot -eq $volumeRoot) {
        throw "DataRoot must not be a volume root: $resolvedDataRoot"
    }
    $runtimeRoot = Join-Path $resolvedDataRoot "runtime"
    $mediaRoot = Join-Path $resolvedDataRoot "media"
    $resolveScriptsRoot = Join-Path $env:APPDATA (
        "Blackmagic Design\DaVinci Resolve\Support\Fusion\Scripts\Edit"
    )
    $bridgeTarget = Join-Path $resolveScriptsRoot "ResolveBridge.py"
    $resolveTemplatesRoot = Join-Path $env:APPDATA (
        "Blackmagic Design\DaVinci Resolve\Support\Fusion\Templates"
    )
    $animationTemplateRelativePath = (
        "Edit\Titles\DaVinci Agent Accent Card.setting"
    )
    $animationTemplateSource = Join-Path (
        Join-Path $RepositoryRoot "config\fusion_templates"
    ) $animationTemplateRelativePath
    $animationTemplateTarget = Join-Path (
        $resolveTemplatesRoot
    ) $animationTemplateRelativePath

    return [PSCustomObject]@{
        RepositoryRoot = [System.IO.Path]::GetFullPath($RepositoryRoot)
        VirtualEnvironment = Join-Path $RepositoryRoot ".venv"
        ConfigRoot = $configRoot
        ConfigFile = Join-Path $configRoot "config.toml"
        StorageManifest = $storageManifest
        DataRoot = $resolvedDataRoot
        MediaRoot = $mediaRoot
        RuntimeRoot = $runtimeRoot
        LogsRoot = Join-Path $runtimeRoot "logs"
        CommandsRoot = Join-Path $runtimeRoot "commands"
        ProcessingRoot = Join-Path $runtimeRoot "processing"
        ResponsesRoot = Join-Path $runtimeRoot "responses"
        FailedRoot = Join-Path $runtimeRoot "failed"
        StateRoot = Join-Path $runtimeRoot "state"
        ReceiptsRoot = Join-Path (Join-Path $runtimeRoot "state") "receipts"
        BackupsRoot = Join-Path $runtimeRoot "backups"
        PlansRoot = Join-Path $runtimeRoot "plans"
        AudioReportsRoot = Join-Path $runtimeRoot "audio-reports"
        SubtitleReceiptsRoot = Join-Path $runtimeRoot "subtitle-receipts"
        EditingRecipeRunsRoot = Join-Path $runtimeRoot "editing-recipe-runs"
        VisualTreatmentsRoot = Join-Path $runtimeRoot "visual-treatments"
        AnimationTemplateRunsRoot = Join-Path (
            $runtimeRoot
        ) "animation-template-runs"
        ColorTreatmentRunsRoot = Join-Path $runtimeRoot "color-treatment-runs"
        TakeSelectionsRoot = Join-Path $runtimeRoot "take-selections"
        TakeSelectionReviewsRoot = Join-Path (
            $runtimeRoot
        ) "take-selection-reviews"
        TakeSequencesRoot = Join-Path $runtimeRoot "take-sequences"
        TakeSequenceBindingsRoot = Join-Path (
            $runtimeRoot
        ) "take-sequence-bindings"
        TakeSequenceMediaImportsRoot = Join-Path (
            $runtimeRoot
        ) "take-sequence-media-imports"
        TakeSequenceTimelineApplicationsRoot = Join-Path (
            $runtimeRoot
        ) "take-sequence-timeline-applications"
        TakeSequenceQcReportsRoot = Join-Path (
            $runtimeRoot
        ) "take-sequence-qc-reports"
        TakeSequenceQcReviewsRoot = Join-Path (
            $runtimeRoot
        ) "take-sequence-qc-reviews"
        TakeSequenceRendersRoot = Join-Path (
            $runtimeRoot
        ) "take-sequence-renders"
        TranscriptionModelsRoot = Join-Path (
            Join-Path $runtimeRoot "models"
        ) "faster-whisper"
        DiagnosticsRoot = Join-Path $runtimeRoot "diagnostics"
        ProcessedAudioRoot = Join-Path $mediaRoot "processed"
        RenderOutputRoot = Join-Path $mediaRoot "renders"
        SubtitleOutputRoot = Join-Path $mediaRoot "subtitles"
        AudioSourceRoot = Join-Path $mediaRoot "audio-sources"
        LegacyRuntimeLink = Join-Path (
            Join-Path $env:LOCALAPPDATA $script:ApplicationDirectoryName
        ) "runtime"
        LegacyMediaLink = Join-Path (
            Join-Path $env:USERPROFILE "Videos"
        ) $script:ApplicationDirectoryName
        BridgeStateFile = Join-Path (Join-Path $runtimeRoot "state") "bridge.json"
        ResolveScriptsRoot = $resolveScriptsRoot
        BridgeSource = Join-Path $RepositoryRoot "bridges\resolve\ResolveBridge.py"
        BridgeTarget = $bridgeTarget
        BridgeBackup = "$bridgeTarget.davinci-agent-backup"
        BridgeHashMarker = "$bridgeTarget.davinci-agent.sha256"
        ResolveTemplatesRoot = $resolveTemplatesRoot
        AnimationTemplateManifestSource = Join-Path $RepositoryRoot (
            "config\animation_templates\accent-card-v1.json"
        )
        AnimationTemplateSource = $animationTemplateSource
        AnimationTemplateTarget = $animationTemplateTarget
        AnimationTemplateBackup = (
            "$animationTemplateTarget.davinci-agent-backup"
        )
        AnimationTemplateHashMarker = (
            "$animationTemplateTarget.davinci-agent.sha256"
        )
    }
}

function Write-StorageManifest {
    param(
        [Parameter(Mandatory = $true)]
        [PSCustomObject]$Paths
    )

    New-Item -ItemType Directory -Path $Paths.ConfigRoot -Force | Out-Null
    $payload = [ordered]@{
        storage_version = "1.0"
        data_root = $Paths.DataRoot
    } | ConvertTo-Json
    $temporaryPath = "$($Paths.StorageManifest).tmp"
    [System.IO.File]::WriteAllText(
        $temporaryPath,
        $payload + [Environment]::NewLine,
        [System.Text.UTF8Encoding]::new($false)
    )
    Move-Item `
        -LiteralPath $temporaryPath `
        -Destination $Paths.StorageManifest `
        -Force
}

function Test-DirectoryWriteAccess {
    param(
        [Parameter(Mandatory = $true)]
        [string]$LiteralPath
    )

    if (-not (Test-Path -LiteralPath $LiteralPath -PathType Container)) {
        throw "Directory does not exist: $LiteralPath"
    }

    $probePath = Join-Path $LiteralPath (
        ".davinci-agent-write-probe-{0}.tmp" -f [Guid]::NewGuid()
    )
    $stream = $null
    try {
        $stream = [System.IO.File]::Open(
            $probePath,
            [System.IO.FileMode]::CreateNew,
            [System.IO.FileAccess]::Write,
            [System.IO.FileShare]::None
        )
        $probeBytes = [System.Text.Encoding]::UTF8.GetBytes("write-probe")
        $stream.Write($probeBytes, 0, $probeBytes.Length)
    } catch {
        throw (
            "Directory is not writable: $LiteralPath. " +
            $_.Exception.Message
        )
    } finally {
        if ($null -ne $stream) {
            $stream.Dispose()
        }
        if (Test-Path -LiteralPath $probePath -PathType Leaf) {
            Remove-Item -LiteralPath $probePath -Force
        }
    }

    return $true
}

function Resolve-PreservationChoice {
    param(
        [Parameter(Mandatory = $true)]
        [string]$Prompt,

        [Parameter(Mandatory = $false)]
        [object]$ProvidedValue = $null
    )

    if ($null -ne $ProvidedValue) {
        return [bool]$ProvidedValue
    }

    $answer = Read-Host "$Prompt [Y/n]"
    return $answer -notmatch "^(n|no)$"
}
