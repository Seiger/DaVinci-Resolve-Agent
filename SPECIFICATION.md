# DaVinci Resolve Agent — Technical Specification

**Status:** Draft  
**Version:** 0.1.0  
**Working name:** DaVinci Resolve Agent  
**Primary use case:** repeatable AI-assisted video editing workflow with DaVinci Resolve, initially targeting Windows and DaVinci Resolve 21 Free.

---

## 1. Purpose

DaVinci Resolve Agent is an extensible local automation framework that allows an AI client, CLI, or MCP client to inspect and modify video-editing projects through interchangeable providers.

The first provider targets DaVinci Resolve 21 Free by running a bridge script inside Resolve and exchanging structured commands with an external local agent.

The system must be reproducible on another computer through a documented installation process and must not depend on machine-specific absolute paths.

Resolve Free 21.1 compatibility experiment: a separate, opt-in Lua MCP server
exposes ping, exported project identity, stop, and guarded import/create-timeline/
append operations. It uses a
trusted generated local Lua mailbox and DRP snapshots, without desktop input
after one in-Resolve bootstrap. This does not replace the production protocol
or expose the full editing surface. Writes require project identity, confirmation,
pre-edit saved backups and session-scoped durable receipts. Uncertain writes block
resubmission. The prototype requires an open saved project, expires
after two hours, and retains local response exports for diagnostics. See
[Lua prototype limits and setup](docs/lua-experimental.md).

Protocol 3 additionally implements bounded gain/framing, SRT captions, owned
render-job preparation/start/status and explicit stopped-session response cleanup.
These finishing operations are not yet live-verified. Cleanup preserves backups,
renders and receipts and refuses pending writes. Full production-provider parity,
automatic bootstrap and general effects are outside this experimental surface.

---

## 2. Goals

### 2.1 Initial goals

1. Verify that DaVinci Resolve 21 Free can execute the internal bridge script.
2. Establish reliable bidirectional communication between the external agent and the Resolve bridge.
3. Expose a small, safe command set:
   - health check;
   - current project information;
   - current timeline information;
   - media import;
   - timeline creation;
   - clip insertion;
   - marker creation;
   - render-job preparation.
4. Provide an MCP server exposing these capabilities to compatible AI clients.
5. Make installation repeatable on Windows through PowerShell scripts.
6. Keep the core independent from DaVinci Resolve so additional providers can be added later.

### 2.2 Long-term goals

- silence and pause detection;
- transcript-based editing;
- automatic rough cuts;
- synchronized screen and webcam tracks;
- automated reframing and zooms;
- subtitles and animated captions;
- reusable title templates;
- audio cleanup and loudness normalization;
- color presets;
- automatic quality-control checks;
- export presets for YouTube and other destinations;
- Premiere Pro and FFmpeg providers;
- reusable editing recipes and user-specific style profiles.

---

## 3. Non-goals for the first milestone

The first milestone will not attempt to:

- fully automate creative editing;
- control every Resolve feature;
- manipulate Fusion compositions;
- perform advanced Fairlight mixing;
- guarantee compatibility with all Resolve versions;
- depend on undocumented network access inside Resolve;
- expose destructive actions without explicit safeguards;
- upload videos or communicate with cloud services.

---

## 4. Design principles

### 4.1 Provider independence

The agent core must not contain DaVinci-specific business logic. Editing operations are expressed through provider-neutral interfaces.

### 4.2 Local-first operation

All commands, project metadata, temporary files, and logs remain local unless the user explicitly configures an external service.

### 4.3 Repeatable installation

A clean Windows machine should be configurable with:

```powershell
git clone <repository-url>
cd DaVinci-Resolve-Agent
.\installer\install.ps1
.\installer\verify.ps1
```

### 4.4 Safe by default

- Read-only operations are enabled first.
- Destructive operations require explicit flags.
- Project backups or snapshots are created before major changes where possible.
- Every command has an idempotency key.
- Every response includes structured success or error information.

### 4.5 Observable behavior

Every command must produce logs and a machine-readable result. Silent failures are not acceptable.

### 4.6 Progressive capability detection

The bridge must report which operations are actually available in the detected Resolve edition and version. Unsupported operations must fail clearly instead of being guessed.

---

## 5. High-level architecture

```text
┌────────────────────────────┐
│ AI client / Codex / Claude │
└──────────────┬─────────────┘
               │ MCP or CLI
┌──────────────▼─────────────┐
│ Agent API / MCP Server     │
│ Validation and orchestration│
└──────────────┬─────────────┘
               │ Provider-neutral commands
┌──────────────▼─────────────┐
│ Provider Layer             │
│ Resolve / FFmpeg / Premiere│
└──────────────┬─────────────┘
               │ Local transport
┌──────────────▼─────────────┐
│ Resolve Bridge             │
│ Runs inside DaVinci Resolve│
└──────────────┬─────────────┘
               │ Resolve scripting context
┌──────────────▼─────────────┐
│ DaVinci Resolve Project    │
└────────────────────────────┘
```

---

## 6. Proposed repository structure

```text
DaVinci-Resolve-Agent/
├── agent/
│   ├── __init__.py
│   ├── application.py
│   ├── config.py
│   ├── errors.py
│   ├── logging.py
│   ├── models/
│   ├── services/
│   └── workflows/
├── bridges/
│   └── resolve/
│       ├── ResolveBridge.py
│       ├── dispatcher.py
│       ├── capabilities.py
│       └── handlers/
├── providers/
│   ├── base.py
│   ├── resolve/
│   ├── ffmpeg/
│   └── premiere/
├── transports/
│   ├── base.py
│   ├── filesystem.py
│   └── local_http.py
├── mcp_server/
│   ├── server.py
│   └── tools/
├── cli/
│   └── main.py
├── contracts/
│   ├── command.schema.json
│   ├── response.schema.json
│   └── capability.schema.json
├── config/
│   ├── default.toml
│   └── logging.toml
├── installer/
│   ├── install.ps1
│   ├── uninstall.ps1
│   ├── verify.ps1
│   └── common.ps1
├── tests/
│   ├── unit/
│   ├── integration/
│   └── fixtures/
├── docs/
│   ├── architecture.md
│   ├── protocol.md
│   ├── installation-windows.md
│   └── troubleshooting.md
├── scripts/
├── pyproject.toml
├── README.md
├── SPECIFICATION.md
├── CHANGELOG.md
├── CONTRIBUTING.md
└── LICENSE
```

---

## 7. Core domain model

### 7.1 Project

```json
{
  "id": "provider-specific-id",
  "name": "Example Project",
  "provider": "resolve",
  "timeline_count": 1,
  "current_timeline_id": "timeline-1"
}
```

### 7.2 Timeline

```json
{
  "id": "timeline-1",
  "name": "Main Timeline",
  "frame_rate": 60,
  "resolution": {
    "width": 2560,
    "height": 1440
  },
  "duration_frames": 0
}
```

### 7.3 Media asset

```json
{
  "id": "asset-1",
  "path": "G:/Videos/screen.mkv",
  "kind": "video",
  "has_audio": true,
  "metadata": {
    "width": 2560,
    "height": 1440,
    "frame_rate": 60
  }
}
```

### 7.4 Edit operation

```json
{
  "operation": "insert_clip",
  "timeline_id": "timeline-1",
  "asset_id": "asset-1",
  "track": {
    "type": "video",
    "index": 1
  },
  "position_frames": 0
}
```

### 7.5 Editing recipe

A recipe is a declarative description of a reusable editing workflow.

```yaml
name: tutorial-rough-cut
version: 1
steps:
  - action: import_media
    inputs:
      screen: "{{screen_file}}"
      webcam: "{{webcam_file}}"
  - action: create_timeline
    name: "{{project_name}} — Rough Cut"
  - action: sync_media
    strategy: audio
  - action: detect_pauses
    min_duration_ms: 700
  - action: remove_pauses
    preserve_context_ms: 120
  - action: normalize_audio
    target_lufs: -14
```

---

## 8. Command protocol

### 8.1 Command envelope

```json
{
  "protocol_version": "1.0",
  "command_id": "uuid",
  "idempotency_key": "uuid-or-stable-key",
  "created_at": "2026-07-30T12:00:00Z",
  "expires_at": "2026-07-30T12:05:00Z",
  "provider": "resolve",
  "action": "get_current_project",
  "arguments": {},
  "safety": {
    "allow_destructive": false,
    "create_backup": true
  }
}
```

### 8.2 Response envelope

```json
{
  "protocol_version": "1.0",
  "command_id": "uuid",
  "status": "success",
  "started_at": "2026-07-30T12:00:01Z",
  "finished_at": "2026-07-30T12:00:01Z",
  "result": {},
  "error": null,
  "warnings": []
}
```

### 8.3 Error envelope

```json
{
  "code": "UNSUPPORTED_CAPABILITY",
  "message": "The current Resolve edition does not expose this operation.",
  "details": {
    "action": "create_render_job"
  },
  "retryable": false
}
```

---

## 9. Initial transport

The first implementation should use a filesystem queue because it is:

- simple to debug;
- compatible with an in-application script;
- independent of firewall configuration;
- easy to inspect manually;
- suitable for proving the bridge concept.

### 9.1 Runtime directory

Default Windows runtime directory:

```text
%LOCALAPPDATA%\DaVinciResolveAgent\runtime\
```

Layout:

```text
runtime/
├── commands/
├── processing/
├── responses/
├── failed/
├── state/
└── logs/
```

### 9.2 Processing sequence

1. Agent validates a command.
2. Agent writes it atomically to `commands/<command-id>.json.tmp`.
3. Agent renames it to `commands/<command-id>.json`.
4. Bridge claims it by moving it to `processing/`.
5. Bridge executes the command.
6. Bridge writes a response atomically to `responses/`.
7. Failed commands are moved to `failed/`.
8. Agent times out if no result appears within the configured interval.

### 9.3 Future transport options

- localhost HTTP;
- named pipes;
- WebSocket;
- platform-specific IPC.

The protocol must remain transport-independent.

---

## 10. Resolve bridge lifecycle

### 10.1 Launch

The user launches the bridge from:

```text
Workspace → Scripts → Edit → ResolveBridge
```

A later version may support automatic startup where Resolve permits it.

### 10.2 Bridge state

The bridge writes:

```json
{
  "bridge_version": "0.1.0",
  "status": "ready",
  "resolve_version": "21.x",
  "edition": "free",
  "project_open": true,
  "last_heartbeat": "2026-07-30T12:00:00Z",
  "capabilities": []
}
```

### 10.3 Polling

For the prototype, the bridge polls the command directory at a conservative interval. The implementation must avoid blocking the Resolve UI.

### 10.4 Shutdown

The bridge must support a stop command and clean shutdown. It must not leave commands in an ambiguous state.

---

## 11. Capability model

The bridge reports capabilities instead of assuming them.

Example:

```json
{
  "provider": "resolve",
  "provider_version": "21.x",
  "edition": "free",
  "capabilities": {
    "project.read": true,
    "timeline.read": true,
    "timeline.create": "unknown",
    "media.import": "unknown",
    "clip.insert": "unknown",
    "marker.create": "unknown",
    "render.configure": "unknown",
    "render.start": "unknown"
  }
}
```

Allowed values:

- `true`;
- `false`;
- `"unknown"`;
- `"requires_confirmation"`;
- `"requires_studio"`.

---

## 12. Initial command set

### Milestone 1 — read-only proof

- `ping`
- `get_bridge_info`
- `get_capabilities`
- `get_current_project`
- `list_timelines`
- `get_current_timeline`

### Milestone 2 — safe project modifications

- `create_timeline`
- `import_media`
- `append_clip`
- `add_marker`
- `set_current_timeline`

### Milestone 3 — editing primitives

- `insert_clip`
- `move_clip`
- `trim_clip`
- `split_clip`
- `delete_clip`
- `set_clip_enabled`
- `set_clip_transform`

### Milestone 4 — delivery and workflows

- `configure_render`
- `add_render_job`
- `start_render`
- `run_recipe`

Each action must have a JSON Schema contract and automated tests.

---

## 13. MCP interface

The MCP server is an adapter over the core agent API.

Initial tools:

- `video_agent_status`
- `resolve_get_project`
- `resolve_list_timelines`
- `resolve_get_timeline`
- `resolve_import_media`
- `resolve_create_timeline`
- `resolve_append_clip`
- `resolve_add_marker`

Higher-level tools are added only after primitive operations are reliable:

- `create_rough_cut`
- `sync_screen_and_webcam`
- `remove_long_pauses`
- `clean_dialogue_audio`
- `generate_subtitles`
- `prepare_youtube_export`

The MCP layer must not directly access Resolve runtime folders. It calls application services.

---

## 14. Provider interface

Illustrative Python interface:

```python
from typing import Protocol

class VideoEditorProvider(Protocol):
    def health(self) -> dict: ...
    def capabilities(self) -> dict: ...
    def get_current_project(self) -> dict: ...
    def list_timelines(self) -> list[dict]: ...
    def get_current_timeline(self) -> dict | None: ...
    def import_media(self, paths: list[str]) -> list[dict]: ...
    def create_timeline(self, name: str, settings: dict) -> dict: ...
    def append_clip(self, timeline_id: str, asset_id: str) -> dict: ...
```

Provider implementations:

- `ResolveProvider`
- `FFmpegProvider`
- future `PremiereProvider`

---

## 15. Audio architecture

Audio processing should not be tightly coupled to Resolve.

Proposed layers:

1. **Analysis**
   - noise profile;
   - speech activity;
   - clipping detection;
   - loudness measurement;
   - silence and pause detection.

2. **Processing**
   - high-pass filter;
   - denoise;
   - de-reverb where available;
   - equalization;
   - compression;
   - de-essing;
   - limiting;
   - loudness normalization.

3. **Backends**
   - FFmpeg filters;
   - external local tools;
   - Resolve/Fairlight provider where supported.

All processing must preserve the original file and create derived assets.

---

## 16. Security model

- Bind network transports only to localhost by default.
- Do not execute arbitrary Python, shell, Lua, or Resolve expressions received through MCP.
- Use an allowlist of actions.
- Validate all commands against JSON Schema.
- Normalize and validate filesystem paths.
- Restrict commands to configured media and output roots where possible.
- Reject expired commands.
- Record an audit log.
- Never include secrets in logs.
- Destructive operations require `allow_destructive: true`.
- Future remote access requires authentication and is out of scope for v1.

---

## 17. Configuration

Default config location:

```text
%APPDATA%\DaVinciResolveAgent\config.toml
```

Example:

```toml
[agent]
log_level = "INFO"
provider = "resolve"
command_timeout_seconds = 30

[runtime]
root = "${LOCALAPPDATA}/DaVinciResolveAgent/runtime"

[resolve]
scripts_category = "Edit"
poll_interval_ms = 500

[safety]
allow_destructive = false
create_backup = true

[media]
allowed_roots = [
  "G:/Videos",
  "${USERPROFILE}/Videos"
]
```

Repository config must contain only defaults. Machine-specific config must not be committed.

---

## 18. Installation requirements

### 18.1 Supported initial platform

- Windows 10 or Windows 11;
- Python 3.10–3.12;
- Git;
- DaVinci Resolve 21 Free or Studio.

### 18.2 Installer responsibilities

`install.ps1` must:

1. detect Python;
2. reject unsupported Python versions with a clear message;
3. create `.venv`;
4. install the local package;
5. create runtime and config directories;
6. copy the Resolve bridge to the correct user script directory;
7. preserve any existing bridge installation as a backup;
8. generate default local configuration;
9. print the exact next manual step in Resolve.

### 18.3 Verification responsibilities

`verify.ps1` must check:

- Python environment;
- package import;
- config validity;
- runtime permissions;
- bridge installation path;
- bridge heartbeat;
- current Resolve connectivity;
- provider capability report.

### 18.4 Uninstaller responsibilities

`uninstall.ps1` must:

- remove only files installed by this project;
- preserve user projects and media;
- offer to preserve configuration and logs;
- restore the previous bridge backup if present.

---

## 19. Logging and diagnostics

Log categories:

- `agent`;
- `transport`;
- `provider.resolve`;
- `bridge.resolve`;
- `mcp`;
- `workflow`;
- `installer`.

Each record should include:

```json
{
  "timestamp": "ISO-8601",
  "level": "INFO",
  "component": "bridge.resolve",
  "event": "command_completed",
  "command_id": "uuid",
  "duration_ms": 24
}
```

A diagnostics bundle command should collect config with secrets removed, logs, versions, capabilities, and recent failed command metadata.

---

## 20. Testing strategy

### 20.1 Unit tests

- schema validation;
- path validation;
- command serialization;
- response parsing;
- workflow planning;
- provider-neutral services.

### 20.2 Contract tests

Every command and response example must validate against its JSON Schema.

### 20.3 Bridge simulation

A fake Resolve environment should simulate the subset of objects used by the bridge, allowing CI tests without Resolve installed.

### 20.4 Manual integration tests

A documented test matrix:

- Resolve 21 Free on Windows;
- Resolve 21 Studio on Windows;
- supported Python versions;
- project open / no project open;
- timeline present / absent.

---

## 21. Versioning

- Semantic Versioning for the application.
- Protocol version maintained separately.
- Bridge and agent negotiate protocol compatibility.
- Breaking protocol changes require a major protocol version.
- Recipe format has its own version field.

---

## 22. Development milestones

### M0 — repository foundation

- project skeleton;
- `pyproject.toml`;
- formatting, linting, and tests;
- installer placeholders;
- specification and architecture docs.

### M1 — bridge proof of concept

- bridge visible in `Workspace → Scripts`;
- `ping`;
- heartbeat;
- current project name;
- current timeline name;
- filesystem transport.

### M2 — external agent

- CLI client;
- validated contracts;
- timeout and error handling;
- capability discovery.

### M3 — MCP server

- status tools;
- read-only Resolve tools;
- documentation for MCP client configuration.

### M4 — safe editing

- media import;
- timeline creation;
- clip append;
- markers;
- rollback strategy.

### M5 — rough-cut workflow

- screen/webcam ingestion;
- synchronization;
- pause analysis;
- draft edit plan;
- user review before applying.

### M6 — audio workflow

- dialogue analysis;
- deterministic audio-processing preset;
- loudness validation;
- before/after reporting.

---

## 23. First acceptance test

The first successful end-to-end test is:

1. Resolve 21 Free is running with a project open. The confirmed
   `create_project` action is an exception to the open-project prerequisite:
   it creates and saves a unique project in the current library folder,
   backing up the current project only when one exists. It requires a running
   bridge; starting the bridge from Project Manager remains live-test pending.
2. User launches `ResolveBridge` through `Workspace → Scripts → Edit`.
3. Bridge writes a heartbeat and capability file.
4. From PowerShell, the user runs:

```powershell
davinci-agent status
davinci-agent resolve project
```

5. The CLI prints the actual open project name.
6. The same operation works through an MCP tool.
7. The entire setup can be reproduced on a second Windows computer using the installer and README.

---

## 24. Open questions

1. Which Resolve objects are available to scripts launched internally in Resolve 21 Free?
2. Can the bridge safely run a persistent polling loop without blocking the UI?
3. Which edit operations work in Free, and which are restricted?
4. Is filesystem IPC sufficiently responsive for interactive use?
5. Should the bridge be Python or Lua for the broadest compatibility?
6. How should project backup or rollback be implemented?
7. Which MCP client will be the first supported client?
8. Should the public package name remain `DaVinci-Resolve-Agent`, or move to a provider-neutral name later?

---

## 25. Immediate next step

Create the repository skeleton and implement only the M1 bridge proof:

- install the bridge through `install.ps1`;
- make it visible under `Workspace → Scripts → Edit`;
- write heartbeat data;
- support `ping`;
- read the current project name;
- document every manual action required.

No editing operation should be implemented until this read-only proof is reliable and repeatable.
