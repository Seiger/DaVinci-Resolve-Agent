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

## Preset

Єдиний дозволений preset — `pcm-dialogue-level-v1`:

- target RMS: `-20 dBFS`;
- peak ceiling: `-1 dBFS`;
- tolerance: `±0.5 dB`;
- gain обмежується peak guard.

Preset не заявляє denoise, de-reverb, EQ або compression. Він виконує лише
детерміноване gain leveling.

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
Для їх навмисного видалення передай:

```powershell
.\installer\uninstall.ps1 `
    -PreserveAudioReports $false `
    -PreserveProcessedAudio $false
```
