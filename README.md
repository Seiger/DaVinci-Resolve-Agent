# DaVinci Resolve Agent

DaVinci Resolve Agent — це розширюваний локальний фреймворк автоматизації
відеоредакторів. Перший провайдер працює з DaVinci Resolve 21 Free у Windows,
але ядро не залежить від конкретного редактора.

Проєкт перебуває на етапі **Milestone M10: safe ranged clip insertion**. Він установлює
одноразовий внутрішній скрипт Resolve, перевіряє канонічні JSON-контракти,
обмінюється командами через локальний файловий транспорт і надає фіксовані
read-only та безпечні write-інструменти через stdio. M5 також створює локальні
чернетки rough cut із синхронізацією та аналізом пауз, але не застосовує їх.
M6 створює похідний PCM WAV і канонічний before/after report, не змінюючи
оригінал. Розширене редагування, довільна конфігурація рендеру й декодування
медіаконтейнерів ще не реалізовані.
Перший підетап M7 додає read-only discovery render formats, codecs, presets і
queue.
Після успішної live-перевірки discovery M7 також готує один фіксований
MP4/H264 job, але ніколи не запускає render автоматично.
Discovery та ідемпотентну підготовку такого job перевірено у Resolve 21 Free
21.0.3.7 на таймлайні з відео й аудіо.
M8 додає read-only статус і контрольований запуск лише такого
agent-підготовленого job. Повторний запуск блокується receipt і окремим
durable start-record. Read-only статус перевірено у Resolve 21 Free 21.0.3.7;
live-start ще не пройшов перевірку на короткому timeline.
M9 додає офіційне resolution discovery та другий фіксований профіль
`youtube-2160p-h264-v1`. Наявність MP4/H.264 3840×2160 і preset
`YouTube - 2160p`, а також backup-backed ідемпотентну підготовку 4K job
підтверджено у Resolve 21 Free 21.0.3.7.
M10 додає backup-backed вставку обмеженого source range на конкретний
video/audio track. Позиція задається як offset від початку timeline; наявні
items не пересуваються, не обрізаються й не видаляються. Video/audio вставку,
frame-rate conversion і replay без дублів перевірено у Resolve 21 Free
21.0.3.7.

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
.\.venv\Scripts\davinci-agent.exe resolve render-options
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
- `resolve_get_render_options`.
- `resolve_get_render_job_status`.

Безпечні write-інструменти:

- `resolve_import_media`;
- `resolve_create_timeline`;
- `resolve_append_clip`;
- `resolve_insert_clip`;
- `resolve_add_marker`.
- `resolve_prepare_render_job`.
- `resolve_start_render_job`.

Draft-only інструмент M5:

- `create_rough_cut`.

Локальний audio-інструмент M6:

- `clean_dialogue_audio`.

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

`clean_dialogue_audio` працює без Resolve та приймає allowlisted 16-bit PCM
WAV. Preset виконує детерміноване RMS leveling із peak guard, зберігає
оригінал і створює derived WAV. RMS dBFS не заявляється як LUFS. Деталі:
[audio workflow](docs/audio-workflow.md).

`resolve_prepare_render_job` використовує лише allowlisted профілі
`youtube-1080p-h264-v1` і `youtube-2160p-h264-v1`, створює `.drp` backup,
пише output у
`%USERPROFILE%\Videos\DaVinciResolveAgent\renders` і додає job у queue.
1080p залишається default. Довільні dimensions, preset, codec і path не
приймаються. Rendering залишається незапущеним.

`resolve_start_render_job` приймає лише `job_id`, який має відповідати receipt
від `resolve_prepare_render_job` і незміненому job у live queue. Перед стартом
створюється `.drp` backup. Один job не можна повторно запустити іншим
`idempotency_key`; довільний або вручну створений job bridge відхиляє.

`resolve_insert_clip` приймає asset/timeline IDs, source frame bounds,
timeline-relative `position_frames`, `track_type` (`video` або `audio`) і
`track_index`. Bridge перевіряє track та lock-state, створює backup і повертає
фактичні bounds із TimelineItem.

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
[rough cut](docs/rough-cut.md), [audio workflow](docs/audio-workflow.md),
[rollback](docs/rollback.md).
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
    -PreservePlans $true `
    -PreserveAudioReports $true `
    -PreserveProcessedAudio $true `
    -PreserveRenderOutput $true
```

Скрипт видаляє лише `.venv` цього репозиторію та каталоги застосунку, створені в
`APPDATA` і `LOCALAPPDATA`. Він не видаляє репозиторій, медіафайли чи проєкти
Resolve.
