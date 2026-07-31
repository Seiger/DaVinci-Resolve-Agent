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
- Python 3.10–3.12 package compatibility: автоматизовано в Windows CI;
- Windows 11 live Resolve: `pending`;
- Resolve 21 Studio: `pending`;
- live project absent і timeline absent: `pending`.

Новий рядок можна перевести у `verified` лише після фактичного live-запуску з
evidence за цим контрактом.
