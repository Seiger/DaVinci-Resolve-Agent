# Безперервна інтеграція

M27 додає GitHub Actions workflow `.github/workflows/windows-ci.yml`.

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

## Межі безпеки

Workflow має лише `contents: read`, не зберігає checkout credentials і не
містить secrets, deployment, commit або push кроків. Він не встановлює й не
запускає DaVinci Resolve та не намагається використовувати external scripting.

Live Resolve 21 Free перевірки залишаються manual-only, тому що
GitHub-hosted runner не має Resolve, відкритого проєкту та внутрішнього
Workspace script context.

## Локальний еквівалент

```powershell
.\.venv\Scripts\python.exe -m pytest -q
.\.venv\Scripts\python.exe -m ruff check .
.\.venv\Scripts\python.exe -m mypy .
.\scripts\check-powershell-syntax.ps1
.\.venv\Scripts\davinci-agent.exe --version
```
