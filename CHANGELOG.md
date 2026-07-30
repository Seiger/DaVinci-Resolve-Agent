# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project follows [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added

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
