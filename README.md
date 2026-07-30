# DaVinci Resolve Agent

DaVinci Resolve Agent — це розширюваний локальний фреймворк автоматизації
відеоредакторів. Перший провайдер працює з DaVinci Resolve 21 Free у Windows,
але ядро не залежить від конкретного редактора.

Проєкт перебуває на етапі **Milestone M5: rough-cut workflow**. Він установлює
одноразовий внутрішній скрипт Resolve, перевіряє канонічні JSON-контракти,
обмінюється командами через локальний файловий транспорт і надає read-only та
чотири безпечні write-інструменти через stdio. M5 також створює локальні
чернетки rough cut із синхронізацією та аналізом пауз, але не застосовує їх.
Розширене редагування, рендер та декодування медіа ще не реалізовані.

## Вимоги

- Windows 10 або Windows 11;
- Python 3.10, 3.11 або 3.12;
- Git;
- доступ до налаштованого Python package index під час першого встановлення.

## Встановлення

У PowerShell:

```powershell
git clone <repository-url>
cd DaVinci-Resolve-Agent
.\installer\install.ps1
```

Інсталятор створює:

- `.venv` у репозиторії;
- `%APPDATA%\DaVinciResolveAgent\config.toml`;
- `%LOCALAPPDATA%\DaVinciResolveAgent\runtime`;
- `%APPDATA%\Blackmagic Design\DaVinci Resolve\Support\Fusion\Scripts\Edit\ResolveBridge.py`.

Після встановлення:

1. Перезапусти DaVinci Resolve.
2. Відкрий проєкт.
3. Запусти `Workspace → Scripts → Edit → ResolveBridge`.
4. Повернися до PowerShell і виконай:

```powershell
.\installer\verify.ps1
```

## CLI

```powershell
.\.venv\Scripts\davinci-agent.exe --version
.\.venv\Scripts\davinci-agent.exe status
.\.venv\Scripts\davinci-agent.exe ping
.\.venv\Scripts\davinci-agent.exe resolve bridge
.\.venv\Scripts\davinci-agent.exe resolve capabilities
.\.venv\Scripts\davinci-agent.exe resolve project
.\.venv\Scripts\davinci-agent.exe resolve timelines
.\.venv\Scripts\davinci-agent.exe resolve timeline
```

`status` читає останній збережений heartbeat. Інші команди ставлять перевірений
запит у чергу та типово очікують до 30 секунд. Поки команда очікує, запусти
`Workspace → Scripts → Edit → ResolveBridge`, щоб одноразовий bridge її
опрацював. Час очікування можна змінити через `--timeout-seconds`.

Коди завершення CLI:

- `0` — успіх;
- `1` — помилка bridge, контракту, конфігурації або протоколу;
- `2` — некоректний виклик CLI;
- `3` — вичерпано час очікування команди.

## MCP

Локальний MCP-сервер запускається через stdio:

```powershell
.\.venv\Scripts\davinci-agent-mcp.exe
```

Read-only інструменти:

- `video_agent_status`;
- `resolve_get_project`;
- `resolve_list_timelines`;
- `resolve_get_timeline`.

Безпечні write-інструменти:

- `resolve_import_media`;
- `resolve_create_timeline`;
- `resolve_append_clip`;
- `resolve_add_marker`.

Draft-only інструмент M5:

- `create_rough_cut`.

Для Resolve-запитів потрібно запустити `ResolveBridge` з меню Resolve, поки
MCP-клієнт очікує відповідь. Перед кожною write-операцією bridge експортує
проєкт у `.drp`; імпорт дозволений лише з `media.allowed_roots`. Приклад
конфігурації клієнта наведено в [документації MCP](docs/mcp.md), а відновлення —
в [rollback strategy](docs/rollback.md).

`create_rough_cut` не звертається до Resolve і не змінює проєкт. Для
детермінованого аналізу йому потрібні окремі нестиснені 16-bit PCM WAV-доріжки.
Результат завжди має статус `pending_review` та зберігається в локальній
runtime-директорії. Деталі наведено в
[документації rough cut](docs/rough-cut.md).

## Розробка

```powershell
py -3.12 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -e ".[dev]"
.\.venv\Scripts\python.exe -m pytest
.\.venv\Scripts\python.exe -m ruff check .
.\.venv\Scripts\python.exe -m mypy .
```

Докладніше дивись у документації про
[встановлення у Windows](docs/installation-windows.md),
[архітектуру](docs/architecture.md), [MCP](docs/mcp.md) та
[rough cut](docs/rough-cut.md), [rollback](docs/rollback.md).
Основні вимоги продукту зафіксовані в
[SPECIFICATION.md](SPECIFICATION.md).

## Видалення

Інтерактивно:

```powershell
.\installer\uninstall.ps1
```

Без запитань:

```powershell
.\installer\uninstall.ps1 `
    -PreserveConfig $true `
    -PreserveLogs $true `
    -PreserveBackups $true `
    -PreservePlans $true
```

Скрипт видаляє лише `.venv` цього репозиторію та каталоги застосунку, створені в
`APPDATA` і `LOCALAPPDATA`. Він не видаляє репозиторій, медіафайли чи проєкти
Resolve.
