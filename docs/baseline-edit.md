# M50: baseline end-to-end монтаж і QA

M50 з'єднує вже перевірені етапи монтажу в один контрольований шлях до
фінального render. Він не додає нових Resolve API і не приховує відсутні
можливості.

## Вхідні артефакти

Baseline QA завжди вимагає два канонічні applied receipt:

- M43 finalization rough cut;
- M46 cleaned-audio integration.

M47 subtitle generation і M49 visual treatment є опційними enhancement
receipt. Якщо їх передано, M50 валідовує їх так само строго. Усі передані
receipt повинні посилатися на один `timeline_id`; receipt з попередніх
disposable probes не можна змішувати з фінальним timeline.

## MCP tools

`preview_baseline_edit` є read-only. Він:

- повторно валідовує обов'язкові та всі передані опційні JSON-контракти й
  canonical receipt IDs;
- перевіряє єдиний timeline;
- читає актуальні video/audio items, а subtitle environment — лише для M47;
- звіряє IDs та frame bounds rough-cut, cleaned audio і generated titles;
- перевіряє наявність усіх subtitle та visual target IDs;
- повертає `ready` лише коли всі checks пройдені.

`start_baseline_render` вимагає `confirm_render=true`. Після успішного QA він
використовує M44/M45, формує deterministic render name із SHA-256 suffix і
запускає рівно один allowlisted 1080p або 4K MP4/H.264 job. Повтор однакового
запиту повертає той самий durable receipt.

`get_baseline_render_status` повторює live QA та перевіряє точний managed MP4.
Статус `complete` можливий лише одночасно з `JobStatus=Complete`, валідним
output і незмінно успішним QA.

## Межі перевірки

M50 звіряє live identity і frame bounds через наявні read-only команди.
Поточні значення довільних Resolve properties не читаються: transform та
enabled-state покладаються на канонічний post-write readback відповідних M46 і
M49 receipt, а live QA підтверджує, що їхні target items досі існують.

Поточний M47 шлях додає SRT через документований `AppendToTimeline`. На
непорожньому timeline Resolve 21 Free розміщує такий кліп після наявного
контенту, а не поверх нього за SRT timecode. Тому M47 не є обов'язковою умовою
baseline render, доки не буде підтверджено безпечне вирівняне розміщення.
Переданий M47 receipt усе одно проходить повну identity-перевірку.

M50 не виконує B-roll, складну анімацію, кольорокорекцію або вибір дублів. Це
межі M51–M54.

## Live acceptance

M50 перевірено 2 серпня 2026 року в DaVinci Resolve 21.0.3 Free на timeline
`M42 Pause Compaction Apply` (`7e430372-841d-4f6f-99ac-8647f6d75a31`):

- core QA без опційних M47/M49 завершився з результатом 6/6;
- M50 receipt: `e291c710c569f1cdb8fc4d1cda30c5c75e898217534623a0528125924221c78a`;
- 1080p profile створив один job `5997af88-9c3a-4d92-9f7b-858385f82e15`;
- Resolve повернув `JobStatus=Complete`, а managed MP4 мав розмір
  2 094 880 932 bytes;
- exact replay повернув ті самі M50/M44/M45 receipt і job ID без нового job;
- M44 prepare та M45 start створили по одному safety backup.

Live acceptance також виявив і закрив regression у M50 status aggregation:
готовність output читається з фактичного M45 поля `output.validation.passed`.
