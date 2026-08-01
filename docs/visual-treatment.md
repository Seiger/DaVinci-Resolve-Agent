# M49: керовані титри, zoom і reframing

M49 додає provider-neutral visual treatment із двома фазами:

- `preview_visual_treatment` нормалізує точний список операцій і перевіряє
  live capabilities без зміни Resolve;
- `apply_visual_treatment` вимагає `confirm_apply=true`, створює durable receipt
  та відновлює виконання лише з незавершеної операції.

## Статичний zoom і reframing

Кожен transform містить canonical `timeline_item_id` і лише дозволені поля:
`position_x`, `position_y`, `zoom`, `rotation_degrees`, `opacity_percent`.
Workflow передає їх одним `set_clip_transforms`; bridge створює один `.drp`
backup і звіряє `Pan`, `Tilt`, `ZoomX`, `ZoomY`, `RotationAngle` та `Opacity`
через документовані `TimelineItem.SetProperty/GetProperty`.

Це статичне кадрування. M49 не викликає `SmartReframe`, бо локальна
документація Resolve 21 відносить його до Studio/AI scripting prerequisites.
Keyframes, tracking, crop, masks і довільні Resolve properties не приймаються.

## Стандартні титри

`resolve_insert_title` приймає exact timeline, ім'я встановленого стандартного
title, timecode `HH:MM:SS:FF` і `confirm_insert=true`. Bridge:

1. експортує backup;
2. вибирає timeline і заданий timecode;
3. викликає документований `Timeline.InsertTitleIntoTimeline(titleName)`;
4. повертає попередній playhead;
5. вимагає canonical ID, video track та frame bounds вставленого item.

Щоб документований API не перезаписував або не розрізав наявні clips, M49
дозволяє insertion лише на integer-FPS timeline і лише на timecode не раніше
поточного `Timeline.GetEndFrame()`. Після write bridge повторно перелічує всі
video items: має з'явитися рівно один новий ID на exact requested frame, а
bounds усіх попередніх items мають лишитися незмінними.

У M49 немає зміни тексту, шрифту чи Fusion controls: Resolve Scripting README
документує insertion, але не документує provider-neutral setter цих полів.
Складні анімації та reusable templates залишаються M52.

Capability `title.insert` стає `true` лише після успішної live-вставки. До цього
preview чесно повертає її в `missing_capabilities`.

## Приклад MCP

```json
{
  "timeline_id": "timeline-id",
  "transforms": [
    {"timeline_item_id": "clip-id", "zoom": 1.2, "position_x": 120.0}
  ],
  "titles": [
    {"title_name": "Text", "timecode": "01:00:05:00"}
  ]
}
```

Після перевірки preview той самий payload передається до
`apply_visual_treatment` разом із `confirm_apply=true`.
