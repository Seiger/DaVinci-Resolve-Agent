# M55: creative v1 acceptance

M55 з'єднує підтверджені M0–M54 можливості у відтворюваний шлях до готового
відео. Кожен write має окремий preview/confirmation, працює з duplicate
timeline, створює backup і перевіряє canonical readback. Unsupported capability
повинна блокуватися, а не підмінятися припущенням про Resolve 21 Free.

## M55.1: approved sequence source binding

M54 sequence навмисно не містить absolute paths. Перед майбутнім apply tool
`bind_take_sequence_sources` повторно приймає по одному `{order, path}` для
кожного sequence entry та:

- перевіряє path через `media.allowed_roots`;
- звіряє filename, size і bounded edge fingerprint з approved candidate;
- зберігає machine-local private artifact у configured runtime;
- повертає лише path-redacted receipt з exact sequence SHA-256;
- не імпортує media, не викликає ResolveBridge і не змінює timeline.

Private artifact може містити absolute local paths, бо є непереносним binding
активної машини. Він не входить до Git, MCP response, sequence report або
workflow audit. `get_take_sequence_binding` повертає лише public receipt;
доступ до private sources залишається внутрішнім provider-neutral boundary для
наступного M55 preview/apply slice.

Binding має `apply_supported=false` і `timeline_modified=false`. Наявність
binding ще не дозволяє import, ranged insert, timeline replacement або render.

## M55.2: read-only assembly preview

`preview_take_sequence_assembly` споживає private binding лише всередині
процесу та перед кожним preview повторно перевіряє allowlist і file identity.
Для кожного source PyAV читає duration, average FPS та resolution без
повного декодування. Plan:

- зберігає approved order і exact source ranges;
- формує безперервні output ranges у секундах від нуля;
- редагує local paths і містить canonical binding SHA-256;
- попереджає про різні FPS або resolution;
- має `timeline_modified=false` та `apply_supported=false`.

M55.2 не читає Resolve, не імпортує media і не переводить секунди у frames
конкретного timeline. Для цього потрібні окремі live target metadata,
capability gates і reviewed duplicate-timeline semantics.

## M55.3: live target timeline frame mapping

`preview_take_sequence_timeline_mapping` повторно обчислює M55.2 preview і
читає exact target timeline через existing `get_editing_metadata` із
`asset_ids=[]`. Це backward-compatible timeline-only режим чинного
документованого readback, а не новий Resolve API.

Plan містить verified timeline identity, FPS, resolution, track counts,
inclusive source-frame bounds і безперервні timeline-relative positions.
Source bounds округлюються за source FPS; тривалість placement переводиться у
target FPS. Результат path-redacted, deterministic і має
`timeline_modified=false`, `apply_supported=false`.

M55.3 ще не має Media Pool asset IDs і тому не може сформувати apply command.
Наступний slice має окремо виконати safe import/binding preview, а confirmed
write — лише після exact plan review, backup і duplicate-timeline gate.

## M55.4: conservative Media Pool import preview

`preview_take_sequence_media_import` прив'язує M55.3 mapping до sorted live
Media Pool snapshot. Однаковий fingerprint у кількох sequence entries означає
один source з кількома `orders`, тому майбутній import не дублюватиме файл для
кожного range.

Bounded Media Pool readback повертає canonical asset ID, name і logical folder,
але навмисно не повертає filesystem path або fingerprint. Через це same-name
item не можна автоматично reuse: plan ставить `review_name_collision`,
`requires_review=true` та `import_ready=false`. За відсутності збігу action —
`import`, але M55.4 все одно має `apply_supported=false`.

Plan містить SHA-256 нормалізованого Media Pool snapshot, не містить private
source paths і не виконує import, backup або timeline write. Confirmed import
має бути окремим наступним slice з exact plan ID і повторною перевіркою binding
та live snapshot.

Різні fingerprints з однаковим filename також не можна безпечно зіставити з
порядком результатів Resolve. Такі sources отримують
`review_source_name_collision`; увесь batch лишається заблокованим.

## M55.5: confirmed receipt-backed Media Pool import

`apply_take_sequence_media_import` приймає тільки canonical `binding_id`,
assembly/timeline identity, exact M55.4 `expected_plan_id` і
`confirm_import=true`. Absolute paths не входять у MCP: workflow повторно
обчислює M55.4/M55.3, перевіряє collision-free plan, розв'язує private binding
всередині процесу та викликає чинний backup-backed `ImportMedia` batch.

Після write агент вимагає по одному однозначному asset ID на unique source,
звіряє source FPS/duration з approved inclusive ranges і підтверджує canonical
Media Pool readback. Durable receipt містить лише fingerprints, display names,
orders, asset IDs і metadata; paths та backup path редагуються. Exact replay
читає receipt і не виконує provider write повторно. M55.5 змінює Media Pool,
але не створює, не дублює і не редагує timeline.

## M55.6: confirmed duplicate-timeline V1/A1 assembly

`preview_take_sequence_timeline_apply` приймає тільки applied M55.5 receipt і
нову bounded назву target timeline. Він повторно перевіряє M55.3 mapping,
canonical imported asset IDs, private binding та live source timeline. Source
мусить бути порожнім, а target name — вільним; інакше preview повертає blocker
без write. Наявність audio stream визначається локально через PyAV без decode і
без додавання path до plan.

`apply_take_sequence_timeline` вимагає exact `expected_plan_id` та
`confirm_apply=true`. Він використовує лише вже перевірені документовані
`DuplicateTimeline` і `AppendToTimeline([{clipInfo}, ...])` primitives:
approved video ranges вставляються одним bounded batch на V1, sources з audio
stream — окремим bounded batch на A1. Кожен provider write створює project
backup і має deterministic idempotency key.

Durable receipt зберігає sanitized step results, canonical TimelineItem IDs і
readback SHA-256, але не source/backup paths. Interrupted apply продовжує лише
pending step. Фінальний gate вимагає exact target items та повторно підтверджує,
що source timeline не змінився. Caller не передає raw clipInfo, track indexes,
asset IDs або filesystem paths.

## M55.7: structural QC та human acceptance

`inspect_take_sequence_qc` приймає лише applied M55.6 receipt. Перед створенням
детермінованого path-redacted report він виконує свіже source/target readback
через M55.6 boundary і перевіряє exact V1 order/ranges, A1 лише для sources з
audio stream, спільний timeline origin та відсутність video gaps.

Структурний pass не є заявою про готовність відео: dialogue audio processing,
subtitle content/alignment, color treatment і visual/editorial quality явно
внесені до `unverified_areas`. `review_take_sequence_qc` записує один immutable
людський `approve|reject`, прив'язаний до exact report hash. Get/review повторно
перевіряють live M55.6 evidence. Жоден M55.7 tool не редагує Resolve.

## Подальша acceptance межа

Після реального людського approve та live M54.4 compose наступні M55 slices
мають окремо реалізувати:

1. сумісне застосування/підтвердження visual/audio/subtitle/color шарів;
2. confirmed render і output verification;
3. повторне встановлення та acceptance на чистому Windows-комп'ютері.
