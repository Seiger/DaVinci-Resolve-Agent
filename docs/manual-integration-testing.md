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

### M40 synchronized screen link evidence

- UTC execution: `2026-08-01T14:25:08Z` through `2026-08-01T14:30:38Z`;
- platform: Windows 10 build 19045, Python 3.12.10;
- Resolve: DaVinci Resolve 21.0.3.7 Free, edition operator-confirmed;
- source: applied M38 receipt `09e1cdece4e1d2b8f848059422691bec6cabb9952cf351706148d9e26f048b2a`;
- target: screen video V1 `c24dbed9-da23-4333-8796-047c3d865642` and screen
  audio A1 `606cfc81-73a7-4a66-a2d7-cc57bd7c63e6`;
- primitive probe: previous links were empty, then each item reported the
  other's canonical ID and capability changed to `clip.link=true`;
- workflow: applied receipt
  `9a17e91ea9650d5ed4e3e15b78e577d03fbb252c0de0c444b0e9a78b94ab99de`;
- safety: one `.drp` backup for the primitive probe and one for the first
  workflow invocation; webcam V2 and all other timeline items were untouched;
- replay: backup count remained 39 before and after, with the identical receipt;
- result: `verified` on this exact environment; future move/trim/split behavior
  over linked items remains outside verified scope.

### M41 pause compaction preview evidence

- UTC execution: `2026-08-01T14:36Z`;
- platform: Windows 10 build 19045, Python 3.12.10;
- Resolve: DaVinci Resolve 21.0.3.7 Free, edition operator-confirmed;
- inputs: approved M5 plan
  `c0d5d8a6bb6ce60fd085faceb9ad8a9a69290dac1cec07a15bf2c064dd548793`
  and applied M38 receipt
  `09e1cdece4e1d2b8f848059422691bec6cabb9952cf351706148d9e26f048b2a`;
- metadata: target 24 FPS, both source assets 60 FPS, bounded source duration
  7,455,000 ms;
- cut: half-open `320..880 ms`, removed duration 560 ms;
- output preview: 7,454,440 ms / 178,907 target frames, two kept intervals,
  six exact V1/A1/V2 placements;
- readiness: no unsupported future apply capabilities reported;
- safety: backup count remained 39 before and after; no timeline or item was
  created, modified, or deleted;
- bridge reliability: after installing the M41 bridge, 2,000 concurrent state
  reads completed and the bridge remained `ready`; the following online
  `verify.ps1` reported a 0.3 s heartbeat age;
- result: `verified` read-only preview on this exact environment; actual
  compacted timeline creation was verified separately in M42.

### M42 pause compaction apply evidence

- UTC execution: `2026-08-01T16:09Z`;
- platform: Windows 10 build 19045, Python 3.12.10;
- Resolve: DaVinci Resolve 21.0.3.7 Free, edition operator-confirmed;
- inputs: M41 plan
  `c0d5d8a6bb6ce60fd085faceb9ad8a9a69290dac1cec07a15bf2c064dd548793`
  and applied M38 receipt
  `09e1cdece4e1d2b8f848059422691bec6cabb9952cf351706148d9e26f048b2a`;
- preview: `apply_supported=true`, no unsupported capabilities, one 560 ms cut,
  two kept intervals, six placements, and 178,907 target frames;
- target: `M42 Pause Compaction Apply`, canonical timeline ID
  `7e430372-841d-4f6f-99ac-8647f6d75a31`;
- apply receipt:
  `b645865e2743554f2f20e5cc3109b72e7a86b6017aef620fd779509f859fe33d`;
- result: create timeline, ensure tracks, and one six-placement batch insert all
  reported `applied`; final `list_timeline_items` found 6/6 canonical IDs;
- source safety: project timeline count changed 7 to 8, while all 3/3 canonical
  M38 source items remained present;
- backups: 39 to 42, exactly one distinct `.drp` for each of the three write
  steps; immediate replay remained at 8 timelines and 42 backups;
- frame readback: both kept segments began at target offsets 0 and 8 frames;
  the second segment used source frame 53, confirming a non-zero ranged insert;
- result: `verified` on this exact environment. Screen video/audio segment
  linking and webcam picture-in-picture propagation are not part of M42.

### M43 compacted timeline finalization evidence

- UTC execution date: `2026-08-01`;
- M43 receipt:
  `2daf23ae6a33d75f015cc9d13decca545af8410ec744979c6e3f163ccb87df32`;
- target: M42 timeline `7e430372-841d-4f6f-99ac-8647f6d75a31`;
- result: two independent screen V1/A1 link groups, two webcam PIP transforms,
  and 6/6 canonical item identities verified;
- backups: 42 to 44; immediate replay remained at 44.

### M44 finalized render preparation evidence

- UTC execution: `2026-08-01T16:59Z`;
- input: applied M43 receipt
  `2daf23ae6a33d75f015cc9d13decca545af8410ec744979c6e3f163ccb87df32`;
- M44 receipt:
  `5d03b799bdaa588b20e080f7b59dbc9ae47e617ec6a1c6f50bfbedf0c3b730c5`;
- prepared job: `926b8633-a03b-4a25-a572-f1d18680c3e5`;
- queue binding: `M42 Pause Compaction Apply`, canonical timeline ID
  `7e430372-841d-4f6f-99ac-8647f6d75a31`;
- profile: `youtube-1080p-h264-v1`, MP4/H.264, 1920×1080;
- status: `Ready`, zero percent, `rendering_in_progress=false`;
- backups: 44 to 45; immediate replay remained at 45 and returned the same
  receipt without adding another job;
- result: `verified` preparation only. Render was intentionally not started.

### M45 finalized render execution evidence

- UTC completion: `2026-08-01T18:00Z`;
- input: applied M44 receipt
  `5d03b799bdaa588b20e080f7b59dbc9ae47e617ec6a1c6f50bfbedf0c3b730c5`;
- M45 receipt:
  `c14ef11f8e90071cc0ad6d4db88cefba798095289683f664e1cf95c769b44f74`;
- job: `926b8633-a03b-4a25-a572-f1d18680c3e5`, exact M42 timeline
  `7e430372-841d-4f6f-99ac-8647f6d75a31`;
- terminal readback: `Complete`, 100%, `rendering_in_progress=false`,
  `TimeTakenToRenderInMs=2462603`;
- output: managed `M44 Finalized Timeline Test.mp4`, 2,094,070,933 bytes;
- validation: completed, managed path, and non-empty checks all passed;
- backups: start created backup 45 to 46; immediate and post-completion replay
  returned the same receipt and remained at 46 without another render start;
- result: `verified` on Resolve 21 Free 21.0.3.7 in Windows 10.

### M46 cleaned-audio integration evidence

- UTC execution: `2026-08-01T18:58Z` through `2026-08-01T19:27Z`;
- extraction receipt:
  `5c54b2eba322013e6149897be2bca4da65dff507a94dbc81e9f74c3bd80262d5`;
- job `1cb90cf4-7d70-4711-a815-a13bc7c8e920`: built-in `Audio Only`,
  Wave/lpcm, 16-bit/48 kHz stereo, `Complete`/100%, 261793 ms;
- extracted WAV: 357812000 sample frames, 7,454,417 ms,
  1,431,249,588 bytes, uncompressed PCM;
- streaming v2 report:
  `091a64d764c7406db37d4b186c9e93f3f6692a3b7f86483582990551dee38cfa`;
- processing readback: RMS `-24.746` → `-20.001 dBFS`, peak `0.0` →
  `-1.0 dBFS`, clipped samples `10` → `0`, `target_met=true`;
- integration receipt:
  `f9f037abe3ac934725960c1e9f88cb2e521c623460e4d954463d3b37af5483ab`;
- exact placement: A2 item `f62bb0e6-c2c2-46db-b0b2-01c970e3c63f`,
  timeline frames `86400..265306`, duration 178906 frames;
- both canonical A1 items reported `enabled=false`; their linked V1 peers
  reported `enabled=true` before and after the explicit safety operation;
- backups: successful extraction prepare/start used 48→50; integration import,
  track creation, insertion, two A1 disables, and two V1 confirmations ended at
  57; immediate replay remained at 57 with one A2 item;
- result: `verified` on Resolve 21 Free 21.0.3.7 in Windows 10. RMS dBFS remains
  a reference metric, not a LUFS/EBU R128 delivery claim.

### M47 local transcription and subtitle evidence

- UTC execution date: `2026-08-01`;
- environment: Resolve 21 Free 21.0.3.7, Windows 10, Python 3.12.10;
- read-only native discovery: `CreateSubtitlesFromAudio` and all required
  constants present; no initial subtitle track on M42;
- native write probe on disposable M34: Resolve returned `False`; structured
  `AUTO_CAPTION_UNAVAILABLE`, backup preserved, capability stayed unverified;
- SRT behavior probe: one local SRT imported and appended to `Subtitle 1`,
  canonical item `fba921bf-b914-482a-98c7-299761e0c160` read back;
- local backend: pinned faster-whisper 1.2.1, `small`, CPU/int8, Ukrainian;
- 60-second speech probe: 4 segments, `language=uk`, probability `1.0`;
- applied receipt:
  `811611522f48183ede4aa456864015a74af4dd859bc4488c3fff8eb88e93ffc5`;
- target: disposable M34 timeline
  `07fce28c-00ee-487d-9935-ff701405d48d`;
- readback: subtitle count `1 → 5`, all four generated Ukrainian texts with
  canonical IDs and frame bounds; import and append each created one `.drp`
  backup;
- exact append-placement recovery on M10 timeline
  `f98c1e47-fa2e-4d7d-bcdf-e402f91d0a02`: receipt
  `62c2fd44eba89aa5b9575645f169593dbe01742195340b6a8e477d8bbeaae3ad`,
  pre-write append frame `86496`, first transcript offset `183` frames, and
  expected/actual first subtitle frame `86679`;
- crash-recovery replay reused the existing import/append provider receipts:
  subtitle items stayed `4 → 4`, backups stayed `64 → 64`, and the same four
  canonical TimelineItem IDs were independently read back;
- result: local transcription → deterministic SRT → Resolve subtitle apply
  is `verified`; native Resolve AI captioning is unsupported in this Free
  environment.

### M48 declarative editing recipe evidence

- UTC execution date: `2026-08-02`;
- environment: Resolve 21 Free 21.0.3.7, Windows 10, Python 3.12.10;
- MCP recipe: `tutorial-layout-v1` over canonical M38 receipt
  `09e1cdece4e1d2b8f848059422691bec6cabb9952cf351706148d9e26f048b2a`;
- discovery returned one packaged recipe; preview returned `ready` with exact
  ordered actions `compose_webcam_picture_in_picture` then
  `link_synchronized_screen_pair`;
- applied recipe receipt:
  `bc4119ed1f0c0f940bf252d700c35d9db62058a9f8bb2f20d62519f3dd6dd8fc`,
  bound to recipe definition SHA-256
  `8cd6bb498197621d00088d557b01efda4aafcc4fac532b08273d26fba1602215`;
- both steps returned `applied`; immediate replay returned an identical receipt;
- underlying M39/M40 receipts were reused, so Resolve backups stayed `64 → 64`;
- result: packaged recipe discovery, read-only preview, confirmed execution and
  idempotent replay are `verified` through the MCP server on this environment.

### M49 standard-title and static reframing acceptance

1. Перезапусти встановлений `ResolveBridge` після оновлення його source.
2. На disposable timeline вибери один video item і виклич
   `preview_visual_treatment` з малим статичним zoom та одним title `Text`.
3. До першої title-вставки preview має показати `title.insert` як unverified.
4. Виклич `resolve_insert_title` із `confirm_insert=true` на безпечному
   timecode; перевір canonical item, backup і повернення playhead.
5. Повтори preview: `title.insert` має бути verified і `ready=true`.
6. Виклич `apply_visual_treatment(confirm_apply=true)`, звір transform/title
   у Resolve, потім повтори exact request і переконайся, що receipt і кількість
   backups не змінилися.

Зафіксуй Resolve edition/version, timeline/item IDs, timecode, receipt ID,
backup count до/після та exact readback. Не використовуй `SmartReframe`, Fusion
controls або production timeline для першої acceptance-перевірки.

### M49 live evidence

- UTC execution date: `2026-08-01`;
- environment: Resolve 21 Free 21.0.3.7, Windows 10, Python 3.12.10;
- disposable timeline: `M34 Disposable Duplicate Probe`, ID
  `07fce28c-00ee-487d-9935-ff701405d48d`;
- occupied `01:00:02:00` placement returned `TITLE_APPEND_ONLY`; item map and
  backup count stayed unchanged at 68;
- confirmed visual-treatment receipt:
  `bd62161bf24bdcd05cc5ca58bb1727a647a63f592a1f13ffd9a8c30e64790877`;
- transform readback: `ZoomGang=true`, `ZoomX=1.16`, `ZoomY=1.16`;
- standard `Text` requested at `01:01:15:00`, absolute frame 88200; exactly one
  generated video item `fbe0c09d-fa5e-432e-9701-8379ea10348b` appeared at
  frames `88200..88320`, with null source bounds and duration 120 frames;
- all prior video item start/end/duration/track snapshots remained unchanged;
- confirmed apply created two backups `68 → 70`; exact replay returned the same
  receipt and item map with backups stable at 70;
- result: append-only standard-title insertion plus static zoom/reframing is
  `verified` on this Resolve 21 Free environment. Smart Reframe, title-text
  mutation, Fusion controls and animated templates remain outside M49.

### M50 baseline end-to-end acceptance

Статус: `verified` у DaVinci Resolve 21.0.3 Free 2 серпня 2026 року. Bridge M50
не змінює, тому достатньо вже запущеної сумісної сесії ResolveBridge.

1. На одному disposable final timeline підготуй applied M43 і M46 receipt.
   M47/M49 передавай лише як опційні enhancement receipt з того самого
   timeline. Не використовуй M47/M49 receipt з M34, якщо M43/M46 належать M42.
2. Виклич `preview_baseline_edit` з M43/M46 та, за наявності, M47/M49 receipt
   IDs. Очікується
   `status=ready`, усі checks `passed`, без backup або render job.
3. Окремо підтвердь `start_baseline_render(confirm_render=true)` з новим
   `custom_name` та allowlisted 1080p/4K profile.
4. Зафіксуй M50, M44 і M45 receipt IDs, deterministic render name, job ID та
   backup count.
5. Опитуй `get_baseline_render_status`, доки він не поверне `complete`; звір
   `JobStatus=Complete`, managed path, ненульовий MP4 і повторно успішний QA.
6. Повтори exact start request: receipt, job ID та backup count не повинні
   змінитися.

Live acceptance має зафіксувати Resolve edition/version, timeline ID,
обов'язкові й передані опційні input receipt IDs, профіль, output size та
точний результат replay. Для поточного M42 acceptance застосовуй M49 лише з
static transform без append-only title; M47 не додавай, доки SRT placement на
непорожньому timeline не буде вирівняно й окремо підтверджено.

Фактичний M50 acceptance виконано на `M42 Pause Compaction Apply`
(`7e430372-841d-4f6f-99ac-8647f6d75a31`) лише з core M43/M46:

- QA: 6 passed, 0 failed;
- M50 receipt: `e291c710c569f1cdb8fc4d1cda30c5c75e898217534623a0528125924221c78a`;
- M44 receipt: `39a13fd725f6472fda51f05ddc0b43abfe48cb5ce15917dd6227fc147229224a`;
- M45 receipt: `c91e318cf83c56a5be9b84526330ef57a5180b9e188a697af113c6305eb48f2e`;
- profile: `youtube-1080p-h264-v1`, 1920×1080, H.264/MP4, 24 fps, AAC;
- job ID: `5997af88-9c3a-4d92-9f7b-858385f82e15`;
- output: `M50 Baseline Acceptance-e291c710c569.mp4`, 2 094 880 932 bytes;
- output SHA-256: `84d870ffdcf2ee2a908cc02e57d772544e13acad05bb3189856ac6579cc4eff6`;
- M44/M45 створили два safety backups; exact replay зберіг усі receipt і job
  ID без нового job.
