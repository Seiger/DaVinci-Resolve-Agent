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
Read-only status was live-validated on Resolve 21 Free 21.0.3.7 for the M7
1920x1080 MP4/H.264 job in `Ready` state with zero completion.
M11 subsequently live-validated the guarded start; the capability is persisted
as `true` only after Resolve accepts `StartRendering`.

## M9 verified export profiles

M9 keeps render configuration finite:

```text
resolve_get_render_options
 └─ GetRenderResolutions("MP4", "H264")

resolve_prepare_render_job(custom_name, profile)
 ├─ youtube-1080p-h264-v1 -> YouTube - 1080p -> 1920x1080
 └─ youtube-2160p-h264-v1 -> YouTube - 2160p -> 3840x2160
```

The bridge verifies the built-in preset and exact resolution before
`AddRenderJob`, explicitly applies documented dimensions, and stores the
selected profile in the preparation receipt. M8 start policy derives its
expected preset and dimensions from that receipt. Arbitrary dimensions,
presets, codecs, paths, and upload targets are not representable.

Resolve 21 Free 21.0.3.7 live discovery returned 3840x2160 for MP4/H.264 and
the `YouTube - 2160p` preset. Live write validation then added one matching
3840x2160 job after backup; replay returned the same job and backup without
adding a duplicate or starting rendering.

## M10 safe ranged clip insertion

```text
MCP resolve_insert_clip
 └─ validate IDs, ordered source frames, position, and track
     └─ resolve timeline + media asset
         └─ verify track exists and is unlocked
             └─ backup project
                 └─ AppendToTimeline([{fixed clipInfo}])
                     └─ TimelineItem bounds and track readback
```

The application contract is provider-neutral: `position_frames` is relative
to the timeline start. Only one video-only or audio-only range can be inserted
per command. Existing items are not moved, trimmed, split, disabled,
transformed, or deleted. Stable receipts prevent replay duplicates.

Live validation on Resolve 21 Free 21.0.3.7 inserted source frames 0..240
separately on V1 and A1 at the same position. TimelineItem readback reported
86400..86496 for both, confirming Resolve's 60 fps source to 24 fps timeline
conversion. Replays returned the original item IDs and backups; preflight
remained exactly one video item and one audio item.

## M11 render smoke test

```text
MCP resolve_verify_render_output(job_id)
 └─ documented live render-job status
     └─ require managed TargetDir and safe MP4 filename
         └─ pathlib file existence and non-zero size check
```

M11 uses the guarded M8 start operation against a dedicated 1080p job on the
four-second M10 timeline. Output verification is provider-neutral and
read-only: it reports completion, managed-path membership, existence, and
file size. It does not claim container validity, expected duration, audio
presence, or visual quality because media decoding is outside this milestone.

Resolve 21 Free 21.0.3.7 completed the live smoke job in 3262 ms. The
verification reported `CompletionPercentage=100`, `JobStatus=Complete`, no
render in progress, and a managed non-empty MP4 of 804100 bytes.

## M12 reversible clip enable state

```text
MCP resolve_set_clip_enabled(timeline_id, timeline_item_id, enabled)
 └─ enumerate video/audio TimelineItems by documented unique ID
     └─ verify item methods and unlocked track
         └─ backup project
             └─ SetClipEnabled(bool)
                 └─ GetClipEnabled readback + idempotency receipt
```

The action changes one boolean property only. It cannot address subtitle
items, accept arbitrary property names, move or trim an item, or delete
timeline content. A same-key replay returns the original result and backup.
Resolve 21 Free 21.0.3.7 live validation disabled the M10 V1 item, read back
`enabled=false`, replayed the same receipt and backup without another edit,
then restored the original `enabled=true` state with a separate backup.
Capability `clip.enable` is persisted as `true` only after a successful call.

## M13 safe current timeline selection

```text
MCP resolve_set_current_timeline(timeline_id)
 └─ resolve one existing timeline by documented unique ID
     └─ backup project
         └─ Project.SetCurrentTimeline(timeline)
             └─ GetCurrentTimeline ID readback + idempotency receipt
```

The action cannot accept a timeline name or index, create or delete timelines,
or change timeline settings. Its response contains both the previous timeline
summary and the selected timeline summary. Capability `timeline.select`
is persisted as `true` only after live validation succeeds.
M13 also adds documented unique IDs to read-only timeline discovery; this
closes the selection loop for pre-existing timelines without consulting old
write receipts.

Resolve 21 Free 21.0.3.7 live validation discovered all three timeline IDs,
selected M7 from M10, replayed the same result and backup without another
selection, and restored M10 with a separate backup.
After every successful write, the bridge refreshes its complete live state
before publishing the final heartbeat. This prevents cached project or
timeline metadata from describing the pre-write state.
The control M10 → M7 → M10 round trip confirmed that each cached heartbeat
immediately matched the completed selection without another bridge run.

## M14 bounded clip transform

```text
MCP resolve_set_clip_transform(timeline_id, timeline_item_id, fields)
 └─ validate the fixed provider-neutral transform subset
     └─ resolve one video TimelineItem by documented unique ID
         └─ verify unlocked track and timeline-dependent position bounds
             └─ backup project
                 └─ TimelineItem.SetProperty(fixed dictionary)
                     └─ GetProperty readback + idempotency receipt
```

The external contract exposes only optional position X/Y, uniform zoom,
rotation degrees, and opacity percent, with at least one value required. The
Resolve provider owns the fixed mapping to Pan, Tilt, ZoomGang, ZoomX, ZoomY,
RotationAngle, and Opacity. Clients cannot supply a Resolve property key,
expression, keyframe, or code. Position is additionally bounded against four
times the current timeline resolution.

Resolve 21 Free 21.0.3.7 live validation changed opacity from 100 to 90 with
exact `GetProperty` readback and a project backup. Same-key replay returned
the identical result and backup. A separate command then restored opacity
from 90 to 100 with its own backup. Capability `clip.transform` is persisted
as `true` after the successful call.

## M15 confirmed non-ripple clip deletion

```text
MCP resolve_delete_clip(timeline_id, timeline_item_id, confirm_delete=true)
 └─ destructive MCP annotation + application confirmation
     └─ command safety allow_destructive=true + create_backup=true
         └─ resolve one unlocked video/audio TimelineItem by ID
             └─ backup project
                 └─ Timeline.DeleteClips([item], False)
                     └─ verify item ID is absent + idempotency receipt
```

The public contract cannot express ripple deletion, multiple item IDs, or
linked-item expansion. All non-delete commands remain constrained to
`allow_destructive=false`.

Resolve 21 Free 21.0.3.7 live validation inserted a dedicated 24-frame video
item after the existing M10 content, deleted exactly that item with
`ripple=false`, and confirmed its ID was absent. Same-key replay returned the
identical result and backup. Final read-only preflight returned to one video
item and one audio item, proving the original M10 pair remained. Capability
`clip.delete` is persisted as `true`.

## M16 timeline item discovery

```text
MCP resolve_list_timeline_items(timeline_id)
 └─ validate one bounded timeline ID
     └─ resolve the existing timeline
         └─ enumerate documented video/audio tracks
             └─ validate item IDs, track readback, and frame metadata
                 └─ return provider-neutral item summaries
```

M16 supplies the canonical item IDs needed by enable, transform, and delete
operations without consulting historical write receipts. It is read-only and
does not expose Resolve objects, arbitrary properties, subtitles, or Fusion
state.

Resolve 21 Free 21.0.3.7 live validation discovered the synchronized M10 video
and audio items with distinct canonical IDs. Both reported duration 96,
timeline bounds 86400..86496, and source bounds 0..240. No project backup was
created, and capability `clip.read` was persisted as `true`.

## M17 Media Pool item discovery

```text
MCP resolve_list_media_pool_items()
 └─ require current project and Media Pool root
     └─ recursively enumerate documented folders
         └─ validate folder IDs and guard cycles/size
             └─ read MediaPoolItem ID and name
                 └─ return provider-neutral logical placement
```

M17 supplies Media Pool IDs for append/insert operations without consulting import
receipts. It intentionally omits filesystem paths, raw clip properties,
metadata dictionaries, and Resolve objects. Because documented `GetClipList`
also returns timeline entries in the live project, the provider-neutral
contract does not claim that every result is source media.

Resolve 21 Free 21.0.3.7 live validation discovered five items in the `Master`
folder, including the M10 source MKV with canonical ID
`e2c01761-f786-4b2c-866e-b682d2806eca`. No project backup was created, and
capability `media.read` was persisted as `true`.

## M18 single-run workspace snapshot

```text
CLI/MCP snapshot
 └─ one allowlisted get_workspace_snapshot command
     ├─ bridge and project state
     ├─ timeline list, current timeline, and current items
     ├─ bounded Media Pool item discovery
     └─ render discovery
```

M18 composes only existing read-only bridge functions and fails atomically if
a required section cannot be collected. It accepts no user-defined action
list, creates no backup, performs no write, and keeps the one-shot lifecycle.
The goal is one Resolve menu invocation for a complete diagnostic snapshot,
not an unverified persistent bridge inside the Resolve UI thread.

The local Resolve 21 Scripting README describes external command-line access
as part of the DaVinci Resolve Studio scripting package. Since the supported
target is Resolve 21 Free and direct external import is not available on the
validated machine, the architecture retains the internal menu script.

## M19 bounded clip linking

```text
MCP resolve_set_clips_linked(timeline_id, item_ids, linked)
 └─ validate 2..16 unique canonical IDs
     └─ resolve every video/audio TimelineItem
         └─ reject any locked track
             └─ export project backup
                 └─ SetClipsLinked(items, linked)
                     └─ verify each selected pair with GetLinkedItems()
```

M19 provides explicit synchronization-group control without introducing a
generic timeline mutation surface. Idempotency receipts prevent duplicate
backups on same-key replay. Link and unlink are non-destructive, but still
modify project state and therefore always require a backup.

The local Resolve 21 API does not document direct TimelineItem move, trim, or
split methods. Those specification surfaces remain intentionally unimplemented
instead of being simulated through delete-and-reinsert operations that could
change linking, transitions, effects, or source timing.

## M20 safe timeline duplication

```text
MCP resolve_duplicate_timeline(source_id, new_name)
 └─ resolve source by canonical timeline ID
     └─ reject an existing target name
         └─ export project backup
             └─ Timeline.DuplicateTimeline(new_name)
                 └─ verify distinct ID, exact name, and project membership
```

M20 provides an isolated editing target for future reviewed workflows. It
does not select the duplicate, rename or mutate the source, or infer a name.
Stable idempotency receipts prevent repeated calls from creating additional
copies or backups. The bridge records the current timeline before duplication
and restores it through documented project APIs if Resolve changes selection.

## M21 explicit rough-cut approval

```text
MCP approve_rough_cut(plan_id, confirm_review=true)
 └─ derive plans/<canonical-id>.json
     └─ validate immutable rough-cut draft
         └─ compute canonical SHA-256
             └─ atomically persist separate approval record
                 └─ apply_supported=false
```

M21 keeps planning and review provider-neutral. It never accepts a filesystem
path, never mutates the deterministic draft, and never queues a Resolve
command. Existing approval records are returned idempotently only while their
stored hash matches the current valid draft; post-approval changes are
rejected.

## M22 rough-cut plan inspection

```text
MCP list_rough_cut_plans(limit)
 └─ scan canonical <plan_id>.json files only
     └─ validate draft and optional hash-bound approval
         └─ return bounded summaries without media paths

MCP get_rough_cut_plan(plan_id)
 └─ validate canonical ID, draft, approval, and SHA-256
     └─ return effective review state without writes
```

M22 makes persisted review state discoverable after client or process restarts.
It does not silently skip invalid canonical artifacts: contract or hash
failures are explicit. Unknown non-canonical JSON filenames and approval files
are not treated as plans.

## M23 audio report inspection

```text
MCP list_audio_reports(limit)
 └─ scan canonical <report_id>.json files only
     └─ validate each audio-report contract and filename identity
         └─ return bounded summaries without filesystem paths

MCP get_audio_report(report_id)
 └─ validate canonical ID, report contract, and filename identity
     └─ return the stored before/after report without media processing
```

M23 makes completed audio processing results discoverable after client or
process restarts. Both tools are local and read-only: they do not instantiate
the audio processor, queue a bridge command, or modify an artifact. Invalid
canonical reports fail explicitly; unrelated non-canonical JSON files are
ignored by listing.

## M24 local diagnostics bundle

```text
CLI davinci-agent diagnostics
 └─ load packaged or local config
     ├─ recursively redact known secret-bearing keys
     ├─ replace user-directory prefixes with environment placeholders
     ├─ summarize cached bridge versions and capabilities
     ├─ collect metadata for at most 20 recent failed commands
     └─ collect bounded sanitized excerpts from at most 5 logs
         └─ validate and atomically write diagnostics/*.json
```

The diagnostics service is provider-neutral and never queues a bridge command.
It accepts no output path and does not include media, render outputs, project
backups, raw command arguments, responses, or idempotency keys. Symlinked
runtime files are ignored. Automatic redaction is a safety layer rather than a
guarantee, so documentation requires human review before sharing a bundle.

## M25 filesystem transport audit

```text
FilesystemCommandClient.request(...)
 └─ validate command contract
     └─ atomically create logs/audit/<command_id>.json (submitting)
         └─ atomically publish command envelope
             └─ update audit state (pending)
                 ├─ validated response → success + duration
                 ├─ bridge error → safe error code + retryable
                 ├─ protocol error → BRIDGE_PROTOCOL_ERROR
                 └─ deadline → timeout + COMMAND_TIMEOUT
```

The initial record is mandatory and is written before queue publication. Later
updates are atomic replacements of the same command-scoped record, avoiding
shared JSONL append races between CLI and MCP processes. The record schema has
no fields capable of storing arguments, results, idempotency keys, paths, or
error messages. M25 covers Resolve filesystem transport commands only; local
workflow audit remains a separate application-layer concern.

## M26 local workflow audit

```text
MCP local tool
 └─ AgentApplication._run_local_workflow(operation, callback)
     └─ atomically create logs/workflow/<operation_id>.json (running)
         ├─ callback result → success + duration
         └─ exception → fixed error class + retryable
```

The production MCP composition root injects `WorkflowAuditLog`; tests and
future adapters can inject a compatible auditor or omit it. The allowlist has
exactly seven rough-cut/audio operations. Audit begins before media policy,
artifact validation, processing, or inspection and records no arguments,
artifact IDs, paths, results, or exception messages. Invalid operation names
cannot invoke the callback.

## Future providers

Resolve-specific imports and object handling remain within the Resolve adapter.
An FFmpeg or Premiere provider can implement the same provider-neutral contracts
without changing the agent core.
