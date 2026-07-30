# Налаштування MCP-клієнта

## Межі MCP

MCP-сервер працює локально через `stdio` і не відкриває мережевий порт.
Read-only інструменти:

- `video_agent_status`;
- `resolve_get_project`;
- `resolve_list_timelines`;
- `resolve_get_timeline`;
- `resolve_get_render_options`.
- `resolve_get_render_job_status`.
- `resolve_verify_render_output`.

Write-інструменти M4:

- `resolve_import_media`;
- `resolve_create_timeline`;
- `resolve_set_current_timeline`;
- `resolve_append_clip`;
- `resolve_insert_clip`;
- `resolve_set_clip_enabled`;
- `resolve_set_clip_transform`;
- `resolve_delete_clip`;
- `resolve_add_marker`.
- `resolve_prepare_render_job`.
- `resolve_start_render_job`.

Draft-only інструмент M5:

- `create_rough_cut`.

Локальний audio-інструмент M6:

- `clean_dialogue_audio`.

MCP-адаптер звертається до application service. Він не працює з transport
runtime безпосередньо та не приймає довільних назв команд, Python, Lua,
PowerShell або shell-коду.

`create_rough_cut` валідовує локальні файли, аналізує окремі PCM WAV-доріжки
та зберігає `pending_review` план. Він не ставить команду bridge, не відкриває
проєкт Resolve й не застосовує запропоновані операції. Формат і обмеження
описано в [rough-cut.md](rough-cut.md).

`clean_dialogue_audio` приймає allowlisted 16-bit PCM WAV, створює derived WAV
і before/after report. Інструмент не викликає Resolve bridge та не приймає
довільних filter graph, команд або коду. Докладніше:
[audio-workflow.md](audio-workflow.md).

## Конфігурація клієнта

Спочатку виконай `installer\install.ps1`. У конфігурації MCP-клієнта вкажи
абсолютний шлях до створеного executable. Не записуй власний шлях у файли
репозиторію:

```json
{
  "mcpServers": {
    "davinci-resolve-agent": {
      "command": "<repository-path>\\.venv\\Scripts\\davinci-agent-mcp.exe",
      "args": []
    }
  }
}
```

Заміни `<repository-path>` на локальний шлях до checkout на конкретному
комп'ютері та перезапусти MCP-клієнт.

## Виконання Resolve-запитів

`video_agent_status` повертає кешований стан bridge одразу.
`create_rough_cut` і `clean_dialogue_audio` також працюють без bridge.
Resolve-інструменти ставлять команду в локальну чергу. Поки клієнт очікує
відповідь:

1. відкрий потрібний проєкт у DaVinci Resolve;
2. запусти `Workspace → Scripts → Edit → ResolveBridge`;
3. дочекайся відповіді MCP-клієнта.

Типовий timeout становить 30 секунд. Аргумент `timeout_seconds` приймає значення
понад `0` і не більше `300`. Одноразова модель bridge є навмисним обмеженням
поточного прототипу.

`resolve_get_render_options` є discovery-only інструментом M7. Він читає
документовані Resolve formats, codecs, presets, поточні значення та render
queue. Він не конфігурує й не запускає render.

`resolve_prepare_render_job` приймає лише безпечний filename stem у
`custom_name` та необов'язковий `profile`. Він створює `.drp` backup,
застосовує фіксований `youtube-1080p-h264-v1` або
`youtube-2160p-h264-v1`, додає MP4/H264 job у queue та повертає
`started=false`. Default — 1080p. Output directory, raw dimensions, codec і
Resolve preset не задаються через MCP.

`resolve_get_render_job_status` читає документований status одного `job_id`.
`resolve_start_render_job` стартує лише job, який був створений
`resolve_prepare_render_job`, досі відповідає фіксованому 1080p MP4/H264
контракту й не має попереднього start-record. Tool не приймає output path,
codec, preset, список job або upload target. Перед стартом створюється backup.

`resolve_verify_render_output` повторно читає status і зіставляє
`TargetDir`/`OutputFilename` із керованою директорією. Успішна перевірка
вимагає `CompletionPercentage=100`, наявного MP4 і ненульового розміру.
Інструмент не декодує контейнер і не перевіряє зображення, звук або тривалість.

`resolve_insert_clip` вставляє один bounded source range на вказаний
`video|audio` track. `position_frames` є offset від початку timeline, а не
абсолютним Resolve frame. Tool не приймає довільний `clipInfo`, ripple,
delete, move, transform або код. Перед вставкою створюється `.drp` backup.

`resolve_set_clip_enabled` змінює лише enabled-state одного TimelineItem.
Аргументи: `timeline_id`, `timeline_item_id`, `enabled`. Bridge сканує
video/audio tracks через документований `GetItemListInTrack`, відхиляє
locked track, створює backup і перевіряє результат через `GetClipEnabled`.
Tool не приймає track index, довільну властивість або Resolve expression.

`resolve_set_current_timeline` приймає один `timeline_id`, створює backup,
вибирає вже наявний timeline через документований `SetCurrentTimeline` і
перевіряє результат через `GetCurrentTimeline`. Відповідь містить попередній
та новий timeline. Tool не приймає назву або index і не створює timeline.
`resolve_list_timelines` і `resolve_get_timeline` повертають потрібні
канонічні IDs разом із назвами.

`resolve_set_clip_transform` змінює лише дозволені transform-поля одного
video TimelineItem: `position_x`, `position_y`, рівномірний `zoom`,
`rotation_degrees` та `opacity_percent`. Щонайменше одне поле обов'язкове.
Bridge відхиляє locked track, значення поза фіксованими межами та позицію поза
динамічною межею ±4 розміри поточного timeline. Мапінг на `Pan`, `Tilt`,
`ZoomGang`, `ZoomX`, `ZoomY`, `RotationAngle` і `Opacity` залишається всередині
Resolve provider; raw property names, expressions і keyframes через MCP
не приймаються. Opacity write/readback, replay без другого backup і відновлення
початкового значення перевірено у Resolve 21 Free 21.0.3.7.

`resolve_delete_clip` є єдиним destructive MCP tool. Він видаляє рівно один
video/audio TimelineItem без ripple і лише коли `confirm_delete=true`.
Application, transport schema та bridge незалежно перевіряють підтвердження,
destructive safety flag і обов'язковий backup. Масив IDs, linked-item expansion
та ripple-параметр зовнішньому клієнту не доступні. Видалення окремого
disposable item, replay без другого backup і незмінені первинні video/audio
counts перевірено у Resolve 21 Free 21.0.3.7.

## Безпечне редагування

Усі write-tools створюють `.drp` backup до зміни та підтримують необов'язковий
`idempotency_key`. Для `resolve_import_media` кожен шлях має бути абсолютним,
існувати й належати до `media.allowed_roots` у локальному `config.toml`.

MCP annotations позначають `resolve_delete_clip` як destructive, а решту
write-tools — як non-destructive. Автоматичного відновлення проєкту немає;
стратегія ручного відновлення описана в [rollback.md](rollback.md).
