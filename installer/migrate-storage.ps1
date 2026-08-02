[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)]
    [string]$DataRoot,

    [Parameter(Mandatory = $true)]
    [switch]$ConfirmBridgeStopped,

    [Parameter(Mandatory = $false)]
    [switch]$RemoveSource,

    [Parameter(Mandatory = $false)]
    [bool]$CreateLegacyJunctions = $true
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

. (Join-Path $PSScriptRoot "common.ps1")

if (-not $ConfirmBridgeStopped) {
    throw "ConfirmBridgeStopped is required before storage migration."
}

$repositoryRoot = Split-Path -Parent $PSScriptRoot
$paths = Get-AgentPaths -RepositoryRoot $repositoryRoot -DataRoot $DataRoot
$legacyRuntime = Join-Path (
    Join-Path $env:LOCALAPPDATA $script:ApplicationDirectoryName
) "runtime"
$legacyMedia = Join-Path (
    Join-Path (Join-Path $env:USERPROFILE "Videos") (
        $script:ApplicationDirectoryName
    )
) ""

$mappings = @(
    [PSCustomObject]@{
        Name = "runtime"
        Source = [System.IO.Path]::GetFullPath($legacyRuntime)
        Destination = [System.IO.Path]::GetFullPath($paths.RuntimeRoot)
    },
    [PSCustomObject]@{
        Name = "media"
        Source = [System.IO.Path]::GetFullPath($legacyMedia)
        Destination = [System.IO.Path]::GetFullPath($paths.MediaRoot)
    }
)

function Get-RelativeManagedPath {
    param(
        [Parameter(Mandatory = $true)]
        [string]$Root,
        [Parameter(Mandatory = $true)]
        [string]$Path
    )

    $rootWithSeparator = $Root.TrimEnd("\", "/") + "\"
    if (-not $Path.StartsWith(
        $rootWithSeparator,
        [System.StringComparison]::OrdinalIgnoreCase
    )) {
        throw "Path is outside the expected managed source: $Path"
    }
    return $Path.Substring($rootWithSeparator.Length)
}

$sourceFiles = @()
foreach ($mapping in $mappings) {
    if ($mapping.Source -eq $mapping.Destination) {
        throw "Migration source and destination must differ: $($mapping.Source)"
    }
    if (Test-Path -LiteralPath $mapping.Source -PathType Container) {
        $sourceFiles += Get-ChildItem `
            -LiteralPath $mapping.Source `
            -File `
            -Recurse `
            -Force
    }
}

$requiredBytes = ($sourceFiles | Measure-Object -Property Length -Sum).Sum
if ($null -eq $requiredBytes) {
    $requiredBytes = 0
}
$destinationDrive = [System.IO.Path]::GetPathRoot($paths.DataRoot)
$driveName = $destinationDrive.TrimEnd("\", "/").TrimEnd(":")
$drive = Get-PSDrive -Name $driveName
$reserveBytes = 1GB
if ($drive.Free -lt ($requiredBytes + $reserveBytes)) {
    throw (
        "Insufficient free space on $destinationDrive. Required with reserve: " +
        "$([math]::Round(($requiredBytes + $reserveBytes) / 1GB, 2)) GiB."
    )
}

Write-Host (
    "Copying $($sourceFiles.Count) files ($([math]::Round($requiredBytes / 1GB, 2)) " +
    "GiB) to $($paths.DataRoot)..."
)
foreach ($mapping in $mappings) {
    New-Item -ItemType Directory -Path $mapping.Destination -Force | Out-Null
    if (-not (Test-Path -LiteralPath $mapping.Source -PathType Container)) {
        continue
    }
    foreach ($sourceFile in Get-ChildItem `
        -LiteralPath $mapping.Source `
        -File `
        -Recurse `
        -Force
    ) {
        $relative = Get-RelativeManagedPath `
            -Root $mapping.Source `
            -Path $sourceFile.FullName
        $destinationFile = Join-Path $mapping.Destination $relative
        $destinationParent = Split-Path -Parent $destinationFile
        New-Item -ItemType Directory -Path $destinationParent -Force | Out-Null
        Copy-Item `
            -LiteralPath $sourceFile.FullName `
            -Destination $destinationFile `
            -Force
    }
}

Write-Host "Verifying copied file sizes and SHA-256 hashes..."
foreach ($mapping in $mappings) {
    if (-not (Test-Path -LiteralPath $mapping.Source -PathType Container)) {
        continue
    }
    foreach ($sourceFile in Get-ChildItem `
        -LiteralPath $mapping.Source `
        -File `
        -Recurse `
        -Force
    ) {
        $relative = Get-RelativeManagedPath `
            -Root $mapping.Source `
            -Path $sourceFile.FullName
        $destinationFile = Join-Path $mapping.Destination $relative
        if (-not (Test-Path -LiteralPath $destinationFile -PathType Leaf)) {
            throw "Migrated file is missing: $destinationFile"
        }
        $destinationInfo = Get-Item -LiteralPath $destinationFile
        if ($sourceFile.Length -ne $destinationInfo.Length) {
            throw "Migrated file size differs: $destinationFile"
        }
        $sourceHash = (
            Get-FileHash -LiteralPath $sourceFile.FullName -Algorithm SHA256
        ).Hash
        $destinationHash = (
            Get-FileHash -LiteralPath $destinationFile -Algorithm SHA256
        ).Hash
        if ($sourceHash -ne $destinationHash) {
            throw "Migrated file hash differs: $destinationFile"
        }
    }
}

Write-StorageManifest -Paths $paths
Write-Host "Verified storage manifest: $($paths.StorageManifest)"

if ($RemoveSource) {
    foreach ($mapping in $mappings) {
        if (-not (Test-Path -LiteralPath $mapping.Source)) {
            continue
        }
        $resolvedSource = [System.IO.Path]::GetFullPath($mapping.Source)
        if ($resolvedSource -notin @(
            [System.IO.Path]::GetFullPath($legacyRuntime),
            [System.IO.Path]::GetFullPath($legacyMedia)
        )) {
            throw "Refusing to remove an unexpected migration source: $resolvedSource"
        }
        Remove-Item -LiteralPath $resolvedSource -Recurse -Force
        Write-Host "Removed verified source data: $resolvedSource"
        if ($CreateLegacyJunctions) {
            $legacyParent = Split-Path -Parent $resolvedSource
            New-Item -ItemType Directory -Path $legacyParent -Force | Out-Null
            New-Item `
                -ItemType Junction `
                -Path $resolvedSource `
                -Target $mapping.Destination | Out-Null
            Write-Host (
                "Created compatibility junction: $resolvedSource -> " +
                $mapping.Destination
            )
        }
    }
}

Write-Host "Storage migration completed and verified."
