# Experimental Lua MCP bridge (Resolve Free 21.1)

This is an opt-in **prototype**, separate from the Python bridge. Protocol 3
adds bounded finishing and render operations to the three protocol-2 edits.
It does not replace the production MCP server or expose its entire surface.
The protocol-2 edits were validated on Windows 10 build 19045, Resolve Free
21.1.0.17, Python 3.12.10. **Protocol-3 finishing and closed-console operation
are not yet live-verified.** Do not treat this revision as ready for unattended
production rendering; see the acceptance section below.

After one bootstrap inside Resolve, requests use a local mailbox. No keyboard,
mouse, window activation, screenshots, desktop automation or network connection
is used by the MCP server or Lua request loop.

## Setup from a checkout

Choose a new private local directory for each session (not a shared folder).
From the repository root:

```powershell
.\.venv\Scripts\python.exe -m mcp_server.lua_experimental --runtime C:/ResolveAgentLua/session1 --prepare --media-root C:/Users/YourName/Videos
```

Open a **saved project** in Resolve. In Workspace → Console, choose Lua and run
the generated script once:

```lua
dofile("C:/ResolveAgentLua/session1/bridge.lua")
```

Configure an optional MCP server with the repository as its working directory:

```toml
[mcp_servers.davinci-resolve-lua-experimental]
command = ".venv/Scripts/python.exe"
args = ["-m", "mcp_server.lua_experimental", "--runtime", "C:/ResolveAgentLua/session1"]
startup_timeout_sec = 20
tool_timeout_sec = 150
required = false
```

Repeat `--media-root` for additional approved media directories. Without media
roots, importing/appending files is disabled. Roots are fixed in both the session
manifest and the installed Lua script; use a new session to change them. Old
protocol-1 sessions remain read-only and need a fresh preparation for editing.
Protocol-2 sessions cannot use finishing commands; prepare a new runtime.

These tools are advertised:

- `resolve_lua_ping`: fresh round-trip, requires an open project.
- `resolve_lua_get_project`: project name and ID from a fresh DRP export.
- `resolve_lua_stop`: acknowledge via export, then stop the Lua loop.
- `resolve_lua_import_media`: import 1–20 local media files into the current
  Media Pool folder, rejecting files already present in the pool.
- `resolve_lua_create_timeline`: create an empty timeline with a unique exact
  name and the project's current defaults.
- `resolve_lua_append_clip`: append already imported media to one uniquely
  named timeline, either whole or with both source frame bounds supplied.
- `resolve_lua_set_clip_properties`: set and read back clip audio gain, or
  video zoom, position and opacity. Uses one-based track/item indices and
  requires the expected source path. This is not noise removal or automatic mixing.
- `resolve_lua_add_subtitles`: import UTF-8 SRT within a media root, reject
  overlapping cues or existing timeline subtitles, verify cue count and first/
  last timing. This provides captions, not arbitrary designed title templates.
- `resolve_lua_prepare_render`: queue a 1080p H.264 MP4 using the installed
  `YouTube - 1080p` preset, with audio and burnt-in subtitles. Creates a new
  `renders/<request>/video.mp4` destination, never overwrites an existing video.
- `resolve_lua_start_render`: start only a job prepared by this running bridge.
  Acknowledges start, not completion. A stopped/restarted Lua loop loses job ownership.
  Rechecks the queued job's timeline/destination and refuses a non-empty output
  directory. A successful replay returns its receipt without starting again.
- `resolve_lua_get_render_status`: poll that owned job. A completed status also
  requires a non-empty output whose first video frame and first audio frame
  (when an audio stream exists) decode successfully.
  This is not a full visual/audio quality inspection.
- `resolve_lua_cleanup_responses`: preview eligible response files by default;
  `confirm=true` removes them only after an acknowledged stop, with no pending
  writes. Keeps every backup, render, receipt, script and unrelated file.

## Editing safety and replay

Each edit requires `expected_project_id` from `resolve_lua_get_project`, explicit
`confirm=true`, and a stable `idempotency_key`. Names are exact; ambiguous assets
or timelines are rejected. Media paths are normalized, checked for existence
and confined to approved session roots. No arbitrary source code is accepted.

Before the editing API call, Lua checks the open project and rendering state,
saves it, and exports `<request>.before.drp`. Failed backup blocks the edit.
Afterward Lua verifies creation/import/new timeline-item IDs and source identity,
saves the project, and exports `<request>.ok.drp`. Render start skips the post-save
while rendering; preparation saves before starting the job. The client validates response
and backup project IDs before recording success.

Append selects the named timeline, adding to its end; it does not insert,
overwrite or delete existing clips. `start_frame` and `end_frame` map to the
Resolve API's inclusive source-frame bounds, not timeline frames. Converted
duration depends on source/timeline frame rates. Both must be provided or both
omitted. Source range must fit the imported clip's reported frame count.

Successful receipts survive MCP client restarts in the **same session directory**.
Reusing the same key/arguments returns the recorded result without resubmission;
reusing a key with different arguments is rejected. This is not global
deduplication across newly prepared session directories.

A timeout, failed post-check/save, or missing response can mean a partial edit.
Its receipt stays `pending`, blocking all further writes in that session. Read
tools and stop remain usable. Do not create a new key/session to bypass this:
inspect the project and retained backup first. Known preflight failures are
recorded as `rejected`. There is no automatic rollback or uncertain-write replay.

The loop automatically stops after approximately two hours (an in-progress
Resolve API call can extend this). After an acknowledged stop, prepare a new
session directory before restarting; the client refuses reuse of stopped sessions.
Stop the old loop before switching runtime directories. No auto-start
or unattended restart is implemented.

This lifetime is a bridge limit, not a Resolve restriction. It starts when the
Lua script starts, rather than resetting after each request. The stop command
can end it earlier. Previously prepared runtime directories retain their copied
script: prepare a new runtime to use the two-hour limit.

## Protocol and limits

The Python client publishes one atomically replaced `request.lua`, with a
random request ID, session token, fixed action and expiry. All string values
are byte-escaped literals. Tools accept no Lua source or arbitrary action.
The local mailbox is **trusted executable input**: do not edit it or permit
untrusted programs/users to write there. This prototype is not a sandbox or
an authenticated multi-user service.

Lua polls with `dofile` and `bmd.wait`; the injected global `resolve` provides
API access. `Resolve()` and `bmd.scriptapp("Resolve")` returned nil in our
console test. Normal `io`, `require`, `package`, and UIManager were unavailable.

Each response exports the current project under its unique request ID. The
client waits for a complete ZIP and reads only the bounded identity header of
`project.xml`; no archive members are extracted. Later Resolve configuration
elements are not standard XML, so the full project graph is not parsed.
This export layout is version-specific and is not a stable public API.

Exports can be large/slow. Responses above 512 MiB or identity XML above
16 MiB are rejected. They remain locally for diagnosis and may contain private
project metadata. No source media is included. Response cleanup is explicit,
never automatic. Backups and final videos still consume disk space and require
a separate retention decision. A new directory is created per render, not per
editing command. Do not remove an entire session unless its backups/renders
are no longer needed. A crashed client can leave `client.lock`;
remove it only after confirming no client owns the session.

Read-only tools do not call SaveProject or modify project contents. Editing
tools save and export before/after the mutation. General effects, deletion,
track layout, transitions and the production rough-cut workflows are not
connected to this bridge. Read-only exported state may differ from unsaved UI
edits. A missing project, failed export or stopped loop yields a timeout. Fixed
editing error codes use separately correlated DRP filenames. Render preparation
returns a bounded job-ID token in the response filename; status uses a fixed
allowlist of tokens. There is no
heartbeat or general-purpose result channel.
Concurrent requests are rejected instead of overwriting another request.
On Windows, a reader can briefly block atomic mailbox replacement. Publication
retries within the request deadline using the same request ID and payload; it
never generates or replays a new editing operation.

## Live acceptance, 2026-09-17

The initial read-only MCP stdio handshake advertised three tools.
`ping → get_project → ping` returned pong, the expected open project's name/ID,
and pong through three separately correlated exports. No GUI input occurred
between these calls. MCP stop returned `stopping`; a subsequent ping timed out,
confirming that the loop no longer served requests. The earlier bounded diagnostic also served two separately
published canary requests after one launch.

The protocol-2 editing acceptance test used an existing disposable test project
and a locally generated 48-frame, 24 fps video. A wrong-project edit was rejected
with `PROJECT_CHANGED` before mutation. Import, empty-timeline creation and a
trimmed append (source frames 12–35) all completed through MCP. Each repeated
request returned `replayed=true`; there were exactly three baseline backups.
Independent inspection of the exported timeline found one video item, source
in-point 12, and timeline duration field 23. Frame-rate conversion was not
independently measured.
This verifies creation and no duplicate append; it does not independently prove
every frame-rate conversion or the source end-frame readback. Whole-clip append,
audio-only and mixed audio/video fixtures have not yet been live-tested in this
Lua adapter. The loop was stopped after testing.

Protocol-3 finishing is implemented and has automated validation/transport tests,
but its live acceptance remains pending. A local synthetic three-second video
with stereo tone and an SRT caption is prepared for the full check. Console
access failed twice while reporting that the foreground window had no process
ID; no finishing command was submitted to Resolve in this attempt. Required
remaining acceptance: bootstrap, close the console, import mixed AV, append,
change gain/framing, add captions, prepare/start/poll render, inspect the output,
then stop and preview response cleanup. The two-hour boundary has not been
wall-clock tested.

This does not verify general editing, no-project startup, every Resolve version, or application focus
behavior under every concurrent user activity. See the manual integration
matrix for the exact scope of the earlier console project-creation test.
