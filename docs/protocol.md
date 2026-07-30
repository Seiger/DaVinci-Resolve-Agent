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

## Write actions

The allowlist additionally contains:

- `import_media` with `paths`;
- `create_timeline` with `name`;
- `append_clip` with `timeline_id` and `asset_id`;
- `insert_clip` with IDs, source bounds, timeline-relative position, and track;
- `set_clip_enabled` with timeline ID, item ID, and boolean enabled state;
- `add_marker` with timeline marker fields.
- `prepare_render_job` with `custom_name` and optional allowlisted `profile`.
- `start_render_job` with `job_id`.

Every write envelope must set `allow_destructive` to `false` and
`create_backup` to `true`. Write actions use `state/receipts` to make a stable
`idempotency_key` replay-safe. The bridge validates media paths independently
against `state/media-policy.json` before calling Resolve.

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

## M1 action allowlist

- `ping`
- `get_bridge_info`
- `get_capabilities`
- `get_current_project`
- `list_timelines`
- `get_current_timeline`
- `get_render_environment`
- `get_render_job_status`

All actions except `get_render_job_status` accept an empty `arguments` object;
status accepts only `job_id`. `allow_destructive` must be `false`. There is no
action for executing Python, Lua, PowerShell, shell commands, or Resolve
expressions.

`get_render_environment` is the read-only M7 discovery action. It returns only
documented formats, codecs, presets, the current format/codec, and existing
queue metadata. M9 adds documented MP4/H264 resolutions. It also reports
current timeline audio/video track and item counts as a render preflight. It
does not change render settings, add a job, start rendering, delete a job, or
upload media.

## One-shot lifecycle

M1 does not continuously poll. Invoke `ResolveBridge` from Resolve to capture a
fresh state and process commands already present in the queue. Persistent
polling requires a separate UI-blocking safety proof.

## M2 timeout behavior

The external client writes a command atomically and polls only for the matching
response file. If no response appears before the configured deadline, it raises
a structured timeout and the CLI exits with code `3`. The command remains in
the queue as local evidence and expires according to its envelope.
