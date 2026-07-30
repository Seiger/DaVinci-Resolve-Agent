# Windows installation

## Supported environment

- Windows 10 or Windows 11
- Python 3.10–3.12 available through `py` or `python`
- access to the configured Python package index during the first installation

## Install and verify

```powershell
.\installer\install.ps1
```

Both scripts derive the repository root from their own location. They do not
contain user- or drive-specific absolute paths. Re-running `install.ps1`
preserves an existing local configuration file and re-applies the editable
package installation.

The installer copies the internal script to the current user's documented
Resolve script tree. If a different file already occupies the target path, the
installer preserves it as `ResolveBridge.py.davinci-agent-backup`.

## First Resolve health check

Resolve scans menu scripts at startup:

1. Restart DaVinci Resolve after installation.
2. Open a project.
3. Select `Workspace → Scripts → Edit → ResolveBridge`.
4. Return to PowerShell and run:

```powershell
.\installer\verify.ps1
.\.venv\Scripts\davinci-agent.exe status
```

The bridge is one-shot in M1. If `status` reports a stale heartbeat, run
`ResolveBridge` from the Workspace menu again.

For an M2 live request, start a command in PowerShell and invoke
`ResolveBridge` while it waits:

```powershell
.\.venv\Scripts\davinci-agent.exe ping --timeout-seconds 60
.\.venv\Scripts\davinci-agent.exe resolve capabilities --timeout-seconds 60
.\.venv\Scripts\davinci-agent.exe resolve project --timeout-seconds 60
```

## Application directories

```text
%APPDATA%\DaVinciResolveAgent\config.toml
%LOCALAPPDATA%\DaVinciResolveAgent\runtime\
%LOCALAPPDATA%\DaVinciResolveAgent\runtime\commands\
%LOCALAPPDATA%\DaVinciResolveAgent\runtime\processing\
%LOCALAPPDATA%\DaVinciResolveAgent\runtime\responses\
%LOCALAPPDATA%\DaVinciResolveAgent\runtime\failed\
%LOCALAPPDATA%\DaVinciResolveAgent\runtime\state\
%LOCALAPPDATA%\DaVinciResolveAgent\runtime\state\receipts\
%LOCALAPPDATA%\DaVinciResolveAgent\runtime\logs\
%LOCALAPPDATA%\DaVinciResolveAgent\runtime\backups\
%LOCALAPPDATA%\DaVinciResolveAgent\runtime\plans\
%LOCALAPPDATA%\DaVinciResolveAgent\runtime\audio-reports\
%USERPROFILE%\Videos\DaVinciResolveAgent\processed\
```

## Uninstall

Run interactively:

```powershell
.\installer\uninstall.ps1
```

Or provide both preservation choices:

```powershell
.\installer\uninstall.ps1 `
    -PreserveConfig $true `
    -PreserveLogs $true `
    -PreserveBackups $true `
    -PreservePlans $true `
    -PreserveAudioReports $true `
    -PreserveProcessedAudio $true
```

The script removes only `.venv` and the named application directories. It does
not remove the repository, media, or Resolve projects. It removes the installed
bridge only when it still matches the repository source and restores a previous
bridge backup when available. Project `.drp` backups are preserved by default;
pass `-PreserveBackups $false` only when their deletion is intentional.
Rough-cut draft plans are also preserved by default; use
`-PreservePlans $false` to remove them intentionally.
Audio reports and derived WAV files are preserved by default. Delete them only
with `-PreserveAudioReports $false -PreserveProcessedAudio $false`.
