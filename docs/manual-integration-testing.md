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
