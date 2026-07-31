# Безперервна інтеграція

M27 додає GitHub Actions workflow `.github/workflows/windows-ci.yml`, M28 —
ізольовану перевірку повного installer lifecycle, а M29 — offline verification
installed state без підробленого Resolve heartbeat.

## Test matrix

На `windows-latest` окремо перевіряються:

- Python 3.10;
- Python 3.11;
- Python 3.12.

Кожна matrix job встановлює package в editable mode з `.[dev]`, запускає
повний `pytest` і перевіряє installed `davinci-agent --version`.

Окрема Python 3.12 job запускає:

- `ruff check .`;
- `mypy .`;
- read-only syntax parse чотирьох installer PowerShell scripts.

Ще одна Python 3.12 job виконує `scripts/test-installer-lifecycle.ps1`.
Job має явний timeout 15 хвилин.
Скрипт копіює лише tracked files поточного checkout у нову директорію під
Windows temporary root і спрямовує `APPDATA`, `LOCALAPPDATA` та `USERPROFILE`
у цю sandbox. `PIP_CACHE_DIR` також має окреме sandbox-значення, щоб Win32
known-folder fallback не міг створити cache у checkout. Усередині
перевіряються:

- перша інсталяція та імпорт установленого package;
- `davinci-agent --version`;
- збереження наявного локального `config.toml`;
- backup наявного стороннього `ResolveBridge.py`;
- безпечний повторний запуск installer;
- `verify.ps1 -SkipResolveConnection`;
- валідація machine-local TOML;
- write/delete probe у кожній installer-managed application directory;
- повний opt-in uninstall;
- відновлення попереднього bridge;
- збереження sentinel-файлу поза installer-owned directories.

## Межі безпеки

Workflow має лише `contents: read`, не зберігає checkout credentials і не
містить secrets, deployment, commit або push кроків. Він не встановлює й не
запускає DaVinci Resolve та не намагається використовувати external scripting.

Live Resolve 21 Free перевірки залишаються manual-only, тому що
GitHub-hosted runner не має Resolve, відкритого проєкту та внутрішнього
Workspace script context.

Installer lifecycle запускає лише явний offline-режим `verify.ps1`. Default
режим продовжує вимагати heartbeat і capability report зі справжнього Resolve.
CI перевіряє відтворюваність файлової інсталяції, конфігурацію та permissions,
але не заявляє live сумісність із Resolve.

## Локальний еквівалент

```powershell
.\.venv\Scripts\python.exe -m pytest -q
.\.venv\Scripts\python.exe -m ruff check .
.\.venv\Scripts\python.exe -m mypy .
.\scripts\check-powershell-syntax.ps1
.\scripts\test-installer-lifecycle.ps1
.\.venv\Scripts\davinci-agent.exe --version
```
