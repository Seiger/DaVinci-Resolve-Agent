# Windows installation

## Supported environment

- Windows 10 or Windows 11
- Python 3.10–3.12 available through `py` or `python`
- access to the configured Python package index during the first installation

## Install and verify

```powershell
.\installer\install.ps1
```

Для зберігання runtime, моделей і всіх generated media на окремому диску:

```powershell
.\installer\install.ps1 -DataRoot "G:\DaVinciResolveAgent"
```

Both scripts derive the repository root from their own location. They do not
contain user- or drive-specific absolute paths. Re-running `install.ps1`
idempotently preserves configuration and creates the complete M54/M55 durable
directory inventory under the selected `DataRoot`, then re-applies the editable
package installation.

The installer copies the internal script to the current user's documented
Resolve script tree. If a different file already occupies the target path, the
installer preserves it as `ResolveBridge.py.davinci-agent-backup`.

The source file is `bridges/resolve/ResolveBridge.py`. Its installed location is:

```text
%APPDATA%\Blackmagic Design\DaVinci Resolve\Support\Fusion\Scripts\Edit\ResolveBridge.py
```

Use `installer/install.ps1` to install the bridge together with its local
configuration and runtime. Copying the Python file alone is not a complete
installation. The `Edit` folder scopes the script to the Edit page; select that
page in the bottom navigation before opening the Scripts menu. The top-level
Edit menu and the Scripts → Edit submenu do not switch editor pages.

Інсталятор також перевіряє SHA-256 пакетованого M52 Fusion Title і копіює його
до `%APPDATA%\Blackmagic Design\DaVinci Resolve\Support\Fusion\Templates\Edit\Titles`.
Якщо цільовий template належить користувачу, він зберігається як
`.davinci-agent-backup`. Повторний запуск не перезаписує цей backup.

CI separately exercises install, repeat install, and uninstall in a generated
temporary repository copy with temporary Windows profile directories. This
smoke-test validates filesystem ownership and restoration behavior without
touching the developer's real profile or claiming live Resolve connectivity.
See [continuous integration](continuous-integration.md).

## First Resolve health check

Before starting Resolve, the installed local state can be checked explicitly:

```powershell
.\installer\verify.ps1 -SkipResolveConnection
```

This mode validates the supported Python, virtual environment, package and MCP
imports, packaged and machine-local configuration, installed CLI executables,
bridge hash, required directories, and temporary write/delete probes. It does
not accept or create a heartbeat and does not report Resolve connectivity.

Resolve scans menu scripts at startup:

1. Restart DaVinci Resolve after installation.
2. Open a project and select the **Edit** page in the bottom navigation.
3. On the Edit page, open `Workspace → Scripts` and select `ResolveBridge`.
   On other pages, Resolve may group it under an `Edit` submenu. The absence
   of an Edit submenu on the Edit page is normal.
4. Return to PowerShell and run:

```powershell
.\installer\verify.ps1
.\.venv\Scripts\davinci-agent.exe status
```

Повний restart також потрібен після першого встановлення або оновлення M52
title template, щоб Resolve повторно просканував Fusion Templates.

Після ручного запуску bridge лишається активним і оновлює heartbeat, доки не
отримає `resolve_stop_bridge`. Якщо `status` повідомляє stale heartbeat,
запусти `ResolveBridge` з Workspace menu знову. Responsive UI та clean stop
перевірено у Resolve 21 Free 21.0.3.7; інші environments залишаються в manual
test matrix.

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
<DataRoot>\runtime\
<DataRoot>\runtime\commands\
<DataRoot>\runtime\processing\
<DataRoot>\runtime\responses\
<DataRoot>\runtime\failed\
<DataRoot>\runtime\state\
<DataRoot>\runtime\state\receipts\
<DataRoot>\runtime\logs\
<DataRoot>\runtime\logs\audit\
<DataRoot>\runtime\logs\workflow\
<DataRoot>\runtime\diagnostics\
<DataRoot>\runtime\backups\
<DataRoot>\runtime\plans\
<DataRoot>\runtime\audio-reports\
<DataRoot>\media\processed\
<DataRoot>\media\renders\
<DataRoot>\media\audio-sources\
<DataRoot>\media\subtitles\
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
    -PreserveProcessedAudio $true `
    -PreserveRenderOutput $true
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
Prepared render outputs are preserved by default; remove them intentionally
with `-PreserveRenderOutput $false`.
