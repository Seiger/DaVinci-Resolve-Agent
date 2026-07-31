# Audit локальних workflows

M26 поширює observable behavior на локальні MCP operations, які не
використовують ResolveBridge:

- `create_rough_cut`;
- `approve_rough_cut`;
- `get_rough_cut_plan`;
- `list_rough_cut_plans`;
- `clean_dialogue_audio`;
- `get_audio_report`;
- `list_audio_reports`.

Canonical records зберігаються в:

```text
%LOCALAPPDATA%\DaVinciResolveAgent\runtime\logs\workflow\
```

Кожен виклик спочатку отримує стан `running`, а потім атомарно переходить у
`success` або `error`. Запис містить лише випадковий operation ID, allowlisted
operation/category, timestamps, duration і безпечну класифікацію помилки.

Workflow audit не містить arguments, plan/report IDs, file paths, contents,
results або exception messages. Невідома operation відхиляється до запуску
callback. Директорія `logs\workflow` не може бути symlink.

Production wiring виконується в MCP composition root. Dependency-injected
`AgentApplication` може отримати test auditor або працювати без audit, тому
unit tests і сторонні adapters не пишуть неочікувані файли в APPDATA.
