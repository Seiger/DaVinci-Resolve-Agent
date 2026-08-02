# M52: пакетовані анімаційні шаблони

M52 додає перший контрольований reusable Fusion Title без довільного коду в
MCP або bridge. Репозиторій містить один аудований шаблон
`accent-card-v1`; інсталятор перевіряє його SHA-256 і копіює до документованої
користувацької директорії Resolve `Fusion\Templates\Edit\Titles`.

## Межа безпеки

MCP приймає лише `template_id`, completed M51 receipt, нову назву timeline,
exact timecode, plan ID і confirmation. Він не приймає `.setting`/`.comp`,
Fusion node names, expressions, scripts, довільні controls або текст титру.
Поля title/subtitle можна змінити вручну в Resolve Inspector після вставки.

Шаблон використовує рекомендований Blackmagic модифікатор Anim Curves із
`Mirror` на `Dissolve.Mix`, тому fade-in/fade-out адаптуються до тривалості
title. Agent не створює keyframes і не мутує Fusion composition через API.

## Preview і apply

`list_animation_templates` і `get_animation_template` читають лише пакетований
каталог. `preview_animation_template` додатково:

- вимагає applied M51 receipt і повторно звіряє його live timeline;
- перевіряє незмінний source snapshot;
- перевіряє встановлений template/hash та документований
  `Timeline.InsertFusionTitleIntoTimeline`;
- повертає deterministic `plan_id` і capability gates без write-команд.

`apply_animation_template` вимагає ті самі inputs, exact `expected_plan_id` і
`confirm_apply=true`. Workflow дублює M51 timeline, вставляє один allowlisted
Fusion Title рівно на поточному timeline end, перевіряє playhead readback,
рівно один новий item,
наявність Fusion composition та незмінність попередніх video items. Durable
receipt дозволяє exact replay без повторного timeline або template insertion.

Raw tools `resolve_get_animation_template_environment` і
`resolve_insert_animation_template` лишаються вузькими provider primitives.
Кожен write створює project backup, зберігає/відновлює playhead і не змінює
source M51 timeline.

## Поточний статус

Python, JSON-contract, bridge simulation, MCP stdio та installer lifecycle
покриваються автоматичними тестами. Fusion asset, фактична вставка й анімація
підтверджені live у DaVinci Resolve 21.0.3 Free після повторної інсталяції та
повного перезапуску Resolve.

Перший live probe у Resolve 21.0.3 Free підтвердив, що asset завантажується як
120-frame Fusion title з composition, але timecode на 14 кадрів після timeline
end був clamp-нутий до start і спричинив ripple лише в disposable duplicate.
Safety readback повернув `ANIMATION_TEMPLATE_READBACK_FAILED`; source M51 не
змінився. Після цього контракт звужено до exact timeline end і додано
обов'язкову перевірку `GetCurrentTimecode()` до insertion. Повторний exact-end
probe та high-level apply успішно підтвердили structural insertion і durable
replay. Візуальна перевірка виявила ще дві помилки asset: card спершу був поза
кадром, а після виправлення координат з'являвся без анімації. Повторна перевірка
показала, що виправлення назви output на `Result` недостатньо: packaged asset
передавав через `KeyStretcherMod` двовимірний `Center`, тоді як штатний приклад
Resolve використовує скалярну криву. Перша scalar-версія через
`KeyStretcherMod.Result` також залишилася статичною: на наданому 60 fps записі
card за один кадр став повністю видимим на `7.083 с` і надалі не змінював
opacity. Asset переведено на прямо рекомендований для Fusion Titles Anim Curves:
`Dissolve.Mix` читає `LUTLookup.Value`, а `Mirror` повертає opacity до нуля.
Новий item `c4050675-00c3-47f7-a987-d0b84f227c5b` на disposable timeline
`M52 Anim Curves Acceptance` пройшов візуальну перевірку. Exact replay повернув
receipt `b0c0835108038962748065e6cf5c04778b99f0a7f6e04feef4f1befed69f1d76`
і не змінив кількість backups (`87 → 87`) або timelines (`14 → 14`).
