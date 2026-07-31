# Integration tests

Automated integration tests cover installed CLI, filesystem transport, MCP
stdio handshake, and the simulated Resolve surface without requiring Resolve.
GitHub Actions runs them on Windows with Python 3.10–3.12.

Live Resolve integration remains manual-only. Verified live evidence targets
Resolve 21 Free on Windows and must document the exact version, project state,
operation, readback, backup behavior, and replay result. CI must not claim that
the Resolve application or its internal script context is available.
