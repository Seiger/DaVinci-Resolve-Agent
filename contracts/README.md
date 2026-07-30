# Contracts

Protocol version `1.0` accepts the read-only Resolve actions and four M4
safe-editing actions listed in `command.schema.json`. Write actions have strict
argument shapes and require `create_backup=true`. The bridge performs a minimal
validation pass without third-party dependencies because it runs inside
Resolve.

The JSON Schemas are canonical protocol documentation. From M2 onward, the
external agent validates commands, responses, date-time formats, response
status/error consistency, and capability reports with Draft 2020-12 semantics.

No contract permits arbitrary Python, Lua, PowerShell, shell, or Resolve
expression execution.

M7 adds the empty-argument read-only `get_render_environment` command and the
strict `prepare_render_job` write command. The latter accepts only
`custom_name`, requires backup, and cannot start rendering. Arbitrary render
settings, deletion, upload, and start commands remain outside the contract.

`rough-cut-plan.schema.json` is a separate M5 artifact contract rather than a
bridge command. It requires a pending human review and explicitly states that
applying the draft is unsupported in M5.

`audio-report.schema.json` defines the M6 before/after measurements, fixed
preset parameters, source-preservation flag, derived asset, and target
validation. It is also independent from the Resolve command protocol.
