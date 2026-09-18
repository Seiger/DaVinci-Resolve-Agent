# Experimental Windows startup launcher

Status: implemented and tested offline with Lua 5.1 API doubles. **Not yet
verified by a cold start of Resolve 21.1 Free on Windows.** Existing editing
acceptance does not prove startup compatibility. Do not interrupt a review or
restart Resolve solely to install this feature.

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
loop synchronously during startup. The worker waits for the configured project
UUID without opening projects, changing pages, seeking or starting playback.
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

To disable future startup, remove only the managed `ResolveAgentStartup.scriptlib`
file. This does not stop an already running bridge; use the normal acknowledged
stop with a saved project open. Retain runtime directories until receipts and
backups are no longer needed. No automatic deletion is performed.

## Live acceptance still required

With review finished: launch once through the helper, open the expected project,
verify ping and identity, close the console and repeat ping. Confirm no change
to the timeline/playhead. Then test an acknowledged stop and a subsequent fresh
application start. Check that a consumed runtime cannot restart and that an
uncertain write blocks migration. Offline tests cover these guard decisions and
worker control flow; only the live test proves the installed Free build loads
the hook and supports the asynchronous context.
