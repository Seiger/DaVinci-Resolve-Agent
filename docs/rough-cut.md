# Чернетка rough cut у M5

M5 аналізує синхронні записи екрана й вебкамери та створює JSON-план для
перевірки людиною. Він не застосовує план, не змінює таймлайн і не запускає
Resolve bridge.

## Вхідні файли

`create_rough_cut` приймає:

- відеофайл екрана;
- відеофайл вебкамери;
- окремі аудіодоріжки екрана, вебкамери та мовлення для аналізу;
- назву майбутнього таймлайна;
- необов'язкові пороги синхронізації та пауз.

Усі п'ять шляхів мають бути абсолютними, існувати та належати до
`media.allowed_roots` локальної конфігурації. Поточний детермінований analyzer
підтримує лише нестиснений 16-bit PCM WAV. Відеоконтейнери не декодуються:
отримання WAV-доріжок належить майбутньому незалежному audio/FFmpeg provider.

## Результат і review gate

План зберігається у
`%LOCALAPPDATA%\DaVinciResolveAgent\runtime\plans\<plan_id>.json`. Однакові
вхідні дані й параметри дають той самий `plan_id` та не створюють дубліката.

Контракт навмисно фіксує:

```json
{
  "status": "pending_review",
  "review": {
    "required": true,
    "approved": false,
    "apply_supported": false
  }
}
```

План містить оцінений offset вебкамери, знайдені довгі паузи, запропоновані
діапазони вирізання, майбутні операції та потрібні capabilities. Низьку
впевненість синхронізації потрібно перевірити вручну.

M21 додає окрему локальну команду схвалення:

```text
approve_rough_cut(plan_id, confirm_review=true)
```

Вона приймає лише 64-символьний lowercase hex `plan_id`, повторно валідовує
draft і зберігає `<plan_id>.approval.json`. Approval містить SHA-256
канонічного draft, тому зміна плану після схвалення виявляється. Повторний
виклик повертає той самий record без зміни `approved_at`.

Схвалення не означає застосування:

```json
{
  "status": "approved",
  "confirm_review": true,
  "apply_supported": false
}
```

M21 не запускає ResolveBridge, не створює timeline і не виконує proposed
operations. Застосування залишається заблокованим, доки немає повного
документованого API для move/trim/split та окремого безпечного apply milestone.

## M34: preview і контрольоване застосування

M34 додає `preview_rough_cut_apply` та `apply_rough_cut`. Обидва вимагають
canonical `plan_id`, чинний approval з тим самим SHA-256, ID вихідного timeline
та нову назву копії. Preview не звертається до Resolve і показує точний список
операцій та всі непідтверджені capabilities.

Apply потребує `confirm_apply=true`. Він не змінює original timeline: спочатку
перевіряє кожну capability і кожну proposed operation. Зараз M34 не має
документованого mapping для жодної операції M5 після копіювання, тому вона
блокує apply ще до дублювання timeline. Коли mapping з'явиться, першим write
буде лише документоване дублювання timeline; він уже створює `.drp` backup у
ResolveBridge.
Результат зберігається як idempotent apply receipt і також потрапляє до
workflow audit. Якщо хоча б одна capability має значення не `true`, apply
повертає `blocked` без backup і без команди до Resolve.

Поточний M5 план вимагає `clip.move` і `clip.trim`, яких bridge ще не
підтвердив, а також `import_media`, `create_timeline`, `place_media` й
`remove_pauses`, для яких M34 поки не реалізує mapping. Тому на реальному
такому плані M34 чесно блокує apply; він не імітує монтаж і не виконує
непідтверджені Resolve API-виклики.

## Повторний перегляд планів

M22 додає два read-only інструменти:

```text
list_rough_cut_plans(limit=100)
get_rough_cut_plan(plan_id)
```

Перший повертає bounded summaries: ID, час створення, назву майбутнього
timeline, кількість proposed operations, effective review status і час
схвалення. Source media paths до summary не потрапляють.

Другий повертає повний валідований draft та matching approval для одного
canonical ID. Якщо approval відсутній, effective status залишається
`pending_review`; якщо його SHA-256 не відповідає draft, інструмент завершується
помилкою. Обидва інструменти завжди повідомляють `apply_supported=false`.

## M38: складання синхронної бази

`sync_screen_and_webcam` реалізує лише підтриману частину майбутнього rough
cut: створення нового timeline та синхронне розміщення screen V1/A1 і webcam
V2. Він не застосовує старий M5 plan автоматично й не змінює його approval.
Offset можна взяти з перевіреного плану, але MCP виклик явно передає canonical
asset IDs, signed offset і `confirm_sync=true`.

Це свідомо окремий workflow: M5 `remove_pauses` усе ще потребує відсутніх
документованих trim/split/move mappings. M38 не оголошує весь plan
`apply_supported=true` і не додає webcam audio.

## Деінсталяція

Draft-плани зберігаються за замовчуванням. Для навмисного видалення разом з
runtime передай `-PreservePlans $false` у `installer\uninstall.ps1`.
