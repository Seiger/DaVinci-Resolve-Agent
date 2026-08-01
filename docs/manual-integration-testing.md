# Ручне інтеграційне тестування

M30 визначає канонічну матрицю live-перевірок. Автоматизовані тести та
GitHub Actions перевіряють Python-код, контракти, bridge simulation й installer,
але не є доказом роботи всередині DaVinci Resolve.

Статуси:

- `verified` — сценарій фактично виконано у вказаному live-середовищі;
- `pending` — сценарій потрібний для покриття, але live-evidence ще немає;
- `blocked` — сценарій неможливо виконати з описаною перевіреною причиною.

## Матриця платформи

| Windows | Python | Resolve edition | Resolve version | Статус |
|---|---|---|---|---|
| 10 build 19045 | 3.12.10 | Free | 21.0.3.7 | `verified` |
| 10 | 3.10 | Free | 21.x | `pending` |
| 10 | 3.11 | Free | 21.x | `pending` |
| 11 | 3.10 | Free | 21.x | `pending` |
| 11 | 3.11 | Free | 21.x | `pending` |
| 11 | 3.12 | Free | 21.x | `pending` |
| 10 | 3.10–3.12 | Studio | 21.x | `pending` |
| 11 | 3.10–3.12 | Studio | 21.x | `pending` |

Verified-рядок фіксує середовище, у якому вже документувалися live M1–M20
операції. Він не означає, що кожна комбінація Python, Windows та edition
перевірена. GitHub Actions coverage для Python 3.10–3.12 залишається
автоматизованою package/bridge-simulation перевіркою, а не live Resolve
evidence.

## Матриця стану Resolve

| Edition | Project state | Timeline state | Очікуваний результат | Статус |
|---|---|---|---|---|
| Free | open | present | project і current timeline доступні | `verified` |
| Free | open | absent | project доступний, current timeline відсутній | `pending` |
| Free | none | not applicable | bridge відповідає без вигаданого project | `pending` |
| Studio | open | present | project і current timeline доступні | `pending` |
| Studio | open | absent | project доступний, current timeline відсутній | `pending` |
| Studio | none | not applicable | bridge відповідає без вигаданого project | `pending` |

`Timeline state = absent` означає відкритий проєкт без timeline.
`not applicable` використовується лише тоді, коли проєкт не відкрито.

## Мінімальний acceptance-сценарій

На кожній запланованій platform/state комбінації:

1. Виконати `installer/install.ps1` двічі.
2. Виконати `installer/verify.ps1 -SkipResolveConnection`.
3. Перезапустити Resolve та підготувати потрібний project/timeline state.
4. Запустити `Workspace → Scripts → Edit → ResolveBridge`.
5. Виконати повний `installer/verify.ps1`.
6. Виконати CLI `status` і `resolve project`.
7. Повторити read-only project operation через MCP.
8. Для write-сценарію окремо зафіксувати backup, readback та idempotent replay.

Stale cached heartbeat не зараховується як нове live-evidence. Якщо bridge
повертає `edition = "unknown"`, edition фіксується як operator-confirmed і не
видається за автоматично визначену capability.

## Evidence contract

Кожний live-запуск має зафіксувати:

- UTC timestamp;
- Windows caption, version і build;
- точну версію Python;
- Resolve product, version та спосіб підтвердження edition;
- agent, bridge і protocol versions;
- початковий project/timeline state;
- command або MCP tool і його exit code/status;
- sanitized result або ключовий readback;
- для write-операцій — backup, safety flags та replay result;
- підсумок `verified`, `pending` або `blocked`;
- відому причину failure без secrets і приватних media paths.

Evidence не повинно містити credentials, raw user configuration, приватні
media paths, повні command arguments або diagnostics bundles без попереднього
ручного перегляду.

## Поточне покриття

- Resolve 21 Free 21.0.3.7, Windows 10 build 19045, Python 3.12.10,
  project open, timeline present: `verified`;
- Codex project-scoped MCP → `video_agent_status` →
  `resolve_get_project(timeout_seconds=120)` → one-shot ResolveBridge → live
  project readback: `verified`;
- Python 3.10–3.12 package compatibility: автоматизовано в Windows CI;
- Windows 11 live Resolve: `pending`;
- Resolve 21 Studio: `pending`;
- live project absent і timeline absent: `pending`.

Новий рядок можна перевести у `verified` лише після фактичного live-запуску з
evidence за цим контрактом.

### M33 Codex MCP acceptance evidence

- UTC heartbeat: `2026-07-31T14:05:14.819536Z`;
- platform: Windows 10 build 19045, Python 3.12.10;
- Resolve: DaVinci Resolve 21.0.3.7 Free, edition operator-confirmed;
- versions: agent 0.1.0, bridge 0.1.0, protocol 1.0;
- initial state: project open, current timeline present;
- MCP server/tool: `davinci-resolve-agent.resolve_get_project`,
  `timeout_seconds=120`, status `completed`;
- sanitized readback: project name `DaVinci Agent M4 Test`;
- safety: read-only operation, no backup and no project mutation expected;
- result: `verified` for the full
  `Codex → MCP → AgentApplication → filesystem transport → ResolveBridge → Resolve`
  path;
- limitation: ResolveBridge was started once from the Resolve menu while the
  MCP tool waited; background bridge startup was not tested or claimed.

### M34 guarded rough-cut apply evidence

Статус: `pending`. Автоматичні тести підтверджують SHA-256 approval gate,
preview, idempotent receipt та блокування непідтверджених API. Вони не є
доказом live timeline mutation.

Перед live write потрібен окремий явний дозвіл оператора, бо перевірка
`timeline.duplicate` створює новий timeline і `.drp` backup. Після запуску
ResolveBridge ручний сценарій має зафіксувати:

1. свіжий `video_agent_status(max_age_seconds=120)`;
2. preview approved M5 plan: статус `blocked`, без command у filesystem queue;
3. окремий disposable plan лише з підтвердженою `timeline.duplicate`;
4. backup path, ID створеної копії, readback original та copy;
5. повтор apply з тим самим idempotency receipt без другого backup або копії;
6. фактичний список API, що лишилися `blocked` для M5 plan.

Без цього evidence `timeline.duplicate` і M34 live apply не позначаються як
`verified`.

### M35 persistent bridge and editing metadata evidence

- UTC heartbeat: `2026-07-31T18:26:04.019624Z`;
- platform: Windows 10 build 19045, Python 3.12.10;
- Resolve: DaVinci Resolve 21.0.3.7 Free, edition operator-confirmed;
- lifecycle: manual menu start, `persistent`, 0.5-second polling;
- UI: operator-confirmed responsive while the bridge loop was active;
- sequential commands without another menu invocation: cached status, `ping`,
  current project and workspace snapshot;
- MCP metadata readback: timeline `M7 Render Source Test`, one video track,
  one audio track, two explicitly requested MKV assets;
- sanitized asset results: `447272` frames at `60.0` FPS and `447300` frames
  at `60.0` FPS;
- safety: metadata operation read-only, no backup and no project mutation;
- clean shutdown: `resolve_stop_bridge` returned `status=stopping`, persisted
  lifecycle state became `stopped`;
- result: `verified` on this exact environment; other Resolve versions and
  editions remain pending.

### M36 bounded timeline track preparation evidence

- UTC execution: `2026-07-31T18:44:06Z` through `2026-07-31T18:44:07Z`;
- platform: Windows 10 build 19045, Python 3.12.10;
- Resolve: DaVinci Resolve 21.0.3.7 Free, edition operator-confirmed;
- target: disposable `M36 Track Preparation Probe`, canonical timeline ID
  `454dd6ad-0114-425f-ab51-53364fcc0c32`;
- initial readback: one video and one audio track;
- operation: `ensure_timeline_tracks(video=2, audio=1)` added exactly one video
  track after exporting a separate `.drp` backup;
- result readback and independent `get_editing_metadata`: two video and one
  audio track;
- replay: the same idempotency key returned the same result and backup path,
  without another added track or backup;
- durable capability: `timeline.track.create=true` after verified execution;
- result: `verified` on this exact environment; other Resolve versions and
  editions remain pending.

### M37 target timeline frame-rate evidence

- UTC readback: `2026-08-01T08:49:18Z`;
- platform: Windows 10 build 19045, Python 3.12.10;
- Resolve: DaVinci Resolve 21.0.3.7 Free, edition operator-confirmed;
- target: `M36 Track Preparation Probe`, canonical timeline ID
  `454dd6ad-0114-425f-ab51-53364fcc0c32`;
- bounded timeline result: two video tracks, one audio track, `24.0` FPS;
- bounded source result: `447300` frames at `60.0` FPS;
- safety: read-only MCP operation, no new `.drp` backup, latest backup remained
  the M36 write from `2026-07-31T18:44:07Z`;
- result: `verified` and confirms that source FPS cannot be assumed to equal
  target timeline FPS; other Resolve versions and editions remain pending.

### M38 synchronized pair assembly evidence

- UTC execution: `2026-08-01T09:06:13Z` through `2026-08-01T09:07:04Z`;
- platform: Windows 10 build 19045, Python 3.12.10;
- Resolve: DaVinci Resolve 21.0.3.7 Free, edition operator-confirmed;
- approved M5 synchronization input: `webcam_offset_ms=0`, correlation `1.0`;
- target: one new `M38 Synchronized Pair Test`, canonical timeline ID
  `5edf4ca3-8db0-44ef-a74f-40fbe08c51ec`, target FPS `24.0`;
- source metadata: screen `447300` and webcam `447272` frames at `60.0` FPS;
- track preparation: 1V/1A → 2V/1A;
- readback: screen video on V1, screen audio on A1, webcam video on V2, all at
  timeline start; three distinct canonical TimelineItem IDs;
- Resolve clamped requested inclusive source ends by one to two frames to the
  actual stream extents; bounded readback recorded `447297` and `447270`;
- safety: five `.drp` backups for five initial primitive writes; replay returned
  the identical SHA-256 receipt with no second timeline, item, or backup;
- workflow audit: two successful `editing` records, neither containing inputs
  nor results;
- result: `verified` on this exact environment; positive/negative non-zero
  offsets remain simulation-tested, and other versions/editions remain pending.

### M39 synchronized webcam picture-in-picture evidence

- UTC execution: `2026-08-01T14:21:06Z`;
- platform: Windows 10 build 19045, Python 3.12.10;
- Resolve: DaVinci Resolve 21.0.3.7 Free, edition operator-confirmed;
- source: applied M38 receipt `09e1cdece4e1d2b8f848059422691bec6cabb9952cf351706148d9e26f048b2a`;
- target: webcam TimelineItem `2eb5e9ef-42ac-4b23-982d-04340b6197f2` on V2
  of `M38 Synchronized Pair Test`;
- bounded metadata: target resolution 1920×1080;
- normalized input: size `25%`, center X/Y `82%/82%`;
- exact readback: Pan `614.4`, Tilt `-345.6`, ZoomX/ZoomY `0.25`, ZoomGang
  enabled; previous values were Pan/Tilt `0/0`, ZoomX/ZoomY `1.0`;
- safety: one `.drp` backup, canonical SHA-256 layout receipt
  `2f196e85b811f3c9bb14ba7203b5a01f77f4316405e54dcf1b63c97f6d597894`;
- replay: backup count remained 37 before and after, with the identical receipt;
- result: `verified` on this exact environment; masks, crop, borders, Fusion,
  and other Resolve versions/editions remain outside verified scope.
