# Contributing

DaVinci Resolve Agent currently targets Python 3.10–3.12 on Windows 10/11.
Keep the core provider-neutral and treat `SPECIFICATION.md` as the primary
requirements source.

## Development setup

```powershell
py -3.10 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -e ".[dev]"
```

## Checks

Run all checks before proposing a change:

```powershell
.\.venv\Scripts\python.exe -m pytest
.\.venv\Scripts\python.exe -m ruff check .
.\.venv\Scripts\python.exe -m mypy .
.\.venv\Scripts\davinci-agent.exe --version
```

Do not add Resolve API behavior without verifying it in the supported Resolve
edition and documenting the evidence. Never expose arbitrary Python, Lua,
PowerShell, or shell execution through a transport or public interface.

