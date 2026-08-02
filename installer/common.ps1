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
        [string]$RepositoryRoot
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
    $runtimeRoot = Join-Path (
        Join-Path $env:LOCALAPPDATA $script:ApplicationDirectoryName
    ) "runtime"
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
        TranscriptionModelsRoot = Join-Path (
            Join-Path $runtimeRoot "models"
        ) "faster-whisper"
        DiagnosticsRoot = Join-Path $runtimeRoot "diagnostics"
        ProcessedAudioRoot = Join-Path (
            Join-Path (
                Join-Path $env:USERPROFILE "Videos"
            ) $script:ApplicationDirectoryName
        ) "processed"
        RenderOutputRoot = Join-Path (
            Join-Path (
                Join-Path $env:USERPROFILE "Videos"
            ) $script:ApplicationDirectoryName
        ) "renders"
        SubtitleOutputRoot = Join-Path (
            Join-Path (
                Join-Path $env:USERPROFILE "Videos"
            ) $script:ApplicationDirectoryName
        ) "subtitles"
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
