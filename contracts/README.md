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
