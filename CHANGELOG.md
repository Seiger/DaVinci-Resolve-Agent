# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project follows [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added

- M47 read-only subtitle environment discovery for one canonical timeline,
  including bounded subtitle tracks/items and documented native auto-caption
  method/constant availability without invoking an AI operation.
- MCP `resolve_get_subtitle_environment` with `subtitle.read` capability
  evidence while `subtitle.auto_caption` remains unknown until a successful
  confirmed live write.
- Backup-backed `resolve_create_subtitles_from_audio` with explicit
  confirmation, fixed automatic-language/default-preset policy, idempotency,
  and mandatory bounded subtitle readback.
- Local pinned faster-whisper transcription, deterministic UTF-8 SRT output,
  receipt-bound Resolve import/append workflow, verified append-anchor
  placement, strict canonical-item readback, and a durable M47
  subtitle-generation receipt.
- M46 streaming PCM analysis/processing for multi-gigabyte WAV inputs without
  loading the complete sample array into memory.
- Versioned `pcm-dialogue-limit-v2` preset with deterministic limiting,
  clipping removal, and strict RMS/peak target validation.
- Durable `apply_finalized_timeline_audio` workflow that imports one validated
  report asset, creates A2, inserts the exact extraction range, disables only
  source A1 items, and confirms linked source video remains enabled.
- Resolve 21 Free 21.0.3.7 live validation of a 178906-frame A2 replacement,
  exact source A1 disable readback, preserved V1 enable state, and replay with
  no second write, backup, or duplicate item.
- M46 guarded full-timeline audio extraction with the fixed Resolve `Audio Only`
  preset, managed WAV output, durable prepare/start replay, and strict 16-bit
  48 kHz uncompressed PCM validation.
- MCP prepare/start/status tools for M46 audio extraction bound to one applied
  M43 finalization receipt without exposing arbitrary render settings.
- M45 guarded `start_finalized_timeline_render` workflow bound to one applied
  M44 receipt, explicit confirmation, exact live job preflight, one-start
  durable replay, and no overwrite of an existing managed output.
- Read-only `get_finalized_timeline_render_status` with live queue identity and
  managed non-empty MP4 verification.
- Resolve 21 Free 21.0.3.7 live M45 completion of the exact M44 job at 100%,
  validation of a 2,094,070,933-byte managed MP4, and replay without another
  render start or backup.
- M44 `prepare_finalized_timeline_render` workflow that binds one fixed 1080p
  or 4K MP4/H.264 job to an applied M43 timeline with explicit confirmation,
  durable replay, and no automatic render start.
- Optional explicit `timeline_id` for `prepare_render_job`, with documented
  Resolve timeline selection and timeline identity in the provider readback.
- Resolve 21 Free 21.0.3.7 live M44 preparation of one Ready 1080p MP4/H.264
  job for the exact M43 timeline, one backup, no render start, and replay
  without another job or backup.
- M43 `finalize_synchronized_pause_compaction` workflow that propagates the
  approved M39 webcam PIP and M40 screen links to every M42 segment with two
  bounded backed-up batches, durable replay, and exact readback verification.
- Provider-neutral `set_clip_link_groups` and `set_clip_transforms` commands
  mapped only to documented Resolve timeline-link and item-property APIs.
- Resolve 21 Free 21.0.3.7 live M43 finalization of two screen link groups and
  two webcam PIP segments with six-item identity readback, exactly two new
  backups, and mutation-free replay.
- M42 confirmed `apply_synchronized_pause_compaction` workflow that rebuilds
  approved kept ranges on a new V1/A1/V2 timeline with a durable receipt,
  explicit confirmation, and final canonical-ID readback.
- Bounded `insert_clips` provider command mapped to the documented batched
  `MediaPool.AppendToTimeline([{clipInfo}, ...])` API with one project backup,
  track/lock validation, and idempotent replay.
- Resolve 21 Free 21.0.3.7 live M42 apply with one new timeline, six persisted
  items, three write-step backups, preserved M38 source items, and replay with
  no additional timeline or backup.
- M41 read-only `preview_synchronized_pause_compaction` workflow that converts
  approved millisecond cuts into bounded kept V1/A1/V2 source-frame ranges
  without undocumented split or trim APIs.
- Resolve 21 Free 21.0.3.7 live preview of one 560 ms cut, two kept intervals,
  six planned placements, and no project backup or mutation.
- Unique bridge state temporary files, bounded Windows `PermissionError`
  retries, and deferred heartbeat publication after repeated live `bridge.json`
  replacement sharing violations.
- M40 provider-neutral `link_synchronized_screen_pair` workflow bound to one
  applied M38 receipt, explicit confirmation, mutual canonical-ID readback,
  durable receipt, and stable replay.
- Resolve 21 Free 21.0.3.7 live verification of documented screen V1/A1
  linking, `clip.link=true`, and replay without a second backup.
- M39 provider-neutral `compose_webcam_picture_in_picture` workflow over one
  completed M38 receipt, normalized frame coordinates, bounded 10–50% zoom,
  explicit confirmation, exact Resolve property readback, and durable replay.
- Bounded target timeline width/height discovery through documented named
  `Timeline.GetSetting` calls; no raw settings snapshot is exposed.
- Resolve 21 Free 21.0.3.7 live verification of a 1920×1080 webcam layout with
  exact Pan/Tilt/Zoom readback, one backup, and zero replay writes.
- M38 provider-neutral `sync_screen_and_webcam` workflow for a new V1/A1/V2
  timeline using live target FPS and bounded signed synchronization offset.
- Durable step-level progress receipt, derived primitive idempotency keys,
  capability gate, explicit confirmation, and final TimelineItem readback.
- Privacy-preserving `editing` workflow audit category without asset IDs or
  operation results in audit records.
- Resolve 21 Free 21.0.3.7 live verification of one 24 FPS timeline, exact
  V1/A1/V2 item mapping, five initial backups, and zero replay writes.
- M37 documented target timeline frame-rate discovery in bounded editing
  metadata, without exposing raw timeline settings.
- Resolve 21 Free 21.0.3.7 live verification of a 24 FPS target timeline and
  60 FPS source asset with no backup or project mutation.
- M36 bounded, backup-backed timeline track preparation through documented
  `GetTrackCount` and `AddTrack`, with 1–8 targets and stereo audio additions.
- Exact per-track readback, durable capability evidence, and idempotent replay
  without duplicate tracks or a second backup.
- Resolve 21 Free 21.0.3.7 live verification of a disposable timeline changing
  from 1V/1A to 2V/1A, independent metadata readback, and replay safety.
- M35 manually launched persistent Resolve bridge with bounded polling,
  heartbeat refresh, one allowlisted command per iteration, and clean stop.
- Read-only editing metadata discovery limited to requested asset IDs,
  `Frames`, `FPS`, and target timeline track counts.
- Resolve 21 Free 21.0.3.7 live verification of responsive persistent polling,
  sequential commands, bounded metadata for both synchronized MKV assets, and
  clean MCP stop without project mutation.
- M34 guarded rough-cut apply preview and approved-plan validation with
  timeline-copy targeting, capability blocking, idempotent receipts, and no
  fabricated mapping for unsupported pause removal.
- M33 portable project-scoped Codex MCP configuration with write-tool approval
  and a live end-to-end acceptance procedure.
- Automated validation that the Codex configuration starts the installed STDIO
  server and exposes representative status, Resolve, and render tools.
- Live Codex MCP verification of cached bridge status and current Resolve
  project readback through the one-shot internal bridge.
- M0 repository foundation.
- Python package skeleton and version CLI.
- Windows installation, verification, and uninstallation scripts.
- Default configuration and initial automated tests.
- M1 one-shot internal Resolve bridge with heartbeat and read-only state.
- Allowlisted filesystem queue for `ping` and documented read-only queries.
- CLI bridge status and current-project commands.
- Resolve bridge installation, backup, verification, and restoration behavior.
- Internal Resolve/Fusion context discovery verified on Resolve 21 Free
  21.0.3.7, with a documented module fallback.
- M2 provider-neutral filesystem command client with atomic enqueue and timeout.
- Canonical Draft 2020-12 JSON Schema validation in the external agent.
- Typed Resolve provider client and live CLI commands for ping, bridge info,
  capabilities, project, timelines, and current timeline.
- Stable CLI exit codes for operational errors and timeouts.
- M3 local stdio MCP server over a provider-neutral application service.
- Read-only MCP tools for bridge status, current project, timelines, and current
  timeline.
- MCP client configuration and one-shot bridge usage documentation.
- M4 allowlisted media import, timeline creation, clip append, and marker tools.
- Mandatory `.drp` project exports before write operations.
- External and bridge-side media-root validation.
- Stable idempotency receipts and documented manual rollback strategy.
- Resolve 21 Free 21.0.3.7 live verification of all four M4 write operations
  and replay without duplicate backups.
- M5 provider-neutral PCM WAV synchronization and long-pause analysis.
- Deterministic rough-cut draft plans with a mandatory human review gate.
- Local `create_rough_cut` MCP tool that never applies edits to Resolve.
- Installer-managed runtime plan storage preserved on uninstall by default.
- M6 standard-library 16-bit PCM WAV dialogue analysis.
- Deterministic RMS-level preset with peak guard and preserved source assets.
- Canonical before/after audio reports with target validation.
- Local `clean_dialogue_audio` MCP tool independent from Resolve.
- M7 read-only discovery of documented Resolve render formats, codecs, presets,
  current format/codec, and queued jobs.
- M7 fixed MP4/H264 render-job preparation with backup, idempotency, and a
  durable non-configurable output directory.
- Resolve 21 Free 21.0.3.7 live verification of 1080p render-job preparation,
  queue discovery, backup creation, and idempotent replay without rendering.
- M8 read-only render-job status and guarded start for agent-prepared jobs.
- Durable per-job start records, live queue policy checks, mandatory backup,
  and replay protection before documented Resolve rendering calls.
- Resolve 21 Free 21.0.3.7 live verification of read-only `Ready` job status
  without starting or changing the render queue.
- M9 documented MP4/H.264 resolution discovery and fixed 1080p/2160p YouTube
  export profile allowlist.
- Resolve 21 Free 21.0.3.7 live confirmation of 3840x2160 MP4/H.264 and the
  built-in `YouTube - 2160p` preset without changing the render queue.
- Resolve 21 Free 21.0.3.7 live verification of backup-backed 4K job
  preparation and idempotent replay without duplicate jobs or rendering.
- M10 safe ranged clip insertion with timeline-relative positioning, explicit
  video/audio track selection, project backup, and idempotent replay.
- Documented TimelineItem readback for actual source bounds, timeline bounds,
  and track placement after insertion.
- Resolve 21 Free 21.0.3.7 live verification of synchronized video/audio ranged
  insertion, 60-to-24 fps frame conversion, backups, and duplicate-free replay.
- M11 read-only verification of completed render status, managed MP4 output
  location, file existence, and non-zero size.
- Resolve 21 Free 21.0.3.7 live verification of guarded 1080p render start,
  completion, and the resulting managed non-empty MP4.
- M12 backup-backed TimelineItem enable/disable operation with locked-track
  protection, documented state readback, and idempotent replay.
- Resolve 21 Free 21.0.3.7 live verification of clip disable, duplicate-free
  replay, and restoration of the original enabled state.
- M13 backup-backed current timeline selection by ID with previous/current
  readback and idempotent replay.
- Canonical timeline IDs in read-only timeline list and current-timeline
  responses.
- Resolve 21 Free 21.0.3.7 live verification of timeline ID discovery,
  selection, duplicate-free replay, and restoration of the original timeline.
- Post-write live bridge-state refresh so cached timeline metadata matches the
  completed Resolve operation.
- Live confirmation that selection heartbeats immediately track an M10 to M7
  to M10 round trip without an extra bridge invocation.
- M14 backup-backed bounded transform updates for one unlocked video
  TimelineItem with exact property readback and idempotent replay.
- Provider-neutral position, uniform zoom, rotation, and opacity fields with
  fixed validation and no arbitrary Resolve property access or expressions.
- Resolve 21 Free 21.0.3.7 live verification of opacity write/readback,
  duplicate-free replay, and restoration of the original value.
- M15 confirmed deletion of exactly one TimelineItem through a destructive MCP
  tool, mandatory backup, non-ripple behavior, readback, and replay protection.
- Action-specific destructive safety envelopes that keep every other command
  constrained to `allow_destructive=false`.
- Resolve 21 Free 21.0.3.7 live verification of isolated non-ripple deletion,
  duplicate-free replay, and preservation of the original video/audio pair.
- M16 read-only timeline item discovery with canonical IDs, track placement,
  timeline/source frame bounds, and duration metadata.
- Provider-neutral item addressability for enable, transform, and delete tools
  without reliance on historical write receipts.
- Resolve 21 Free 21.0.3.7 live discovery of synchronized video/audio item IDs
  and matching frame metadata without creating a project backup.
- M17 read-only recursive Media Pool item discovery with canonical item and
  folder IDs plus logical folder paths.
- Bounded folder traversal without raw clip properties, filesystem paths, or
  Resolve object handles.
- Resolve 21 Free 21.0.3.7 live discovery of the M10 source ID among five
  Media Pool items without creating a project backup.
- M18 fixed read-only workspace snapshot for bridge, project, timeline,
  TimelineItem, Media Pool, and render discovery in one bridge command.
- CLI and MCP snapshot entry points without arbitrary batching, project
  backups, persistent polling, or external Resolve scripting assumptions.
- M19 backup-backed link/unlink for 2 to 16 explicitly addressed timeline
  items through documented Resolve link APIs.
- Per-item track-lock validation, link-state readback, and idempotent replay
  without exposing undocumented move, trim, or split operations.
- M20 backup-backed duplication of one explicitly addressed timeline through
  documented `Timeline.DuplicateTimeline`.
- Timeline-name conflict protection, canonical duplicate readback, project
  list verification, and idempotent replay without changing the current timeline.
- M21 explicit local approval for one canonical rough-cut draft with mandatory
  `confirm_review=true`.
- Immutable draft preservation, SHA-256-bound approval records, tamper
  detection, and idempotent replay while plan application remains unsupported.
- M22 read-only rough-cut plan listing and canonical plan-detail retrieval.
- Bounded path-free summaries plus validated approval/hash inspection without
  changing local artifacts or contacting Resolve.
- M23 read-only audio report listing and canonical report-detail retrieval.
- Bounded path-free audio summaries with contract validation and no media
  processing or Resolve bridge call.
- M24 bounded local diagnostics bundles with sanitized configuration, cached
  capabilities, failed-command metadata, log excerpts, and version data.
- Fixed managed diagnostics output with no media, backups, raw queue payloads,
  arbitrary output paths, or Resolve bridge invocation.
- M25 canonical per-command filesystem transport audit records.
- Atomic submitting, pending, success, error, and timeout states without
  arguments, media paths, idempotency keys, response payloads, or messages.
- M26 application-level audit for seven local rough-cut and audio operations.
- Atomic workflow lifecycle records with fixed error classification and no
  arguments, artifact IDs, paths, results, contents, or exception messages.
- M27 GitHub Actions Windows test matrix for Python 3.10, 3.11, and 3.12.
- Read-only CI quality checks for Ruff, mypy, installed CLI, and installer
  PowerShell syntax without Resolve, secrets, deployment, commit, or push.
- Bounded retry for transient Windows `PermissionError` during atomic audit
  replacement and simulated command/response publication.
- M28 isolated Windows installer lifecycle smoke test.
- Repeat-install configuration preservation, previous-bridge backup/restore,
  fixed-scope uninstall, and out-of-scope sentinel verification in CI.
- M29 explicit offline installer verification without a fabricated Resolve
  heartbeat.
- Machine-local TOML validation and write/delete permission probes for every
  installer-managed application directory.
- M30 canonical manual Resolve integration platform and state matrices.
- Evidence requirements that separate verified live runs, pending coverage,
  automated CI, stale cached state, and operator-confirmed edition.
- M31 packaged canonical command, response, and capability examples.
- Exact automated coverage of every allowlisted action with schema-validated
  envelopes and safety invariants.
- M32 isolated Windows wheel build, boundary inspection, and non-editable
  installation verification.
- Wheel metadata, console entry-point, safe archive-path, packaged-resource,
  and repository-only content checks without publication or upload.
