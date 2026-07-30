# Resolve bridge

`ResolveBridge.py` is the internal script launched through
`Workspace → Scripts → Edit → ResolveBridge` in DaVinci Resolve.

It uses the internal Resolve/Fusion context injected into a menu script, with
the documented `DaVinciResolveScript.scriptapp("Resolve")` entry point as a
fallback. Live Resolve 21 Free testing confirmed that the injected context is
available while a direct module import is not.

The bridge uses only calls documented in the Resolve 21.0.3 local Scripting
README. It records one heartbeat/state snapshot, processes allowlisted commands
already present in the filesystem queue, and exits. M4 write operations require
a successful `.drp` project export and store idempotency receipts.

M7 render discovery uses only documented read methods. Its separate preparation
action adds one fixed MP4/H264 job only after project backup and never starts,
stops, deletes, or uploads anything.

The one-shot lifecycle is intentional: persistent polling is not enabled until
live testing proves that it does not block the Resolve UI.
