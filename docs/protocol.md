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

## M4 write actions

The allowlist additionally contains:

- `import_media` with `paths`;
- `create_timeline` with `name`;
- `append_clip` with `timeline_id` and `asset_id`;
- `add_marker` with timeline marker fields.

Every write envelope must set `allow_destructive` to `false` and
`create_backup` to `true`. Write actions use `state/receipts` to make a stable
`idempotency_key` replay-safe. The bridge validates media paths independently
against `state/media-policy.json` before calling Resolve.

## M1 action allowlist

- `ping`
- `get_bridge_info`
- `get_capabilities`
- `get_current_project`
- `list_timelines`
- `get_current_timeline`

All actions accept an empty `arguments` object. `allow_destructive` must be
`false`. There is no action for executing Python, Lua, PowerShell, shell
commands, or Resolve expressions.

## One-shot lifecycle

M1 does not continuously poll. Invoke `ResolveBridge` from Resolve to capture a
fresh state and process commands already present in the queue. Persistent
polling requires a separate UI-blocking safety proof.

## M2 timeout behavior

The external client writes a command atomically and polls only for the matching
response file. If no response appears before the configured deadline, it raises
a structured timeout and the CLI exits with code `3`. The command remains in
the queue as local evidence and expires according to its envelope.
