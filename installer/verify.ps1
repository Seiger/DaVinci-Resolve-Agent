[CmdletBinding()]
param()

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

. (Join-Path $PSScriptRoot "common.ps1")

try {
    $repositoryRoot = Split-Path -Parent $PSScriptRoot
    $paths = Get-AgentPaths -RepositoryRoot $repositoryRoot
    $python = Find-CompatiblePython
    Write-Host "Compatible system Python: $($python.Version)"

    if (-not (Test-Path -LiteralPath $paths.VirtualEnvironment -PathType Container)) {
        throw "Virtual environment not found: $($paths.VirtualEnvironment)"
    }

    $venvPython = Join-Path $paths.VirtualEnvironment "Scripts\python.exe"
    $cli = Join-Path $paths.VirtualEnvironment "Scripts\davinci-agent.exe"
    $mcpServer = Join-Path (
        $paths.VirtualEnvironment
    ) "Scripts\davinci-agent-mcp.exe"

    if (-not (Test-Path -LiteralPath $venvPython -PathType Leaf)) {
        throw "Virtual environment Python not found: $venvPython"
    }
    if (-not (Test-Path -LiteralPath $cli -PathType Leaf)) {
        throw "CLI executable not found: $cli"
    }
    if (-not (Test-Path -LiteralPath $mcpServer -PathType Leaf)) {
        throw "MCP server executable not found: $mcpServer"
    }

    & $venvPython -c (
        "import agent, mcp_server; " +
        "from agent.configuration import load_default_config; " +
        "load_default_config(); print(f'Package import OK: {agent.__version__}')"
    )
    if ($LASTEXITCODE -ne 0) {
        throw "Package import or default configuration validation failed."
    }

    & $cli --version
    if ($LASTEXITCODE -ne 0) {
        throw "davinci-agent --version failed."
    }

    foreach ($directory in @(
        $paths.ConfigRoot,
        $paths.RuntimeRoot,
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
        $paths.LogsRoot,
        $paths.ResolveScriptsRoot
    )) {
        if (-not (Test-Path -LiteralPath $directory -PathType Container)) {
            throw "Required application directory not found: $directory"
        }
    }
    if (-not (Test-Path -LiteralPath $paths.ConfigFile -PathType Leaf)) {
        throw "Local configuration file not found: $($paths.ConfigFile)"
    }
    if (-not (Test-Path -LiteralPath $paths.BridgeTarget -PathType Leaf)) {
        throw "Installed Resolve bridge not found: $($paths.BridgeTarget)"
    }

    $sourceHash = (Get-FileHash -LiteralPath $paths.BridgeSource -Algorithm SHA256).Hash
    $targetHash = (Get-FileHash -LiteralPath $paths.BridgeTarget -Algorithm SHA256).Hash
    if ($sourceHash -ne $targetHash) {
        throw "Installed Resolve bridge differs from the repository source."
    }
    if (-not (Test-Path -LiteralPath $paths.BridgeStateFile -PathType Leaf)) {
        throw (
            "Resolve bridge has not written its state. Restart Resolve, open a " +
            "project, and run Workspace > Scripts > Edit > ResolveBridge."
        )
    }

    & $cli status
    if ($LASTEXITCODE -ne 0) {
        throw "Resolve bridge heartbeat is missing, stale, or unhealthy."
    }

    $bridgeState = Get-Content -LiteralPath $paths.BridgeStateFile -Raw |
        ConvertFrom-Json
    if (-not $bridgeState.capabilities.'bridge.ping') {
        throw "Resolve bridge did not report the ping capability."
    }
    Write-Host "Resolve product: $($bridgeState.product_name)"
    Write-Host "Resolve version: $($bridgeState.resolve_version)"
    Write-Host "Current project: $($bridgeState.project_name)"
    Write-Host "Current timeline: $($bridgeState.current_timeline_name)"

    Write-Host "Verification completed successfully."
    exit 0
} catch {
    Write-Error "Verification failed: $($_.Exception.Message)"
    exit 1
}
