# DaVinci Resolve Agent

DaVinci Resolve Agent — це розширюваний локальний фреймворк автоматизації
відеоредакторів. Перший провайдер працює з DaVinci Resolve 21 Free у Windows,
але ядро не залежить від конкретного редактора.

Проєкт перебуває на етапі **Milestone M39: webcam picture-in-picture**. Він
установлює внутрішній скрипт Resolve, перевіряє канонічні JSON-контракти,
обмінюється командами через локальний файловий транспорт і надає фіксовані
read-only та безпечні write-інструменти через stdio. M5 також створює локальні
чернетки rough cut із синхронізацією та аналізом пауз. M34 додає preview та
контрольоване застосування лише повністю підтриманого approved plan до копії
timeline; поточні `remove_pauses` плани чесно блокуються як unsupported.
Milestone M35: interactive editing session переводить вручну запущений bridge
у постійну інтерактивну сесію, а M36
додає backup-backed підготовку 1–8 video/audio доріжок перед точним placement.
Нові audio tracks створюються лише як `stereo`; видалення або зміна типу
наявних доріжок не підтримуються. Створення V2, точний readback 2V/1A і replay
без другої зміни перевірено у Resolve 21 Free 21.0.3.7.
M37 додає до bounded editing metadata фактичний FPS цільового timeline, щоб
майбутня синхронна розкладка переводила мілісекунди у frames без припущень.
Live readback у Resolve 21 Free 21.0.3.7 підтвердив 24 FPS для target timeline
і 60 FPS для source asset без backup або зміни проєкту.
M38 додає provider-neutral workflow `sync_screen_and_webcam`: він створює
новий timeline, готує V1/A1/V2 та розміщує screen video, screen audio і webcam
video з signed offset. Кожен write має окремий backup та derived idempotency
key, а progress receipt дозволяє безпечно продовжити перервану операцію.
M39 додає `compose_webcam_picture_in_picture`: workflow бере лише завершений
receipt M38, читає live resolution timeline і переводить нормалізовані
координати кадру в документовані `Pan`/`Tilt`/`ZoomX`/`ZoomY`. Маски, crop,
Fusion і довільні Resolve properties не входять до цього етапу.
Live-перевірка у Resolve 21 Free 21.0.3.7 підтвердила 1920×1080 metadata,
Pan/Tilt `614.4/-345.6`, Zoom `0.25`, один backup і replay без нової зміни.
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
live-start підтверджено під час M11 на короткому timeline.
M9 додає офіційне resolution discovery та другий фіксований профіль
`youtube-2160p-h264-v1`. Наявність MP4/H.264 3840×2160 і preset
`YouTube - 2160p`, а також backup-backed ідемпотентну підготовку 4K job
підтверджено у Resolve 21 Free 21.0.3.7.
M10 додає backup-backed вставку обмеженого source range на конкретний
video/audio track. Позиція задається як offset від початку timeline; наявні
items не пересуваються, не обрізаються й не видаляються. Video/audio вставку,
frame-rate conversion і replay без дублів перевірено у Resolve 21 Free
21.0.3.7.
M11 виконує контрольований 1080p render короткого таймлайна та додає
read-only перевірку результату. Вона приймає лише `job_id`, звіряє керовану
output-директорію, 100% завершення й ненульовий розмір MP4. Декодування,
перевірка тривалості та візуального вмісту на цьому етапі не виконуються.
Live-тест у Resolve 21 Free 21.0.3.7 завершив чотирисекундний job за
3262 мс і підтвердив MP4 розміром 804100 байт.
M12 додає backup-backed увімкнення або вимкнення одного TimelineItem за
його ID. Bridge знаходить item лише у video/audio tracks, перевіряє lock-state,
викликає документований `SetClipEnabled(Bool)` і читає результат через
`GetClipEnabled()`. Вимкнення, replay без другого backup і відновлення
початкового стану перевірено у Resolve 21 Free 21.0.3.7.
M13 додає вибір наявного timeline за ID через документований
`Project.SetCurrentTimeline`. Bridge створює backup, повертає попередній і
фактичний поточний timeline та підтримує replay без повторного backup.
Read-only список і current timeline тепер повертають канонічний `timeline_id`,
тому вибір не залежить від старих receipts, назви або index.
ID discovery, перемикання M10 → M7, replay без другого backup і повернення
M7 → M10 перевірено у Resolve 21 Free 21.0.3.7.
M14 додає backup-backed зміну обмеженого набору властивостей одного video
TimelineItem: позиції X/Y, рівномірного zoom, кута повороту та opacity. Зовнішній
контракт не приймає довільних назв Resolve-властивостей або expressions.
Bridge перевіряє межі, lock-state доріжки й фактичні значення через
`GetProperty`. Зміну opacity 100 → 90, replay без другого backup і відновлення
90 → 100 перевірено у Resolve 21 Free 21.0.3.7.
M15 додає видалення рівно одного TimelineItem через документований
`Timeline.DeleteClips`. Операція завжди non-ripple, вимагає одночасно
`confirm_delete=true`, destructive safety flag і `.drp` backup. Live-сумісність
підтверджено у Resolve 21 Free 21.0.3.7 на окремому disposable item: delete
readback, replay без другого backup і повернення preflight до одного video та
одного audio item.
M16 закриває addressability loop для editing primitives: read-only discovery
повертає IDs усіх video/audio TimelineItem вибраного timeline разом із track,
timeline/source bounds і duration. Інструмент не читає довільні properties і
не змінює проєкт. Discovery синхронної M10 пари з окремими video/audio IDs,
однаковими timeline/source bounds і без нового backup перевірено у Resolve 21
Free 21.0.3.7.
M17 додає read-only рекурсивний перелік Media Pool items із канонічними
`asset_id`, назвами та логічними folder IDs/paths. Він не повертає файлові
шляхи, raw clip properties або Resolve object handles. Folder API також
повертає timeline entries, тому контракт чесно не називає всі результати
source assets. У Resolve 21 Free 21.0.3.7 знайдено п'ять items у `Master`,
включно з потрібним MKV asset `e2c01761-…`, без нового backup.
M18 додає фіксований read-only snapshot поточного workspace: одним запитом
повертаються bridge metadata, проєкт, timelines, current timeline та його
items, Media Pool і render discovery. Команда не приймає перелік довільних
дій, не створює backup і не запускає постійний цикл. Це скорочує повну
діагностику до одного ручного запуску ResolveBridge.
M19 додає backup-backed link/unlink для групи з 2–16 TimelineItem через
документовані `SetClipsLinked` і `GetLinkedItems`. Bridge приймає лише
канонічні IDs, перевіряє lock-state кожної доріжки, фактичний link-state та
idempotent replay. Переміщення, trim і split не реалізовані, бо відповідних
документованих TimelineItem API у локальній документації Resolve 21 немає.
M20 додає backup-backed дублювання одного timeline за ID через документований
`Timeline.DuplicateTimeline(name)`. Bridge відхиляє конфлікт імен, перевіряє
новий ID і появу копії у project timeline list, не перемикає current timeline
та не змінює оригінал. Це створює безпечну основу для майбутнього застосування
reviewed rough-cut до окремої копії.
M21 додає локальне явне схвалення draft-плану через окремий approval record.
Draft залишається незмінним, approval прив’язаний до SHA-256 його канонічного
вмісту, а повторне схвалення є idempotent. `apply_supported` залишається
`false`: схвалення не запускає ResolveBridge і не застосовує монтаж.
M22 додає read-only перелік bounded plan summaries і повторне відкриття одного
draft разом із чинним approval. Summary не містить source media paths, а
детальний запит приймає лише canonical `plan_id` і повторно перевіряє
контракти та SHA-256.

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

1. За потреби виконай offline preflight без запущеного Resolve:

```powershell
.\installer\verify.ps1 -SkipResolveConnection
```

2. Перезапусти DaVinci Resolve.
3. Відкрий проєкт.
4. Запусти `Workspace → Scripts → Edit → ResolveBridge`.
5. Повернися до PowerShell і виконай повну перевірку:

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
.\.venv\Scripts\davinci-agent.exe resolve snapshot --json
.\.venv\Scripts\davinci-agent.exe resolve render-options
.\.venv\Scripts\davinci-agent.exe diagnostics
```

`status` читає останній збережений heartbeat. `diagnostics` локально створює
sanitized JSON із версіями, конфігурацією, cached capabilities, metadata
failed commands і bounded log excerpts. Ці дві команди не потребують запуску
ResolveBridge. Інші команди ставлять перевірений запит у чергу та типово
очікують до 30 секунд. Запусти
`Workspace → Scripts → Edit → ResolveBridge` один раз: bridge обслуговує
allowlisted queue, доки не отримає `resolve_stop_bridge`. Час очікування можна
змінити через `--timeout-seconds`. Responsive UI, послідовні команди без
повторного запуску меню та clean stop перевірено у Resolve 21 Free 21.0.3.7.

Diagnostics bundle зберігається у фіксованій runtime-директорії, не містить
медіа, backups, raw commands/responses або відомих secret-полів. Перед
передаванням третій стороні його слід переглянути вручну. Деталі:
[локальна діагностика](docs/diagnostics.md).

Кожна валідована Resolve-команда через filesystem transport створює окремий
canonical audit record до enqueue та атомарно оновлює його після відповіді або
timeout. Audit не містить arguments, media paths, idempotency keys, response
payloads чи error messages. Деталі: [audit logging](docs/audit-logging.md).

Сім локальних rough-cut/audio operations також створюють окремі workflow
records зі станом `running`, `success` або `error`. Вони не містять arguments,
plan/report IDs, file paths, contents, results чи exception messages. Деталі:
[workflow audit](docs/workflow-audit.md).

GitHub Actions перевіряє повний test suite на Windows із Python 3.10, 3.11 і
3.12. Окрема quality job запускає Ruff, mypy та read-only syntax parse
installer PowerShell scripts. M28 також запускає install → повторний install →
uninstall у повністю тимчасовому профілі Windows, перевіряє збереження
локальної конфігурації, backup/restore попереднього bridge та недоторканність
стороннього sentinel-файлу. M29 запускає в цій самій sandbox offline
`verify.ps1`, включно з перевіркою локального TOML і write/delete probes у
керованих директоріях. Workflow має лише `contents: read` і не виконує
deploy, commit, push або live Resolve automation. Деталі:
[безперервна інтеграція](docs/continuous-integration.md).

M32 окремо збирає wheel, перевіряє його archive paths, metadata, entry points,
runtime package boundary і packaged resources. Після цього CI замінює editable
install на wheel та запускає CLI поза repository directory. Wheel не
публікується й не завантажується як artifact.

Live Resolve compatibility ведеться окремою platform/state матрицею.
Підтверджено Windows 10 build 19045, Python 3.12.10 і Resolve 21 Free
21.0.3.7 з відкритим проєктом та timeline. Windows 11, Studio, project absent
і timeline absent не видаються за перевірені та залишаються `pending`.
Деталі: [ручне інтеграційне тестування](docs/manual-integration-testing.md).

Кожна з 24 allowlisted Resolve actions має рівно один повний command example,
який автоматично валідовується канонічною schema. Окремі fixtures покривають
success/error responses і всі capability value kinds. Статичні приклади
призначені для документації та тестів — їх не можна напряму ставити у live
чергу. Деталі: [протокол](docs/protocol.md) і [contracts](contracts/README.md).

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

Для Codex репозиторій уже містить переносиму project-scoped конфігурацію
`.codex/config.toml`. Після `installer\install.ps1` відкрий цей checkout як
trusted project і перезапусти Codex. Read-only tools виконуються без
підтвердження, а write-tools запитують його. Наскрізна перевірка описана в
[документації MCP](docs/mcp.md).

Read-only інструменти:

- `video_agent_status`;
- `resolve_get_project`;
- `resolve_list_timelines`;
- `resolve_get_timeline`.
- `resolve_list_timeline_items`.
- `resolve_list_media_pool_items`.
- `resolve_get_editing_metadata`.
- `resolve_get_workspace_snapshot`.
- `resolve_get_render_options`.
- `resolve_get_render_job_status`.
- `resolve_verify_render_output`.

Безпечні write-інструменти:

- `resolve_stop_bridge`;
- `resolve_import_media`;
- `resolve_create_timeline`;
- `resolve_ensure_timeline_tracks`;
- `resolve_duplicate_timeline`;
- `resolve_set_current_timeline`;
- `resolve_append_clip`;
- `resolve_insert_clip`;
- `resolve_set_clip_enabled`;
- `resolve_set_clips_linked`;
- `resolve_set_clip_transform`;
- `resolve_delete_clip`;
- `resolve_add_marker`.
- `resolve_prepare_render_job`.
- `resolve_start_render_job`.

Локальні rough-cut інструменти:

- `create_rough_cut`.
- `approve_rough_cut`.
- `get_rough_cut_plan`.
- `list_rough_cut_plans`.
- `sync_screen_and_webcam`.
- `compose_webcam_picture_in_picture`.

Локальний audio-інструмент M6:

- `clean_dialogue_audio`.
- `get_audio_report`.
- `list_audio_reports`.

Для Resolve-запитів потрібно один раз вручну запустити `ResolveBridge` з меню
Resolve. Після цього bridge обслуговує наступні allowlisted команди, доки
`resolve_stop_bridge` не завершить його cleanly. Перед кожною write-операцією
bridge експортує
проєкт у `.drp`; імпорт дозволений лише з `media.allowed_roots`. Приклад
конфігурації клієнта наведено в [документації MCP](docs/mcp.md), а відновлення —
в [rollback strategy](docs/rollback.md).

`create_rough_cut` не звертається до Resolve і не змінює проєкт. Для
детермінованого аналізу йому потрібні окремі нестиснені 16-bit PCM WAV-доріжки.
Результат завжди має статус `pending_review` та зберігається в локальній
runtime-директорії. Деталі наведено в
[документації rough cut](docs/rough-cut.md).

`approve_rough_cut` приймає лише canonical `plan_id` і
`confirm_review=true`. Він повторно валідовує draft, фіксує його SHA-256 та
створює окремий approval record у runtime `plans`. Tool не змінює draft,
не ставить bridge-команду й завжди повертає `apply_supported=false`.

`list_rough_cut_plans` повертає до 100 summaries без source media paths.
`get_rough_cut_plan` приймає canonical ID і повертає валідований draft,
matching approval або `null`, effective status та `apply_supported=false`.
Обидва інструменти read-only і не використовують ResolveBridge.

`sync_screen_and_webcam` приймає нову назву timeline, canonical IDs screen і
webcam assets, signed `webcam_offset_ms` у межах ±30 секунд та
`confirm_sync=true`. Workflow створює новий timeline, забезпечує 2V/1A,
конвертує offset за live target FPS і вставляє screen video на V1, screen audio
на A1 та webcam video на V2. Webcam audio, trim, split і pause removal не
виконуються. Результат перевіряється через bounded TimelineItem readback;
фактичні stream extents після можливого Resolve clamp є авторитетними.

`compose_webcam_picture_in_picture` приймає canonical receipt ID завершеного
M38, `size_percent` від 10 до 50, координати центру `center_x_percent` і
`center_y_percent` від 0 до 100 та `confirm_layout=true`. Нуль координат —
лівий/верхній край кадру. Workflow читає live width/height timeline, застосовує
transform лише до canonical webcam item V2 і вимагає exact property readback.
Default 25/82/82 дає компактну розкладку праворуч унизу; кругла маска,
рамка, crop і Fusion поки не реалізовані.

`clean_dialogue_audio` працює без Resolve та приймає allowlisted 16-bit PCM
WAV. Preset виконує детерміноване RMS leveling із peak guard, зберігає
оригінал і створює derived WAV. RMS dBFS не заявляється як LUFS. Деталі:
[audio workflow](docs/audio-workflow.md).

`list_audio_reports` повертає до 100 summaries без source/derived paths.
`get_audio_report` приймає canonical `report_id` і повертає повторно
валідований before/after report. Обидва інструменти read-only, не обробляють
медіа та не використовують ResolveBridge.

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

`resolve_verify_render_output` повторно читає live status job і локально
перевіряє, що завершений MP4 існує в
`%USERPROFILE%\Videos\DaVinciResolveAgent\renders` та має ненульовий розмір.
Інструмент read-only і не запускає render.

`resolve_insert_clip` приймає asset/timeline IDs, source frame bounds,
timeline-relative `position_frames`, `track_type` (`video` або `audio`) і
`track_index`. Bridge перевіряє track та lock-state, створює backup і повертає
фактичні bounds із TimelineItem.

`resolve_set_clip_enabled` приймає лише `timeline_id`, `timeline_item_id` і
boolean `enabled`. Перед зміною bridge перевіряє існування item і lock-state
й створює `.drp` backup. Tool не переміщує, не обрізає, не розділяє і не
видаляє кліп.

`resolve_set_clips_linked` приймає `timeline_id`, від 2 до 16 унікальних
`timeline_item_ids` і boolean `linked`. Bridge перевіряє наявність кожного
item, lock-state його video/audio track, створює `.drp` backup і звіряє
фактичні зв’язки через `GetLinkedItems`. Довільне групування, один item або
масове редагування всього timeline не підтримуються.

`resolve_set_current_timeline` приймає лише ID наявного timeline. Bridge
перевіряє його існування, створює `.drp` backup, викликає
`SetCurrentTimeline` і звіряє фактичний current timeline. Tool не створює,
не перейменовує і не видаляє timelines.

`resolve_duplicate_timeline` приймає ID наявного timeline та унікальну нову
назву. Перед викликом `DuplicateTimeline` bridge створює `.drp` backup, а
після нього звіряє нові ID/назву і наявність копії у проєкті. Оригінальний і
current timeline залишаються незмінними; якщо Resolve тимчасово перемкнув
current timeline, bridge відновлює попередній і перевіряє результат.

`resolve_ensure_timeline_tracks` приймає ID timeline та цільові кількості
video/audio доріжок від 1 до 8. Bridge лише додає відсутні доріжки через
документований `AddTrack`, створює нові audio tracks як `stereo`, після кожної
операції звіряє `GetTrackCount` і ніколи не видаляє наявні доріжки.

`resolve_set_clip_transform` приймає `timeline_id`, `timeline_item_id` та
щонайменше одне з полів `position_x`, `position_y`, `zoom`,
`rotation_degrees`, `opacity_percent`. Bridge працює лише з video item на
незаблокованій доріжці, створює `.drp` backup і звіряє записані значення.
Tool не приймає raw Resolve property names, keyframes, expressions або
довільний код.

`resolve_delete_clip` приймає лише IDs одного TimelineItem і явне
`confirm_delete=true`. MCP позначає його destructive; transport встановлює
`allow_destructive=true`, bridge створює backup, викликає non-ripple delete і
перевіряє, що item більше не повертається з timeline. Tool не підтримує масове
або ripple-видалення.

`resolve_list_timeline_items` приймає `timeline_id` і повертає канонічні
`timeline_item_id` для video/audio tracks, їхні назви, track index,
timeline/source frame bounds та duration. Tool read-only, не створює backup і
не повертає raw Resolve objects або довільні clip properties.

`resolve_list_media_pool_items` без аргументів рекурсивно перелічує поточний
Media Pool і повертає `asset_id`, назву, `folder_id` та логічний folder path. Tool
read-only, не створює backup, не читає файлові шляхи та не викликає
`GetClipProperty`.

`resolve_get_editing_metadata` приймає один `timeline_id` та 1–100 унікальних
`asset_id`. Він повертає кількість video/audio tracks і лише потрібні для
placement значення: FPS цільового timeline, а для asset — `Frames` та `FPS`;
raw property snapshot і файлові шляхи
не повертаються. Capability стає підтвердженою лише після успішного live
readback.

`resolve_get_workspace_snapshot` без аргументів збирає всі основні read-only
розділи одним bridge-запитом. Він не є універсальним batch dispatcher:
користувач не може передати назви команд, код або Resolve expressions.
Внутрішній скрипт запускається вручну та не додає зовнішнього керування
Resolve. Встановлена документація Resolve 21
описує зовнішній Scripting API як API Resolve Studio, тому для Resolve 21 Free
проєкт не заявляє непідтверджений автоматичний зовнішній запуск.

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
