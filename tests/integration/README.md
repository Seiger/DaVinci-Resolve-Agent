# Integration tests

Automated integration tests cover installed CLI, filesystem transport, MCP
stdio handshake, and the simulated Resolve surface without requiring Resolve.
GitHub Actions runs them on Windows with Python 3.10–3.12.

The M28 PowerShell smoke-test additionally covers install, idempotent reinstall,
and explicit uninstall inside a generated temporary repository and Windows
profile sandbox. It does not run `verify.ps1` because that command intentionally
requires a real bridge heartbeat and capability report.

Live Resolve integration remains manual-only. Verified live evidence targets
Resolve 21 Free on Windows and must document the exact version, project state,
operation, readback, backup behavior, and replay result. CI must not claim that
the Resolve application or its internal script context is available.
