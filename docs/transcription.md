# Локальна транскрипція та субтитри

M47 використовує два незалежні шляхи:

1. `resolve_get_subtitle_environment` без змін читає subtitle tracks/items та
   перевіряє наявність native auto-caption API.
2. `generate_subtitles` локально транскрибує дозволений source-файл, створює
   UTF-8 SRT і додає його до одного canonical timeline через backup-backed
   `import_media` та receipt-bound `append_subtitle_file`.

Resolve 21 Free 21.0.3.7 expose-ить документований
`CreateSubtitlesFromAudio`, але live-виклик повертає `False`. Тому native tool
залишається capability-gated і не видається за робочий шлях у Free.

## Локальний backend

Інсталятор встановлює pinned `faster-whisper==1.2.1`. Фіксована політика v1:

- multilingual model `small`;
- `language="uk"`, task `transcribe`;
- CPU з `int8`, тому CUDA не є вимогою;
- beam size 5 і VAD;
- максимум 10000 неперекривних сегментів;
- жодного shell, PowerShell або довільного executable invocation.

Під час першого запуску модель завантажується у
`%LOCALAPPDATA%\DaVinciResolveAgent\runtime\models\faster-whisper`. Після
цього inference використовує локальний кеш. Артефакти SRT зберігаються у
`<DataRoot>\media\subtitles`, а receipts — у
`<DataRoot>\runtime\subtitle-receipts`.

## Safety та replay

`generate_subtitles` вимагає `confirm_apply=true`, абсолютний source path у
`media.allowed_roots` і canonical timeline ID. Workflow спочатку читає
наявні subtitle IDs, потім транскрибує, атомарно записує SRT, виконує рівно
один import та append і звіряє всі нові canonical IDs. Кількість нових items
має точно дорівнювати кількості transcript segments. SHA-256 receipt робить
повторний виклик без другого імпорту або append.

Документований `MediaPool.AppendToTimeline()` додає SRT відносно кінця
таймлайна перед операцією, а не відносно playhead. Bridge тому повертає
`append_frame`, а workflow перевіряє точний перший кадр як
`append_frame + transcript offset`. Поточний контракт не обіцяє вставлення
субтитрів у довільну середину вже змонтованого таймлайна.

Якщо процес завершився після provider write, але до локального workflow
receipt, повторний виклик приймає вже наявні items лише за точного збігу з
idempotent append receipt та незалежним readback. Для старого provider receipt
без `append_frame` anchor відновлюється з підтверджених item frames і має
`append_frame_source="recovered_provider_receipt"`.

Оригінальний source не змінюється. Модель, prompt, raw Resolve settings і
довільний код через MCP не приймаються.
