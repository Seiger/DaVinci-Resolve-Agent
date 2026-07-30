# Troubleshooting

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

M1 is intentionally one-shot. Run `ResolveBridge` again, then immediately run:

```powershell
.\installer\verify.ps1
```

## Live CLI command times out

Live commands wait for the one-shot bridge and exit with code `3` on timeout.
Start the CLI command with a sufficient deadline, then invoke
`Workspace → Scripts → Edit → ResolveBridge` before it expires:

```powershell
.\.venv\Scripts\davinci-agent.exe ping --timeout-seconds 60
```

The timed-out command remains under `runtime\commands` until a later bridge run
rejects it as expired and moves it to `failed`.

## Bridge reports BRIDGE_INITIALIZATION_FAILED

Inspect the safe error in `state\bridge.json` and the structured log in
`logs\bridge.jsonl`. Do not enable external scripting or network access as a
workaround. The M1 bridge must run from inside Resolve.

A direct `DaVinciResolveScript` import may be unavailable even inside a menu
script. The bridge therefore checks the injected internal Resolve/Fusion
context before trying the documented module fallback.
