# Troubleshooting

## Local diagnostics bundle

Collect bounded local diagnostics without launching ResolveBridge:

```powershell
.\.venv\Scripts\davinci-agent.exe diagnostics
```

Review the generated JSON before sharing it. The collected fields and
redaction limits are documented in [diagnostics.md](diagnostics.md).

## Command audit remains pending

Transport audit records are stored under `runtime\logs\audit`. A `pending`
record means the command was published but no valid terminal response was
observed by that client process. Check the matching command/response evidence
and cached bridge state; do not edit the audit JSON manually.

Workflow records live separately under `runtime\logs\workflow`. A `running`
record means the process did not persist a terminal workflow state, commonly
because it was interrupted. Artifact contents and operation arguments cannot
be recovered from this record by design.

## ResolveBridge is absent from the Workspace menu

Resolve scans menu scripts at startup. Confirm installation:

```powershell
Test-Path "$env:APPDATA\Blackmagic Design\DaVinci Resolve\Support\Fusion\Scripts\Edit\ResolveBridge.py"
```

If the menu says **No Scripts**, first select the **Edit page** in the bottom
navigation. Opening the top-level Edit menu or Scripts → Edit submenu does not
switch from Deliver, Color, or another page. Confirm that the file is installed
for the same Windows user running Resolve, and that its extension is `.py`,
not `.py.txt`. Use the installer to restore a missing file and its configuration.

Then fully restart Resolve and check `Workspace → Scripts → ResolveBridge`
on the Edit page. From other pages the script can appear under an `Edit`
submenu; on the Edit page that submenu is absent.

If the file exists but **No Scripts** remains, inspect the current startup in
`%APPDATA%\Blackmagic Design\DaVinci Resolve\Support\logs\ResolveDebug.txt`.
Resolve Free 21.1.0.17 did not list the installed Python script. Restarting
did not restore it. Startup Fusion warnings were also present, but are not
established as its cause. Lua console API access and a limited background
transport worked in the same installation. See [the experimental Lua
prototype](lua-experimental.md); it is not a replacement for production editing
tools. Do not repeatedly reinstall/move the Python script to fix this edition
restriction.

## M52 animation template відсутній у Titles

Перевір installed template без абсолютного шляху:

```powershell
Test-Path "$env:APPDATA\Blackmagic Design\DaVinci Resolve\Support\Fusion\Templates\Edit\Titles\DaVinci Agent Accent Card.setting"
.\installer\verify.ps1 -SkipResolveConnection
```

Якщо обидві перевірки успішні, повністю перезапусти Resolve. Якщо raw
environment повідомляє hash mismatch, не копіюй довільний `.setting` поверх
файлу: повторно запусти `install.ps1` і перевір, чи інсталятор зберіг
користувацьку версію як `.davinci-agent-backup`.

## Bridge state was not found

Open a Resolve project and invoke `ResolveBridge` from the Workspace menu. The
expected state file is:

```powershell
"$env:LOCALAPPDATA\DaVinciResolveAgent\runtime\state\bridge.json"
```

## Heartbeat is stale

The manually launched persistent bridge is not running, has stopped, or has
failed. Inspect `state\bridge.json` and `logs\bridge.jsonl`, then run
`ResolveBridge` again and verify:

```powershell
.\installer\verify.ps1
```

## Live CLI command times out

Live commands require an active internal bridge and exit with code `3` on
timeout. Start `Workspace → Scripts → Edit → ResolveBridge` once, then run:

```powershell
.\.venv\Scripts\davinci-agent.exe ping --timeout-seconds 60
```

The timed-out command remains under `runtime\commands` until an active or later
bridge iteration rejects it as expired and moves it to `failed`.

## Resolve UI becomes unresponsive after bridge start

Persistent lifecycle is live-verified only on Resolve 21 Free 21.0.3.7. If UI
becomes unresponsive in another environment, send the allowlisted
`resolve_stop_bridge` command from MCP. If the bridge cannot process it, close
Resolve normally when possible, preserve `state\bridge.json` and
`logs\bridge.jsonl` for diagnosis, and record that environment as unsupported.

## Bridge reports BRIDGE_INITIALIZATION_FAILED

Inspect the safe error in `state\bridge.json` and the structured log in
`logs\bridge.jsonl`. Do not enable external scripting or network access as a
workaround. The M1 bridge must run from inside Resolve.

If the error reports Windows access denial while replacing `bridge.json`,
install the latest bridge and restart it once. The bridge uses a unique
temporary file and bounded retries for transient readers. If a heartbeat still
cannot replace the state file, the persistent bridge records
`state_publish_deferred` and retries on the next heartbeat instead of exiting.
A denial that persists across later heartbeats indicates an external lock or
directory permission problem that must be resolved instead of bypassed.

A direct `DaVinciResolveScript` import may be unavailable even inside a menu
script. The bridge therefore checks the injected internal Resolve/Fusion
context before trying the documented module fallback.

## Write command fails before editing

Inspect the structured response under `runtime\responses`. `PROJECT_SAVE_FAILED`
or `PROJECT_BACKUP_FAILED` means the bridge intentionally skipped the edit.
`MEDIA_PATH_NOT_ALLOWED` means the requested file is outside
`media.allowed_roots`.

If an error contains `details.backup_path`, the backup was created before
Resolve rejected the operation. Follow [rollback.md](rollback.md) rather than
automatically replacing the open project.
