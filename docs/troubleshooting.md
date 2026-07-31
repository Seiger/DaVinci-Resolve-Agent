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

Then fully restart Resolve and check
`Workspace → Scripts → Edit → ResolveBridge`.

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
