# Roadmap DaVinci Resolve Agent

## Межа v1

Версія v1 має дозволяти Codex змонтувати та перевірити готове відео за
вказівками користувача, зберігаючи оригінали й використовуючи лише
документовані та live-підтверджені можливості активного provider.

До обов'язкової межі v1 входять:

- повний керований шлях від локальних source-файлів до перевіреного render;
- очищення та інтеграція звуку;
- транскрипція, субтитри й декларативні editing recipes;
- керовані титри, zoom та reframing;
- B-roll;
- складні анімації;
- кольорокорекція;
- розумний вибір дублів;
- end-to-end acceptance на чистому підтримуваному Windows-комп'ютері.

## Заплановані milestones

- **M45** — контрольований старт finalized render і перевірка MP4.
- **M46 — завершено** — інтеграція очищеного звуку в timeline: керований
  audio-only WAV export, потокова локальна обробка, validation gate і bounded
  A2 replacement із вимкненням source A1.
- **M47 — завершено** — native capability probe, локальна українська
  faster-whisper транскрипція, deterministic SRT та backup-backed apply з
  canonical subtitle readback.
- **M48 — завершено** — пакетовані allowlisted MCP editing recipes,
  capability-aware preview, confirmed execution і durable per-step replay.
- **M49 — завершено** — confirmed append-only standard-title
  insertion за exact timecode та provider-neutral static zoom/reframing із
  preview, capability gates, unchanged-item verification і durable replay;
  Smart Reframe/Fusion виключені.
- **M50 — завершено** — mandatory M43/M46 core, optional M47/M49 enhancements,
  canonical receipt convergence, read-only live QA та deterministic confirmed
  render через перевірені M44/M45 примітиви; live 1080p acceptance і exact
  replay перевірені в Resolve 21.0.3 Free.
- **M51 — завершено** — explicit video-only
  B-roll planning, deterministic review ID, completed-M50 binding і confirmed
  bounded application на duplicate timeline з canonical readback; live preview,
  confirmed apply та exact replay перевірені в Resolve 21.0.3 Free.
- **M52 — завершено** — пакетований
  allowlisted Fusion Title, hash-verified Windows install, M51-bound preview,
  confirmed duplicate-timeline apply і durable replay без довільного Fusion
  input через MCP; mirrored Anim Curves та exact replay перевірені live у
  Resolve 21.0.3 Free.
- **M53 — завершено** — пакетований CDL preset, documented color-graph
  discovery, M52-bound deterministic preview і confirmed duplicate-timeline
  apply; 5/5 managed versions, exact replay та visual acceptance підтверджені
  у Resolve 21.0.3 Free.
- **M54 — у роботі** — bounded full-file та segment-level technical analysis,
  script-aware dialogue matching, deterministic ranking і immutable
  approve/reject review, а також ordered approved sequence handoff без
  автоматичної модифікації timeline.
- **M55 — у роботі** — повний creative v1 end-to-end acceptance і repeatable
  install test; M55.1 додає allowlisted machine-local source binding для
  approved M54 sequence, а M55.2 — deterministic path-redacted assembly
  preview з локальними media metadata та послідовними ranges. M55.3 прив'язує
  його до exact live timeline FPS/resolution і формує frame mapping; усі три
  етапи працюють без import або timeline write. M55.4 формує conservative
  Media Pool import preview, дедуплікує sources і блокує ambiguous same-name
  collisions до review. M55.5 виконує лише exact confirmed source batch import,
  створює backup, перевіряє metadata/Media Pool readback і зберігає durable
  path-redacted receipt без timeline mutation. M55.6 формує exact preview і
  confirmed V1/A1 assembly лише на duplicate порожнього source timeline,
  перевіряє source/target readback та відновлює interrupted apply покроково.
  M55.7 додає structural QC exact sequence, явний перелік ще не перевірених
  creative шарів та immutable human acceptance без timeline mutation. M55.8
  прив'язує approved QC до exact confirmed 1080p/4K render і перевіряє live job
  та непорожній MP4 лише у configured managed output root. M55.9 синхронізує
  повний M54/M55 directory inventory між Python та Windows installer/verify і
  перевіряє його в ізольованому install/rerun/uninstall lifecycle.

Milestone може бути розділений на discovery/preview/apply підетапи, якщо
Resolve API або безпечне live-тестування цього потребують. Roadmap не є заявою
про доступність конкретної функції у DaVinci Resolve 21 Free: unsupported або
недокументовані можливості повинні блокуватися, а не емулюватися припущеннями.
