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
.\scripts\check-powershell-syntax.ps1
.\.venv\Scripts\davinci-agent.exe --version
```

GitHub Actions повторює pytest на Windows із Python 3.10, 3.11 і 3.12.
Ruff, mypy та PowerShell syntax перевіряються в окремій Python 3.12 job.
Окрема installer job запускає повний lifecycle лише у створеній нею
тимчасовій копії репозиторію та тимчасових Windows profile directories.
Вона також виконує `verify.ps1 -SkipResolveConnection`; default verification
із heartbeat залишається live-only.
Resolve integration залишається manual-only. Докладніше:
[docs/continuous-integration.md](docs/continuous-integration.md).

Кожне нове твердження про live Resolve compatibility має оновлювати
[manual integration matrix](docs/manual-integration-testing.md) і містити
повний sanitized evidence contract. CI або stale heartbeat не можна позначати
як live `verified`.

Локальний installer lifecycle змінює лише власну тимчасову sandbox:

```powershell
.\scripts\test-installer-lifecycle.ps1
```

Do not add Resolve API behavior without verifying it in the supported Resolve
edition and documenting the evidence. Never expose arbitrary Python, Lua,
PowerShell, or shell execution through a transport or public interface.
