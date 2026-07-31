# Contracts

Protocol version `1.0` accepts the read-only Resolve actions and allowlisted
write actions listed in `command.schema.json`. Write actions have strict
argument shapes and require `create_backup=true`. The bridge performs a minimal
validation pass without third-party dependencies because it runs inside
Resolve.

The JSON Schemas are canonical protocol documentation. From M2 onward, the
external agent validates commands, responses, date-time formats, response
status/error consistency, and capability reports with Draft 2020-12 semantics.

No contract permits arbitrary Python, Lua, PowerShell, shell, or Resolve
expression execution.

M31 adds canonical examples under `contracts/examples/`. `commands.json`
contains exactly one full envelope for every action currently enumerated by
`command.schema.json`; tests reject missing, duplicate, or extra actions and
validate every envelope. `responses.json` covers success and error consistency,
while `capabilities.json` covers boolean and all symbolic capability values.

Example timestamps, IDs, media paths, and results are illustrative contract
fixtures. They are packaged for inspection but must not be copied directly to
the live command queue. Production commands require fresh IDs, current
timestamps, policy-validated paths, and application-generated safety fields.

M7 adds the empty-argument read-only `get_render_environment` command and the
strict `prepare_render_job` write command. The latter accepts only
`custom_name` and requires backup.

M8 adds `get_render_job_status` and `start_render_job`; both accept only a safe
opaque `job_id`. Start requires backup and can target only a fixed-policy job
proven by an M7 preparation receipt. Arbitrary render settings, deletion,
stopping, upload, and mass-start commands remain outside the contract.

M9 extends `prepare_render_job` with an optional allowlisted `profile`.
Omitting it preserves the 1080p default. The only accepted values are
`youtube-1080p-h264-v1` and `youtube-2160p-h264-v1`; raw width, height, preset,
codec, quality, and output path remain outside the command contract.

M10 adds `insert_clip` with strict timeline/asset IDs, ordered source-frame
bounds, a non-negative timeline-relative position, `video|audio` track type,
and bounded track index. It requires backup. The contract does not expose
move, trim, split, delete, ripple, transform, or arbitrary clipInfo fields.

`rough-cut-plan.schema.json` is a separate M5 artifact contract rather than a
bridge command. It requires a pending human review and explicitly states that
applying the draft is unsupported in M5.

`rough-cut-approval.schema.json` is the separate M21 review record. It binds
one explicit approval to the canonical draft SHA-256 and keeps
`apply_supported=false`. Approval never changes the deterministic draft.

`audio-report.schema.json` defines the M6 before/after measurements, fixed
preset parameters, source-preservation flag, derived asset, and target
validation. It is also independent from the Resolve command protocol.
