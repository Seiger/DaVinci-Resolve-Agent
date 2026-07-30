# Налаштування MCP-клієнта

## Межі MCP

MCP-сервер працює локально через `stdio` і не відкриває мережевий порт.
Read-only інструменти:

- `video_agent_status`;
- `resolve_get_project`;
- `resolve_list_timelines`;
- `resolve_get_timeline`.

Write-інструменти M4:

- `resolve_import_media`;
- `resolve_create_timeline`;
- `resolve_append_clip`;
- `resolve_add_marker`.

Draft-only інструмент M5:

- `create_rough_cut`.

MCP-адаптер звертається до application service. Він не працює з transport
runtime безпосередньо та не приймає довільних назв команд, Python, Lua,
PowerShell або shell-коду.

`create_rough_cut` валідовує локальні файли, аналізує окремі PCM WAV-доріжки
та зберігає `pending_review` план. Він не ставить команду bridge, не відкриває
проєкт Resolve й не застосовує запропоновані операції. Формат і обмеження
описано в [rough-cut.md](rough-cut.md).

## Конфігурація клієнта

Спочатку виконай `installer\install.ps1`. У конфігурації MCP-клієнта вкажи
абсолютний шлях до створеного executable. Не записуй власний шлях у файли
репозиторію:

```json
{
  "mcpServers": {
    "davinci-resolve-agent": {
      "command": "<repository-path>\\.venv\\Scripts\\davinci-agent-mcp.exe",
      "args": []
    }
  }
}
```

Заміни `<repository-path>` на локальний шлях до checkout на конкретному
комп'ютері та перезапусти MCP-клієнт.

## Виконання Resolve-запитів

`video_agent_status` повертає кешований стан bridge одразу.
`create_rough_cut` також працює без bridge. Resolve-інструменти ставлять команду
в локальну чергу. Поки клієнт очікує відповідь:

1. відкрий потрібний проєкт у DaVinci Resolve;
2. запусти `Workspace → Scripts → Edit → ResolveBridge`;
3. дочекайся відповіді MCP-клієнта.

Типовий timeout становить 30 секунд. Аргумент `timeout_seconds` приймає значення
понад `0` і не більше `300`. Одноразова модель bridge є навмисним обмеженням
поточного прототипу.

## Безпечне редагування

Усі write-tools створюють `.drp` backup до зміни та підтримують необов'язковий
`idempotency_key`. Для `resolve_import_media` кожен шлях має бути абсолютним,
існувати й належати до `media.allowed_roots` у локальному `config.toml`.

MCP annotations позначають ці tools як write, але не destructive. M4 не видаляє
кліпи, таймлайни, медіа чи markers і не відновлює проєкт автоматично. Стратегія
відновлення описана в [rollback.md](rollback.md).
