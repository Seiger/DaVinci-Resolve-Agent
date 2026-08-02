# M1 filesystem protocol

## M53 color discovery protocol

`get_color_environment` є fixed read-only action для exact timeline ID. Bridge
читає лише media-backed video items через документовані
`GetCurrentVersion`, `GetVersionNameList`, `GetNodeGraph`, `GetNumNodes`,
`GetNodeLabel` і `GetLUT`. Наявність `SetCDL`, `AddVersion` та
`LoadVersionByName` лише повідомляється; ці методи не викликаються.

CDL values надходять тільки з hash-bound packaged preset у core. MCP/bridge не
приймають довільні CDL, LUT/DRX paths, node indices або executable input.

`apply_color_preset` є внутрішнім fixed write action. Він приймає exact target
timeline, повний bounded список media-video item IDs, allowlisted preset ID та
`confirm_apply=true`; backup обов'язковий. Adapter створює/активує managed local
version і викликає `SetCDL` лише з code-owned map для node 1.

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
- read-only `get_subtitle_environment` with one existing `timeline_id`;
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
- `insert_clips` with one timeline ID and 1 to 3003 bounded placements;
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

## M41 pause compaction preview

`preview_synchronized_pause_compaction` avoids inventing split or trim APIs,
which are absent from the documented Resolve 21 scripting surface. It validates
one approved M5 plan against one applied M38 receipt, checks synchronization
offset and bounded source names, then complements ordered half-open cuts into
kept intervals. Each interval is mapped independently into source frames using
the asset FPS and record frames using target timeline FPS. The canonical
preview contract is bounded to 1000 cuts and 3003 placements, performs no
Resolve write, and reports apply readiness from verified live capabilities.

## M42 pause compaction apply

`apply_synchronized_pause_compaction` requires `confirm_apply=true`, recomputes
the current M41 preview, and rejects a changed approval, source binding,
metadata result, or in-progress preview hash. It creates a new timeline,
ensures V1/A1/V2, and sends all planned ranges through one `insert_clips`
provider operation. The provider maps the fixed placements to the documented
batched `MediaPool.AppendToTimeline([{clipInfo}, ...])` form. It checks every
track and lock state before the backup and write. Returned item IDs, tracks,
source bounds, and a shared timeline origin are checked before a separate
`list_timeline_items` persistence readback. Three step-level keys plus the
provider receipt make replay resumable without editing the source timeline.

## M43 compacted timeline finalization

`finalize_synchronized_pause_compaction` binds applied M42, M39, and M40
receipts to one M38 synchronized pair. The provider-neutral
`set_clip_link_groups` action accepts bounded exact pairs, while
`set_clip_transforms` accepts only the fixed transform allowlist. Each action
creates one project backup for the entire batch. The workflow derives all item
IDs from M42, verifies mutual links and exact Pan/Tilt/Zoom readback, and stores
a resumable finalization receipt; it exposes no arbitrary Resolve property.

## M44 finalized render preparation

`prepare_finalized_timeline_render` loads one applied M43 receipt and derives
the exact target timeline ID. The existing `prepare_render_job` command now
accepts that optional bounded ID; the Resolve adapter selects the documented
timeline before applying the fixed MP4/H.264 settings and `AddRenderJob()`.
The returned timeline identity, profile, dimensions, and `started=false` must
match before the durable M44 receipt becomes applied. Render start remains a
separate guarded operation.

## M45 finalized render execution

The write workflow accepts one applied M44 receipt rather than a caller-chosen
job ID. It compares the live queue job with the stored timeline, preset,
dimensions, codec, output filename, and managed directory, requires `Ready`,
rejects an existing output, and then calls the existing guarded
`start_render_job` once. A separate read-only status workflow verifies the same
identity and uses the canonical managed MP4 validator at every poll.

## M46 finalized audio extraction

The existing `prepare_render_job` command accepts one additional fixed profile,
`audio-only-pcm-wav-v1`. It still accepts no arbitrary settings. The Resolve
adapter loads the built-in `Audio Only` preset and attempts the discovered
`Wave` format with its empty codec identifier. Because Resolve 21 Free may
reject that setter, the newly added queue job is the authoritative readback;
an invalid job is immediately removed with documented `DeleteRenderJob`.
sets only documented `ExportVideo=false`, `ExportAudio=true`,
`AudioBitDepth=16`, and `AudioSampleRate=48000`, and writes below the managed
`audio-sources` directory.

The higher-level prepare/start/status workflow is bound to an applied M43
receipt. Start requires a separate confirmation and remains protected by the
existing provider start record. Status is read-only and requires a completed,
non-empty, uncompressed 16-bit/48 kHz WAV before reporting `passed=true`.

The local `pcm-dialogue-limit-v2` preset processes this WAV in bounded chunks,
applies nominal RMS gain with a deterministic hard limiter, and emits a report
that must satisfy both RMS tolerance and peak ceiling. The versioned v1 peak
guard behavior remains unchanged.

`apply_finalized_timeline_audio` accepts only the extraction receipt, validated
v2 report ID, and confirmation. It derives timeline/item IDs and duration from
the receipts, verifies WAV duration against render `MarkIn`/`MarkOut`, then
uses existing allowlisted primitives to import one asset, ensure A2, insert the
full range, disable source A1 items, and confirm linked video items enabled.
No raw Resolve setting, track, asset, item ID, or filesystem path is accepted
from the MCP caller.

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
readback. It does not mutate existing items. `insert_clips` applies the same
documented mapping to a bounded list with one backup and one
`AppendToTimeline` call for the full batch.

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

`get_subtitle_environment` accepts exactly one canonical `timeline_id`. It
enumerates at most 128 subtitle tracks and 10000 subtitle items through the
documented Timeline API, returning bounded text, canonical item IDs and frame
bounds. It additionally inspects the documented native auto-caption method and
required constants without invoking caption generation. Its `verified=false`
field and `subtitle.auto_caption=unknown` capability distinguish API-surface
presence from confirmed support in Resolve 21 Free.

`create_subtitles_from_audio` requires one canonical `timeline_id`, literal
`confirm_create=true`, `create_backup=true` and an idempotency key. The caller
cannot choose a model, prompt or raw Resolve setting. The bridge uses only the
fixed `AUTO` language, default preset, 42 characters per line, single-line and
zero-gap values. Success requires at least one newly discovered subtitle item;
otherwise the response is a structured error and the capability is not
promoted.

The higher-level `generate_subtitles` MCP workflow accepts only a configured
local source path, canonical timeline ID, literal `confirm_apply=true` and a
bounded timeout. It uses the fixed local transcription policy, writes SRT under
the managed Videos directory, then composes existing `import_media` and
receipt-bound `append_subtitle_file` provider operations. The bridge reports
the pre-write timeline end as `append_frame`; the workflow requires the first
subtitle frame to equal that anchor plus the first transcript offset.
Independent subtitle discovery must find
exactly one new canonical item per transcript segment before a validated
`subtitle-generation` receipt is persisted.

M48 editing recipes are local application contracts, not bridge commands.
`list_editing_recipes`, `get_editing_recipe` and `preview_editing_recipe` are
read-only. `run_editing_recipe` requires literal confirmation and accepts only
a canonical packaged recipe ID plus bounded scalar inputs. The action allowlist
and argument mapping are code-owned; recipe data cannot name an arbitrary MCP
tool, bridge action, provider method, property or executable command. Applied
steps are persisted after each successful underlying idempotent workflow.

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
- `get_subtitle_environment`
- `get_workspace_snapshot`
- `get_render_environment`
- `get_render_job_status`
- `create_subtitles_from_audio`

`list_timeline_items` and `get_subtitle_environment` accept only `timeline_id`;
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

## M49 title and static reframing protocol

`insert_title` is a fixed write action with `timeline_id`, bounded
`title_name`, `timecode` and `confirm_insert=true`. It always requests a project
backup. The Resolve adapter temporarily selects the requested playhead, invokes
documented `InsertTitleIntoTimeline`, restores the previous playhead and returns
canonical item identity plus track/frame readback. It does not accept title
text, Fusion inputs, expressions, scripts or arbitrary properties.

The Resolve adapter accepts this write only for integer-FPS timelines and a
requested absolute non-drop timecode at or after `Timeline.GetEndFrame()`.
Before backup/write it rejects occupied placement. After insertion exactly one
new video item must start at the requested frame and every previous video-item
snapshot must remain unchanged.

Static zoom/reframing reuses `set_clip_transforms`; the high-level visual
treatment remains application orchestration and never becomes executable bridge
data. A SHA-256 receipt binds normalized inputs and persists each completed
operation for replay.

`list_timeline_items` reports `source_type=media` with integer source bounds
for Media Pool clips. A documented generated item such as a standard title has
`source_type=generated` and null source bounds; its timeline bounds remain
mandatory integers. A media-backed item with invalid source bounds still fails
instead of being silently reclassified.

## M52 animation-template protocol

`get_animation_template_environment` є fixed read-only action для exact
timeline. Вона повертає лише presence documented methods, allowlisted template
ID, installed/hash state і readiness — без filesystem path або Fusion graph.

`insert_animation_template` приймає лише exact `timeline_id`,
`template_id=accent-card-v1`, absolute non-drop `timecode` та
`confirm_insert=true`. Adapter перевіряє packaged asset hash до backup,
вимагає timecode рівно на `Timeline.GetEndFrame()`, перевіряє playhead
readback, викликає documented `Timeline.InsertFusionTitleIntoTimeline`, відновлює
playhead і вимагає один новий generated item із Fusion composition. Існуючі
video items мають залишитися еквівалентними bounded snapshot. Arbitrary Fusion
data, code, expressions, controls та external template paths не входять до
protocol.
