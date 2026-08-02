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

## Подальша acceptance межа

Після реального людського approve та live M54.4 compose наступні M55 slices
мають окремо реалізувати:

1. confirmed, receipt-backed Media Pool import;
2. confirmed application лише до duplicate timeline;
3. повний visual/audio/subtitle/color QC;
4. confirmed render і output verification;
5. повторне встановлення та acceptance на чистому Windows-комп'ютері.
