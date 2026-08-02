# M54: технічний аналіз і review вибору дублів

M54 виконує локальний bounded analysis. `analyze_take_candidates` приймає від
2 до 8 явно названих кандидатів лише з `media.allowed_roots`. Один виклик має
містити кандидатів лише одного режиму:

- повні файли: `{candidate_id, path}`;
- сегменти: `{candidate_id, path, start_seconds, end_seconds}`.

Для сегментів діє `0 <= start_seconds < end_seconds`, максимальна тривалість —
300 секунд. Той самий файл можна передати кілька разів з різними candidate ID і
діапазонами. Шляхи перевіряє наявний `MediaPolicy`; абсолютні шляхи не
потрапляють у selection report.

Fixed policy `technical-take-v1` вимірює:

- сім відеокадрів у фіксованих позиціях;
- exposure, contrast, edge detail і near-black ratio;
- bounded audio sample до 480000 mono samples;
- RMS, peak, clipping і silence ratio;
- resolution, FPS та duration.

У segment mode кадри й аудіо декодуються лише всередині заявленого source
range, а report version `1.1` зберігає діапазон біля кожного кандидата. Старий
full-file report version `1.0` і його API залишаються сумісними.

Декодування виконує явно задекларована Python-залежність PyAV; зовнішній
`ffmpeg.exe` та shell-команди для цього workflow не запускаються.

Результат ранжується детерміновано і завжди має `pending_review`. Recommendation
оцінює лише технічну якість: вона не розуміє зміст, акторську гру, правильність
репліки або драматургію.

`review_take_selection` приймає тільки `approve` з конкретним candidate ID або
`reject` без candidate ID. Review immutable, прив'язаний SHA-256 до exact
selection і повертає `timeline_modified=false`. На цьому slice approval не
змінює Resolve і не підставляє рекомендований файл у монтаж автоматично.

`get_take_selection` і `list_take_selections` читають локальні artifacts без
ResolveBridge. Жоден M54 tool не приймає Python/Lua/PowerShell, FFmpeg arguments,
довільні scoring weights або executable input.

## Live smoke test

2 серпня 2026 року bounded analysis двох allowlisted синхронних MKV-файлів
завершився з усіма 7 video samples і 480000 audio samples для кожного файла.
Exact replay повернув той самий selection
`2548a854ab96a6b27321a979d46365dce0cf909068ba356005686fe4e4dad679`;
`get` і `list` підтвердили persisted artifact, а absolute source paths у report
відсутні. Статус лишився `pending_review`: camera і screen recording є
комплементарними синхронними джерелами, а не взаємозамінними дублями, тому їхній
technical rank не слід автоматично перетворювати на creative edit decision.

M54.2 додатково перевірено на двох 10-секундних ranges одного 41,4 ГБ
allowlisted MKV на диску G. Обидва кандидати дали 7/7 video samples і bounded
audio, exact replay повернув selection
`bf51e004dba7e3f57f5fb476a143f4e14cb1a5ab59dc251652d85929013f2cf3`, а
persisted report записано в configured runtime на G без source path. Review не
створювався, timeline не змінювався.
