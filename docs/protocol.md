# M1 filesystem protocol

Protocol version: `1.0`.

The canonical JSON Schemas are under `contracts/`. The bridge performs a
minimal dependency-free validation pass inside Resolve. The M2 external agent
uses Draft 2020-12 validation with date-time format checking before enqueue and
after response receipt.

## Queue layout

```text
runtime/
  commands/
  processing/
  responses/
  failed/
  state/
  logs/
  backups/
```

The external writer creates `commands/<id>.json.tmp` and atomically renames it
to `commands/<id>.json`. The bridge claims a command by moving it to
`processing/`, then writes a response atomically.

Invalid, expired, destructive, or unknown commands receive a structured error
response and are preserved under `failed/`.

Response files are retained as local audit evidence. The external client checks
that the response `command_id` matches the submitted command.

## Canonical examples

M31 packages three inspected fixture catalogs:

- `contracts/examples/commands.json` — one full envelope for each allowlisted
  action;
- `contracts/examples/responses.json` — one success and one error response;
- `contracts/examples/capabilities.json` — boolean, `unknown`,
  `requires_confirmation`, and `requires_studio` values.

Automated tests compare the command catalog with the schema action enum in
both directions, validate every fixture, require unique command/idempotency
IDs, require backup for every write example, and allow the destructive flag
only for confirmed clip deletion.

These are static protocol examples, not executable queue payloads. Their
timestamps expire, paths are illustrative, and IDs do not identify live
Resolve objects. Live commands must be produced by the application service.

M25 also creates one canonical transport audit record under
`logs/audit/<command-id>.json` before publishing the command. The same file is
atomically updated to `pending`, then `success`, `error`, or `timeout`.
It contains only identity, action, safety, timestamps, duration and safe error
classification. Arguments, paths, idempotency keys, responses and error
messages are not representable in the audit schema.

## Additional read actions

- read-only `list_timeline_items` with one existing `timeline_id`;
- read-only `list_media_pool_items` with an empty arguments object;
- read-only `get_workspace_snapshot` with an empty arguments object;

## Write actions

The allowlist additionally contains:

- `import_media` with `paths`;
- `create_timeline` with `name`;
- `ensure_timeline_tracks` with timeline ID and bounded target counts;
- `duplicate_timeline` with source `timeline_id` and a new unique `name`;
- `set_current_timeline` with one existing `timeline_id`;
- `append_clip` with `timeline_id` and `asset_id`;
- `insert_clip` with IDs, source bounds, timeline-relative position, and track;
- `set_clip_enabled` with timeline ID, item ID, and boolean enabled state;
- `set_clips_linked` with timeline ID, bounded unique item IDs, and link state;
- `set_clip_transform` with timeline/item IDs and a bounded transform subset;
- `delete_clip` with one timeline item ID and explicit confirmation;
- `add_marker` with timeline marker fields.
- `prepare_render_job` with `custom_name` and optional allowlisted `profile`.
- `start_render_job` with `job_id`.

Every write envelope must set `create_backup` to `true`. Non-destructive writes
must set `allow_destructive` to `false`; only `delete_clip` must set it to
`true` and also pass `confirm_delete=true`. Write actions use `state/receipts`
to make a stable `idempotency_key` replay-safe. The bridge validates media
paths independently against `state/media-policy.json` before calling Resolve.

`set_current_timeline` resolves the requested ID against the current project,
creates a backup, calls documented `Project.SetCurrentTimeline`, and verifies
the selected object through `GetCurrentTimeline`. It returns both previous and
current timeline summaries. The read-only `list_timelines` and
`get_current_timeline` results expose documented unique IDs so selection never
depends on a name or ordinal index.

`duplicate_timeline` resolves one source timeline by canonical ID, rejects an
existing target name, creates a backup, and calls documented
`Timeline.DuplicateTimeline(name)`. Success requires a distinct non-empty ID,
the exact requested name, and discovery of the returned timeline in the
project list. The action does not select the duplicate or mutate the source.
If Resolve changes the current timeline as a side effect, the bridge restores
the previously selected timeline and verifies it before reporting success.

`ensure_timeline_tracks` resolves one timeline by canonical ID and accepts
only integer video/audio targets from 1 through 8. It creates a project backup,
reads both existing counts, adds only missing tracks, and requires an exact
increment readback after every documented `Timeline.AddTrack` call. Added
audio tracks use the fixed `stereo` subtype. The action cannot remove tracks,
change existing track types, or accept raw Resolve options.

`get_editing_metadata` reads the documented target named settings
`timelineFrameRate`, `timelineResolutionWidth`, and
`timelineResolutionHeight` in addition to bounded track counts and requested
asset `Frames`/`FPS`. It normalizes FPS to a positive float and dimensions to
positive integers, and never returns a raw setting snapshot.

## M38 synchronized pair workflow

`sync_screen_and_webcam` is an application workflow, not a bridge action. It
composes the existing `create_timeline`, `get_editing_metadata`,
`ensure_timeline_tracks`, three `insert_clip` calls, and
`list_timeline_items`. The fixed mapping is screen video V1, screen audio A1,
and webcam video V2. A signed millisecond offset is converted with the live
target timeline FPS; source ranges use each asset's own frame domain.
The documented Resolve example treats `endFrame` as inclusive, so a full
bounded asset range is `0..duration_frames-1`.
Resolve may clamp that request to actual per-stream extents. The workflow keeps
the requested placement separately and treats the bounded TimelineItem
readback as authoritative; it rejects a non-positive or out-of-request range.

Before the first write, the workflow requires verified `timeline.create`,
`timeline.track.create`, `media.metadata.read`, `clip.insert`, and `clip.read`
capabilities. Its SHA-256 receipt stores progress after each primitive. Every
write derives a stable command idempotency key, so a retry resumes pending
steps and a completed retry returns the stored result. It accepts no paths,
raw clipInfo, arbitrary operation list, webcam audio, trim, split, or delete.

## M39 synchronized webcam layout

`compose_webcam_picture_in_picture` is another application workflow rather
than a bridge action. It accepts one applied M38 receipt, a bounded 10–50%
size, normalized 0–100 frame-center coordinates and explicit confirmation.
The application derives Pan/Tilt/Zoom from live target dimensions and invokes
only the existing `set_clip_transform` primitive for the receipt's canonical
webcam item. A SHA-256 layout receipt records the resolution, transform and
exact property readback for stable replay. Raw Resolve properties, crop,
masks, Fusion, keyframes, expressions and arbitrary code remain unavailable.

## M40 synchronized screen link

`link_synchronized_screen_pair` is an application workflow over the existing
documented `set_clips_linked` primitive. It accepts only an applied M38 receipt
and explicit confirmation, recovers exactly the canonical screen V1/A1 IDs,
and requires verified `clip.link` capability. Success requires each selected
item's `GetLinkedItems()` readback to contain the other selected ID. A durable
SHA-256 receipt prevents repeated provider writes. The workflow cannot accept
arbitrary item IDs, infer a track-wide selection, or include webcam V2.

`prepare_render_job` independently rejects paths and invalid Windows filename
characters, derives the output directory from `USERPROFILE`, loads the fixed
YouTube 1080p or 2160p preset, verifies the matching documented MP4/H264
resolution, sets exact `FormatWidth` and `FormatHeight`, and adds one job. Its
response reports `started=false`. Missing `profile` means 1080p for protocol
compatibility; no raw render setting is accepted.
The bridge temporarily opens the documented `deliver` page required by the
official Blackmagic example and then restores the previously active page.

`start_render_job` accepts only one safe `job_id`. Before the documented
`StartRendering([jobId], False)` call, the bridge verifies the M7 preparation
receipt and matching live queue metadata, rejects any existing render process,
creates a project backup, and atomically reserves the job under
`state/render-starts`. The command receipt handles same-key replay; the
per-job record blocks a second start under a different key.

`insert_clip` maps its finite argument object to one documented
`AppendToTimeline([{clipInfo}])` call. The bridge converts `track_type` to
Resolve `mediaType`, derives `recordFrame` as
`Timeline.GetStartFrame() + position_frames`, checks the track exists and is
unlocked, and returns documented TimelineItem source/timeline bounds and track
readback. It does not mutate existing items.

`set_clip_enabled` locates one video/audio TimelineItem by documented unique
ID, verifies its track is unlocked, creates a project backup, calls
`SetClipEnabled(Bool)`, and confirms the exact result with
`GetClipEnabled()`. It cannot address arbitrary properties or execute code.

`set_clips_linked` resolves 2 to 16 unique video/audio TimelineItems, rejects
locked tracks, creates a project backup, and invokes documented
`Timeline.SetClipsLinked([items], Bool)`. It verifies every selected pair
through `TimelineItem.GetLinkedItems()`. The action cannot infer item IDs,
operate on a whole track, or represent undocumented move/trim/split behavior.

`set_clip_transform` locates one video TimelineItem by documented unique ID,
verifies the track is unlocked, and maps provider-neutral position, uniform
zoom, rotation, and opacity fields to a fixed Resolve property dictionary.
It creates a project backup and confirms every written property through
`GetProperty`. Arbitrary Resolve property keys, expressions, keyframes, and
code are not representable.

`delete_clip` locates exactly one video/audio TimelineItem, rejects a locked
track, creates a project backup, and calls documented
`Timeline.DeleteClips([item], False)`. It then enumerates the timeline again to
verify the item ID is absent. Ripple deletion, multiple IDs, and implicit
linked-item expansion are not representable.

`list_timeline_items` resolves a timeline by documented unique ID and
enumerates all video/audio tracks. Each result contains only provider-neutral
identity, track placement, timeline/source frame bounds, and duration. It does
not create a backup or expose arbitrary TimelineItem properties.

`list_media_pool_items` recursively walks the current Media Pool root and
subfolders. It returns bounded provider-neutral identity and logical folder
placement only. The bridge guards folder cycles and rejects discovery beyond
1000 folders or 10000 items. Results may include timeline entries returned by
the documented Folder API; the contract does not infer an undocumented kind.

`get_workspace_snapshot` performs a fixed composition of the existing
read-only operations. It returns bridge metadata, current project, timelines,
current timeline and its items, Media Pool items, and render discovery. It
requires an open project and accepts no action list or other arguments. Failure
of a required section fails the command instead of returning a misleading
partial snapshot.

## M1 action allowlist

- `ping`
- `get_bridge_info`
- `get_capabilities`
- `get_current_project`
- `list_timelines`
- `get_current_timeline`
- `list_timeline_items`
- `list_media_pool_items`
- `get_workspace_snapshot`
- `get_render_environment`
- `get_render_job_status`

`list_timeline_items` accepts only `timeline_id`;
`get_render_job_status` accepts only `job_id`; every other read action accepts
an empty `arguments` object. `allow_destructive` must be `false`. There is no
action for arbitrary batches or for executing Python, Lua, PowerShell, shell
commands, or Resolve expressions.

`get_render_environment` is the read-only M7 discovery action. It returns only
documented formats, codecs, presets, the current format/codec, and existing
queue metadata. M9 adds documented MP4/H264 resolutions. It also reports
current timeline audio/video track and item counts as a render preflight. It
does not change render settings, add a job, start rendering, delete a job, or
upload media.

## Persistent lifecycle

`ResolveBridge` запускається вручну з Resolve та після цього працює як
консервативний persistent loop: один allowlisted command за ітерацію,
heartbeat перед обробкою, інтервал 0.5 секунди та запис state після кожного
кроку. `stop_bridge` не приймає аргументів, не створює backup і не змінює
проєкт: він завершує loop лише після структурованої відповіді `stopping`.
Жодного arbitrary code, shell або Resolve expression цей lifecycle не додає.

Автоматичні тести підтверджують queue, heartbeat state і clean stop у
симуляції. Live acceptance у Resolve 21 Free 21.0.3.7 підтвердив responsive UI,
кілька послідовних команд без повторного menu invocation, metadata readback і
clean stop; це не є доказом сумісності з іншими environments.

M18 reduces a full workspace inspection to one queued command and therefore
one menu invocation. It does not claim zero-click startup: the Resolve 21
documentation installed on the supported machine identifies the external
Scripting API as a Resolve Studio facility, while the supported target is
Resolve 21 Free.

## M2 timeout behavior

The external client writes a command atomically and polls only for the matching
response file. If no response appears before the configured deadline, it raises
a structured timeout and the CLI exits with code `3`. The command remains in
the queue as local evidence and expires according to its envelope.
