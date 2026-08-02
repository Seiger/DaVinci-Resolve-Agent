# M53: кольорокорекція та visual QC

M53 починається з read-only discovery/preview. ResolveBridge використовує лише
документовані `TimelineItem.GetCurrentVersion`, `GetVersionNameList`,
`GetNodeGraph` та методи `Graph.GetNumNodes`, `GetNodeLabel`, `GetLUT`.

Перший пакетований preset `tutorial-clean-v1` містить фіксовані CDL slope,
offset, power і saturation. MCP не приймає довільні CDL-значення, LUT/DRX-шляхи,
node indices або Resolve expressions.

`resolve_get_color_environment` читає лише media video items і повертає current
local color version, node count, labels та LUT readback. `list_color_presets` і
`get_color_preset` працюють локально. `preview_color_treatment` вимагає applied
M52 receipt, повторно звіряє live timeline та формує deterministic plan для
майбутнього duplicate-timeline apply.

Live discovery у Resolve 21.0.3 Free підтвердив усі read methods, один node на
кожному з п'яти media-video items та presence `SetCDL`, `AddVersion` і
`LoadVersionByName`. Exact preview replay повернув plan
`79c1730ea806e7838f0255063096e9fc162fb66831c7900a916f1cb3d19db47d`;
timelines лишилися `14`, backups — `87`.

Другий slice додає `apply_color_treatment`: він вимагає exact reviewed plan і
`confirm_apply=true`, дублює M52 timeline та передає bridge лише preset ID і
exact media item IDs. Bridge створює local version
`DaVinci Agent Tutorial Clean v1` і застосовує code-owned CDL до node 1.
MCP не приймає CDL values. Через відсутність documented GetCDL readback
перевіряються success `SetCDL`, активна managed version, node 1, exact targets,
backup та durable replay. Live write ще потребує окремого підтвердження.

Live apply виявив, що duplicate timeline отримує нові TimelineItem IDs. Перший
attempt безпечно зупинився до grade з `COLOR_TARGET_MISMATCH`, зберігши лише
duplicate і його backup. Workflow тепер однозначно зіставляє source/target за
name, track, timeline bounds і source bounds, після чого відновлює pending
operation з durable receipt.

Відновлений apply створив local version на 5/5 target clips і один color
backup. Receipt:
`1f79bf7e84794183c806344144982d17ca0c0164364c08c4bb57e172eeafb606`;
target timeline: `939ab59d-2eb6-4ed3-9860-2e4bc65a9bf6`. Exact replay зберіг
timelines `15 → 15` і backups `89 → 89`; source 5/5 лишилися на `Version 1`,
target 5/5 — на `DaVinci Agent Tutorial Clean v1`.

Ручний visual acceptance підтвердив очікуване помірне підсилення контрасту без
зауважень щодо неприродного кольорового відтінку. M53 завершено.
