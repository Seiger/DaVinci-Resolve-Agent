# Experimental Windows startup launcher

Status: implemented and tested offline with Lua 5.1 API doubles, but the
**2026-09-18 cold-start acceptance on Resolve 21.1 Free / Windows failed**.
The launcher started Resolve and installed the configured hook. More than 180
seconds after the application main loop started, it remained in Project Manager;
there was no consumed-session export and two MCP pings timed out. No manual
project opening or Lua bootstrap was substituted. Project, timeline and page
readback therefore remain unverified.

The installed folder matches the scripting documentation and local path map.
A subsequently supplied Lua console screenshot **confirmed the hook and worker
executed** and stopped at `Another project is open; automatic switching refused`.
A diagnostic after manual opening read the expected UUID, Edit page and expected
timeline. That later state does not identify the project seen at startup.
Fusion initialization warnings do not explain this refusal.
This is an experimental candidate, **not a working automatic-start guarantee**.
Existing editing acceptance does not prove startup compatibility. Do not interrupt
a review or restart Resolve solely to install this feature.

## Evidence and choice

The installed Resolve 21.1 scripting README lists internal console/menu/render
and composition scripts. Scanning a Scripts folder at startup populates menus;
it does not itself establish that ordinary `.lua` files execute automatically.
The local bundled Python external-API probe returned no Resolve object.

Blackmagic's [Fusion scripting guide, Script Libraries](https://documents.blackmagicdesign.com/UserManuals/Fusion8_Scripting_Guide.pdf)
documents root `Scripts:` `.scriptlib` loading. This is Fusion documentation,
not a guarantee for every Resolve edition. The primary
[AutoSubs startup implementation](https://github.com/tmoroney/auto-subs/blob/main/AutoSubs-App/src-tauri/resources/AutoSubs.scriptlib)
uses that hook and `fusion:Execute()` to dispatch asynchronously; its
[bootstrap](https://github.com/tmoroney/auto-subs/blob/main/AutoSubs-App/src-tauri/resources/modules/bootstrap.lua)
describes the Resolve 21.1 Free Lua sandbox. These support trying this route,
but local live acceptance remains necessary.

Our hook dispatches only a locally generated worker. It never runs the resident
loop synchronously during startup. By default it waits for the configured project
UUID without opening projects. Explicit `--project-name` enables loading the
existing named project. Neither mode changes pages, seeks or starts playback.
No arbitrary script argument, network listener, scheduled task, service or
keyboard/mouse automation is introduced.

## Prepare, then launch

Run from the repository's Python environment. Supply a previous runtime whose
receipts have been reconciled. Preparation only writes a fresh staging folder:

```powershell
python -m providers.resolve.lua_launcher --base G:/ResolveAgentStartup --previous-runtime G:/PreviousRuntime --project-id PROJECT_UUID --media-root G:/ApprovedMedia
```

After the user finishes reviewing and closes Resolve, repeat with `--launch`.
That explicit option installs **one** file,
`%APPDATA%/Blackmagic Design/DaVinci Resolve/Support/Fusion/Scripts/ResolveAgentStartup.scriptlib`,
and opens the installed Resolve.exe. A custom `--executable` must name Resolve.exe.
Existing unmanaged files at that hook path are never overwritten.

To open an existing project automatically, supply both `--project-name` with its
exact name and `--project-id` with its known UUID. `LoadProject(name)` is documented
in the installed 21.1 `DaVinciResolveScript.pyi`. The worker requires exactly one
matching name in the **current Project Manager folder**; it never searches or
switches databases/folders, creates, imports or deletes projects. If any other
project is already open, it refuses to switch even if that project is saved.
It rechecks immediately before loading and verifies both the returned and current
project UUID afterward. On mismatch it stops before exporting/starting the bridge;
the incorrectly matched project may already be open, because this API cannot
query an unopened project's UUID. It never saves or edits that project.

Readiness polling is bounded by `--ready-timeout-seconds` (default 180, range
1–600). This timeout is for startup only, not the persistent bridge lifetime.
Missing/ambiguous names, load failure and identity mismatch fail closed without
retries. Whether this Free build exposes the Project Manager to an asynchronous
startup hook before a project is open remains a **live acceptance requirement**.
Adding `LoadProject` does not solve a missing/non-executing hook by itself.

The Python CLI works without PowerShell script execution. If `.ps1` launchers are
blocked by Windows ExecutionPolicy, invoke the Python command directly or use a
local `.cmd` wrapper invoking Python with a saved argument file. Do not change
machine/user policy or silently introduce console keystrokes as a fallback.

**Use this launcher for subsequent starts.** It generates a fresh random session
token and directory each time. Read `<base>/active.json` for the runtime to pass
to `mcp_server.lua_experimental --runtime ...`; this file is a locator, not proof
of connection. Confirm MCP ping and project readback after opening the target
project. Startup waiting itself does not export or save the project. Once the
target opens, one local DRP export records that this runtime has been consumed.
Ordinary starts with the old installed hook cannot reuse a consumed session.

## Safety and lifecycle

- The launcher refuses to run while Resolve.exe exists. Its exclusive lock
  serializes launcher instances; a stale lock requires explicit reconciliation.
- Previous pending/unknown receipt states, malformed receipts, and client locks
  block rotation. Old backups, receipts and media are preserved. Successful
  results are not automatically replayed in a new runtime.
- Startup uses a shared Fusion preference claim and an invocation guard to avoid
  duplicate dispatch. The session's consumed DRP marker prevents restarting it
  after loss of the in-memory replay set. It is not a playback/render artifact.
- Do not concurrently start Resolve by another route, or manually bootstrap a
  second bridge in another scripting context. No forced takeover is attempted.
- Once running, the bridge has no lifetime cutoff. Closing/reopening the MCP
  client retains the running Lua session. Acknowledged stop, Lua error or Resolve
  exit ends it; errors do not trigger an automatic restart or write replay.
- Startup error messages go to the Lua console. If the hook never loads, a
  missing ping is inconclusive: inspect startup diagnostics rather than adding
  GUI automation. Do not mark startup verified on the strength of unit tests.
- A foreign-project refusal now emits `STARTUP_PROJECT_CONFLICT` with the actual
  name, UUID and its type, current page/folder, timeline count and exact-name match
  counts at the time of refusal. It attempts to save `startup-conflict.txt` in the
  private runtime only when `io.open` is available; restricted Lua contexts print
  `STARTUP_CONFLICT_FILE_SAVED=false` and require copying the console output.
  No project is exported, saved, closed or switched for this diagnostic. Even an
  empty project named `Untitled Project` remains protected: that name alone is
  not proof it is a disposable startup placeholder. Keep diagnostics private.

To disable future startup, remove only the managed `ResolveAgentStartup.scriptlib`
file. This does not stop an already running bridge; use the normal acknowledged
stop with a saved project open. Retain runtime directories until receipts and
backups are no longer needed. No automatic deletion is performed.

## Live acceptance still required

With review finished: launch once through the helper, open the expected project,
verify ping and identity, close the console and repeat ping. With explicit project
selection, first verify that the existing project opens automatically. Confirm no change
to the timeline/playhead. Then test an acknowledged stop and a subsequent fresh
application start. Check that a consumed runtime cannot restart and that an
uncertain write blocks migration. Offline tests cover these guard decisions and
worker control flow; only the live test proves the installed Free build loads
the hook and supports the asynchronous context.
