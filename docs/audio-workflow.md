# Audio workflow у M6

M6 додає незалежний від Resolve workflow для аналізу й детермінованого
вирівнювання діалогового аудіо. Оригінальний файл ніколи не перезаписується.

## Підтримуваний формат

Reference backend використовує лише стандартну бібліотеку Python і приймає:

- нестиснений PCM WAV;
- 16-bit sample width;
- один або більше каналів;
- довільну коректну sample rate.

M6 не декодує MKV/MP4, не запускає FFmpeg та не виконує shell-команди.

## Аналіз

Before/after report містить:

- тривалість, sample rate і кількість каналів;
- RMS level у dBFS;
- sample peak у dBFS;
- кількість clipped samples;
- частку тихих 20 ms вікон;
- SHA-256 оригіналу й похідного файлу.

RMS dBFS не є LUFS або EBU R128. Це навмисно чесне обмеження reference
backend. Delivery loudness потрібно буде перевіряти окремим підтвердженим
FFmpeg/EBU R128 backend.

## Presets

Підтримуються два версійовані presets із однаковими цілями:

- target RMS: `-20 dBFS`;
- peak ceiling: `-1 dBFS`;
- tolerance: `±0.5 dB`;
- `pcm-dialogue-level-v1` обмежує gain через peak guard;
- `pcm-dialogue-limit-v2` застосовує nominal RMS gain, детермінований hard
  limiter і фінальний peak ceiling.

Presets не заявляють denoise, de-reverb, EQ або perceptual compression. V1
виконує лише gain leveling, v2 додає sample limiter. Обробка й аналіз читають
WAV чанками та не завантажують повний файл у пам'ять.

## MCP і результати

Інструмент `clean_dialogue_audio` приймає абсолютний allowlisted шлях до PCM
WAV. Він не звертається до Resolve bridge.

Read-only інструменти:

- `list_audio_reports(limit=100)` повертає bounded summaries без локальних
  шляхів до source або derived файлів;
- `get_audio_report(report_id)` приймає рівно 64 lowercase hexadecimal
  символи та повертає повний повторно валідований report.

Обидва інструменти працюють без Resolve bridge, не аналізують і не змінюють
медіа. Canonical JSON із валідним іменем, але неправильним контрактом або
невідповідним `report_id`, спричиняє явну помилку.

Похідний WAV створюється в:

```text
%USERPROFILE%\Videos\DaVinciResolveAgent\processed\
```

Канонічний JSON-report зберігається в:

```text
%LOCALAPPDATA%\DaVinciResolveAgent\runtime\audio-reports\
```

Однаковий source path, SHA-256 джерела й той самий preset повертають наявний
report та не створюють дубліката.

## Видалення

Audio reports і derived audio зберігаються під час uninstall за замовчуванням.

## M46: extraction finalized timeline audio

Перший підетап M46 отримує повну вже скомпоновану аудіодоріжку applied M43
timeline через фіксований Resolve preset `Audio Only`. Він не приймає format,
codec, sample rate або довільний output path від MCP-клієнта.

- `prepare_finalized_timeline_audio` створює один Ready job без старту;
- `start_finalized_timeline_audio` вимагає окреме `confirm_render=true`;
- `get_finalized_timeline_audio_status` є read-only і приймає output лише при
  `Complete`/100%, у керованій директорії та у форматі незжатого 16-bit PCM WAV
  з частотою 48 kHz.

Файли extraction зберігаються в:

```text
%USERPROFILE%\Videos\DaVinciResolveAgent\audio-sources\
```

`apply_finalized_timeline_audio` завершує M46 і вимагає:

- completed extraction із `validation.passed=true`;
- completed `pcm-dialogue-limit-v2` report із `target_met=true`;
- exact source path і duration, що збігається з `MarkIn`/`MarkOut` extraction;
- явне `confirm_apply=true`.

Workflow імпортує рівно один derived WAV, забезпечує stereo A2, вставляє його
на повний extraction range, вимикає лише canonical A1 items із M43 finalization
та явно підтверджує `enabled=true` для їхніх linked video peers. Кожен write
має backup та idempotency key; progress receipt зберігається в
`%LOCALAPPDATA%\DaVinciResolveAgent\runtime\finalized-audio-integrations\`.

Live M46 у Resolve 21 Free 21.0.3.7 підтвердив:

- extraction job `1cb90cf4-7d70-4711-a815-a13bc7c8e920`: Wave/lpcm,
  16-bit/48 kHz stereo, 1 431 249 588 bytes;
- v2 report `091a64d764c7406db37d4b186c9e93f3f6692a3b7f86483582990551dee38cfa`:
  RMS `-20.001 dBFS`, peak `-1.000 dBFS`, 0 clipped samples;
- integration receipt
  `f9f037abe3ac934725960c1e9f88cb2e521c623460e4d954463d3b37af5483ab`:
  один A2 item на frames `86400..265306`, source A1 disabled, linked V1 enabled;
- replay залишив 57 backups і один A2 item без повторної зміни.

Для їх навмисного видалення передай:

```powershell
.\installer\uninstall.ps1 `
    -PreserveAudioReports $false `
    -PreserveProcessedAudio $false
```
