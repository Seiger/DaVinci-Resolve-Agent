# Декларативні editing recipes

M48 додає версіоновані рецепти, які компонують лише явно дозволені
application workflows. Recipe не є Python-скриптом і не може містити MCP tool
name, shell-команду, Lua, PowerShell, Resolve expression або довільні kwargs.

## Вбудований recipe

`tutorial-layout-v1` працює з одним applied M38 synchronized-pair receipt і
послідовно виконує:

1. `compose_webcam_picture_in_picture` з фіксованими або перевіреними
   нормалізованими координатами;
2. `link_synchronized_screen_pair` для canonical screen V1/A1 items.

Параметри за замовчуванням:

- webcam size — `25%`;
- center X — `82%`;
- center Y — `82%`.

Recipe-файл входить до wheel як
`config/recipes/tutorial-layout-v1.json` і проходить
`editing-recipe.schema.json`. Підміна action або capability declaration
відхиляється до виконання.

## MCP workflow

Read-only tools:

- `list_editing_recipes()`;
- `get_editing_recipe(recipe_id)`;
- `preview_editing_recipe(recipe_id, inputs)`.

Preview нормалізує defaults, показує точний порядок step-ів, перевіряє live
capabilities і повертає `ready` або `blocked`. Він не створює Resolve backup і
не змінює timeline.

Write tool:

```text
run_editing_recipe(
  recipe_id="tutorial-layout-v1",
  inputs={"synchronized_pair_receipt_id": "<sha256>"},
  confirm_execute=true
)
```

Одна confirmation стосується всього попередньо видимого bounded recipe.
Кожний underlying workflow зберігає власні confirmation, capability, backup,
readback та idempotency gates.

## Replay і відновлення

Recipe run має SHA-256 identity, залежну від recipe ID, версії, SHA-256
повного definition та нормалізованих inputs. Зміна step-ів без підняття версії
тому не може повернути старий applied receipt. Receipt зберігається у
`%LOCALAPPDATA%\DaVinciResolveAgent\runtime\editing-recipe-runs`.

Після кожного успішного step receipt записується атомарно. Якщо наступний step
перервався, повторний виклик пропускає applied step-и та продовжує лише pending
step. Повністю applied receipt повертається без повторних Resolve writes.

## Поточна межа

M48 навмисно не приймає recipe-файли або action lists через MCP. Розширення
allowlist відбувається лише через код, JSON Schema, тести й окремий review.
Поточний recipe не запускає render і не обходить review boundaries наступних
milestones.
