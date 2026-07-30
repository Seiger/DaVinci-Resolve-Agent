# Architecture

## M0 foundation

M0 establishes repository tooling and stable extension points:

```text
CLI
 └─ agent (configuration and platform paths)
     ├─ providers (editor capability adapters)
     ├─ transports (local communication adapters)
     └─ bridges (scripts running inside an editor)
```

The core package does not import Resolve modules. Paths are resolved from
platform environment variables at runtime, and packaged defaults contain only
portable placeholders.

## M1 bridge proof

M1 adds a read-only proof inside `bridges/resolve`:

- an internal script visible under `Workspace → Scripts → Edit`;
- the Resolve/Fusion context injected into the internal menu script, with the
  officially documented `DaVinciResolveScript.scriptapp("Resolve")` entry as a
  fallback;
- `ping`, heartbeat, current project name, timelines, and current timeline name;
- capability reporting that leaves untested operations as `unknown`;
- a filesystem transport with an explicit read-only action allowlist.

The initial bridge is one-shot. Each manual invocation observes Resolve,
atomically writes `state/bridge.json`, processes complete commands currently in
`commands/`, and exits. This avoids introducing an unverified polling loop that
could block the Resolve UI.

Live testing on Resolve 21 Free 21.0.3.7 established that the internal host
context works, while importing `DaVinciResolveScript` directly from that menu
script raises `ModuleNotFoundError`. The bridge records failures before retrying
with updated code, so this behavior remains observable rather than implicit.

## M2 external agent

M2 keeps transport mechanics and editor semantics separate:

```text
CLI
 └─ ResolveProviderClient
     └─ FilesystemCommandClient
         ├─ canonical JSON Schema validation
         ├─ atomic command enqueue
         ├─ bounded response wait
         └─ structured protocol/bridge/timeout errors
```

The CLI maps fixed subcommands to provider methods. It does not accept arbitrary
action names. `ResolveProviderClient` validates the shape of action-specific
results, while `FilesystemCommandClient` owns only provider-neutral envelopes
and transport behavior.

```text
ResolveBridge.py
  ├─ documented Resolve read-only API
  ├─ state/bridge.json
  ├─ commands/*.json → processing/*.json
  ├─ responses/*.json
  ├─ failed/*.json
  └─ logs/bridge.jsonl
```

## M3 MCP adapter

M3 adds a local stdio adapter without exposing transport internals:

```text
MCP client
 └─ mcp_server (fixed read-only tools)
     └─ AgentApplication
         └─ ResolveProviderClient
             └─ provider-neutral CommandClient
```

The MCP package does not import `agent.paths`, `transports`, or the Resolve
bridge. It accepts no arbitrary action names and exposes only the four M3 tools
listed in the specification. Blocking application calls run in worker threads
so the MCP event loop remains responsive.

## M4 safe editing

Write requests retain the same boundaries:

```text
MCP write tool
 └─ AgentApplication
     ├─ MediaPolicy (absolute path + allowed root validation)
     └─ ResolveProviderClient
         └─ validated command with create_backup=true
             └─ ResolveBridge
                 ├─ bridge-side media-policy validation
                 ├─ SaveProject + ExportProject
                 ├─ one documented Resolve mutation
                 └─ idempotency receipt
```

The bridge advertises write capabilities as `unknown` until a documented
operation succeeds in the running Resolve edition. Project restore remains an
explicit user action; the bridge never replaces an open project automatically.

Live validation on Resolve 21 Free 21.0.3.7 confirmed `ImportMedia`,
`CreateEmptyTimeline`, `AppendToTimeline`, and timeline `AddMarker`. Replaying
the same four idempotency keys returned the original results without creating
additional backups or duplicate edits.

## M5 rough-cut draft

M5 adds analysis and planning without expanding the Resolve mutation surface:

```text
MCP create_rough_cut
 └─ AgentApplication
     ├─ MediaPolicy (read-only path validation)
     └─ RoughCutPlanner
         ├─ PCM WAV envelope analysis
         ├─ audio-correlation synchronization
         ├─ long-pause detection
         ├─ canonical rough-cut plan validation
         └─ runtime/plans/<plan_id>.json
```

The plan is deterministic for the same inputs and parameters. Its contract
requires `pending_review`, `approved=false`, and `apply_supported=false`.
Neither the Resolve provider nor the bridge is called while creating it.
Video decoding is intentionally outside the core analyzer and remains a future
provider responsibility.

## M6 audio workflow

M6 keeps audio processing outside the Resolve provider:

```text
MCP clean_dialogue_audio
 └─ AgentApplication
     ├─ MediaPolicy (read-only source validation)
     └─ DialogueAudioWorkflow
         └─ PcmWavAudioProvider
             ├─ before analysis
             ├─ deterministic gain + peak guard
             ├─ derived PCM WAV
             └─ canonical before/after report
```

The reference backend supports uncompressed 16-bit PCM WAV and uses no shell
or editor runtime. It measures RMS dBFS rather than claiming standards-compliant
LUFS. Original assets are preserved, derived assets use a durable user video
directory, and reports remain under the local runtime directory.

## M7 delivery discovery

The first M7 slice is read-only:

```text
CLI / MCP resolve_get_render_options
 └─ AgentApplication
     └─ ResolveProviderClient
         └─ get_render_environment command
             └─ ResolveBridge
                 ├─ GetRenderFormats
                 ├─ GetRenderCodecs
                 ├─ GetCurrentRenderFormatAndCodec
                 ├─ GetRenderPresetList
                 └─ GetRenderJobList
```

Successful discovery records `render.discovery=true`, but leaves
`render.configure` and `render.start` unknown. No render setting or queue state
is changed by this slice.

The write slice remains intentionally narrow:

```text
MCP resolve_prepare_render_job
 └─ validate custom_name
     └─ backup project
         └─ fixed YouTube 1080p + MP4/H264 settings
             └─ AddRenderJob
```

The bridge derives the target directory from `USERPROFILE`; clients cannot
provide a path, codec, preset, filter, upload target, or executable command.
Successful preparation verifies `render.configure`, while `render.start`
remains unknown and unavailable.
The bridge temporarily opens the documented Deliver page for `AddRenderJob`
and restores the prior Resolve page afterward.
Live validation on Resolve 21 Free 21.0.3.7 confirmed one 1920x1080 MP4/H.264
job, one mandatory backup, and replay of the stored result without adding a
second job or starting rendering.

## M8 safe render execution

M8 separates status from start:

```text
MCP resolve_get_render_job_status(job_id)
 └─ GetRenderJobList + GetRenderJobStatus + IsRenderingInProgress

MCP resolve_start_render_job(job_id)
 └─ validate M7 preparation receipt
     └─ verify fixed live queue metadata and no active render
         └─ backup project + durable start reservation
             └─ StartRendering([job_id], False)
```

The start action cannot accept a path, preset, codec, upload destination, job
list, or all-jobs flag. A same-key replay returns its stored result; a different
key cannot restart a job with an existing `state/render-starts` record.
`render.start=true` is persisted only after Resolve accepts a live start.
Until that live test succeeds, the capability remains `unknown`.
Read-only status was live-validated on Resolve 21 Free 21.0.3.7 for the M7
1920x1080 MP4/H.264 job in `Ready` state with zero completion.

## Future providers

Resolve-specific imports and object handling remain within the Resolve adapter.
An FFmpeg or Premiere provider can implement the same provider-neutral contracts
without changing the agent core.
