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
