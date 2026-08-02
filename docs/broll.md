# M51: B-roll planning, review та bounded application

M51 додає контрольований B-roll поверх завершеного M50 baseline. Він не
вибирає кадри автоматично й не робить семантичних припущень: caller явно
передає imported `asset_id`, source range, позицію, video track і коротке
пояснення `purpose`.

## Preview

`preview_broll_plan` є read-only і вимагає completed M50 receipt. Tool:

- повторно перевіряє M50 status і live identity baseline timeline;
- читає лише документовані `GetClipProperty("Frames"/"FPS")`, track counts і
  canonical timeline item bounds;
- дозволяє від 1 до 100 video-only placements на V3–V8;
- перевіряє source bounds, перераховує тривалість за source/timeline FPS;
- блокує вихід за timeline, взаємні overlap та collision з existing item;
- повертає deterministic `plan_id` і capability gates без backup або змін.

`position_frames` задається відносно початку baseline timeline. Source end є
bounded source frame, який передається у документований `AppendToTimeline`
`clipInfo`. Аудіо B-roll у M51 не вставляється.

## Apply

`apply_broll_plan` приймає ті самі inputs, reviewed `expected_plan_id` і
`confirm_apply=true`. Перед кожним write він повторно обчислює preview. Якщо
metadata, baseline, placements або capabilities змінилися, plan ID не збігається
і apply блокується.

Успішний apply:

1. дублює M50 timeline під новою унікальною назвою;
2. забезпечує потрібну кількість video tracks;
3. одним batch insert додає video-only source ranges;
4. звіряє asset binding в immediate insert result, а потім canonical IDs,
   source/timeline bounds і track у загальному timeline readback;
5. зберігає durable receipt для exact replay.

Канонічний M50 timeline не змінюється. Кожен provider write використовує
наявний backup/idempotency transport contract. Довільні Resolve properties,
Lua, Python, PowerShell, shell, Fusion, transitions і автоматичний пошук B-roll
не приймаються.

## Поточний статус

Provider-neutral workflow, JSON Schema, MCP tools і automated tests реалізовані.
Read-only preview, confirmed apply та exact replay перевірено в Resolve 21.0.3
Free на completed M50 source `M42 Pause Compaction Apply`. Plan
`7d6fb2369c9d6b24b3a71d857f9199927203afb0c701650ecc031394a7809b5e`
вставив asset `M10 Short Render Test`, source `0–47`, у duplicate timeline
`M51 B-roll Apply Test` на V3: фактичні timeline bounds `86640–86687`, canonical
item ID `97003e7d-8b07-4477-94ee-cc0b3f17a4ef`.

Durable receipt
`a7a0343d4af6cb10507e5241e0476bcf28d787080aea58020d2fc67750190c7f`
має статус `applied`. Три окремі provider operations створили три safety
backups. Exact replay зберіг 75 backup-файлів і 9 timelines без змін. Source
M50 timeline залишився з 7 items і без V3; B-roll існує лише в duplicate
timeline `019fc876-775c-429a-95d6-8b4ca741a802`.

Generic timeline readback Resolve не повертає `asset_id`. Тому asset binding
перевіряється в immediate insert result, а durable persistence — за canonical
item ID, track і точними source/timeline bounds.
