# Retry a rejected media import with the original key

An import timeout does not establish whether Resolve imported the files. Keep
the original `paths` and `idempotency_key`; do not change the key or transport
to bypass a pending operation.

For the managed Lua SDK transport, `resolve_import_media` can start one new
attempt with that same key when the original native acknowledgement proves
`SDK_OPERATION_EXPIRED` **before the ImportMedia API call**. This includes an
uncertain host receipt whose exact late native rejection is now available, or
a terminal rejection previously reconciled from that evidence.

The automatic MCP facade sends an existing SDK key to the coordinator before
native readiness checks. A stored key alone grants no retry permission; invalid
or uncertain evidence remains blocked without bootstrapping Resolve.

## Required proof

The worker validates both native preset exports, the original request bytes and
hash, canonical command, fingerprint, session, generation, backup and SDK call
history. It accepts the fixed adapter's pre-call expiry rejection only. A host
error code, timeout, cached project name or generic SDK failure is insufficient.
A canonical success receipt or another pending mutation prevents a new attempt.

The retry remains in the original native runtime and transport. It neither
launches Resolve nor opens a project. The first SDK exchange freshly checks
the original project UUID before saving, backing up or importing. The existing
backup and native concurrent-change checks still apply.

## Attempts and replay

Each request has its own command UUID and expiry but keeps the original logical
idempotency key and exact import arguments. The worker does not loop on a failed
import. One request reserves at most one new attempt.

Before dispatch, `config/managed-free/import-retries/<key-hash>/<previous-command>.json`
records the previous owner, ledger, command, proof hashes and new attempt. Original
commands, responses, traces and native acknowledgements remain available. Original
packet directories and the previous SDK ledger are archived under
`<native-runtime>/rejected-import-<previous-command>/`. The current owner links to
that journal; the current canonical response/ledger records the new outcome.

After success, further calls with the same paths and key return the saved result
before any connection, launch or project-opening work. Replayed asset IDs are
historical; verify the current project before using them for timeline work.
Concurrent same-key requests share this result. If the new
attempt times out after a possible import, it stays fenced: the previous rejection
does not authorize another attempt. A changed project/session/generation, altered
proof, different paths or foreign packet also remains blocked.

A host interruption during reservation fails closed and retains the journal and
ownership for inspection. It does not automatically discard an unfinished
reservation. External Python SDK failures and other write actions retain their
existing recovery rules.

## MCP errors

Expected import errors return a structured `code`, `detail` and `retryable` value.
An uncertain command timeout also reports its original command ID and key. An
error response is not a successful import acknowledgement; use only a successful
result's asset IDs for subsequent timeline work.

The retry path imports media only. It does not create tracks, append clips, change
a timeline or render. The test suite exercises retries with API doubles; live
installation must still use a merged upstream main commit.
