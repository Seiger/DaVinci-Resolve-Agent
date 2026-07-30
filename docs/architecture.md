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

## Future providers

Resolve-specific imports and object handling remain within the Resolve adapter.
An FFmpeg or Premiere provider can implement the same provider-neutral contracts
without changing the agent core.
