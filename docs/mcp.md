# Налаштування MCP-клієнта

## Межі M3

MCP-сервер працює локально через `stdio` і не відкриває мережевий порт. Він
надає лише чотири read-only інструменти:

- `video_agent_status`;
- `resolve_get_project`;
- `resolve_list_timelines`;
- `resolve_get_timeline`.

MCP-адаптер звертається до application service. Він не читає й не записує
runtime-каталоги безпосередньо та не приймає довільних назв команд, Python,
Lua, PowerShell або shell-коду.

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

`video_agent_status` повертає кешований стан bridge одразу. Інші інструменти
ставлять команду в локальну чергу. Поки клієнт очікує відповідь:

1. відкрий потрібний проєкт у DaVinci Resolve;
2. запусти `Workspace → Scripts → Edit → ResolveBridge`;
3. дочекайся відповіді MCP-клієнта.

Типовий timeout становить 30 секунд. Аргумент `timeout_seconds` приймає значення
понад `0` і не більше `300`. Одноразова модель bridge є навмисним обмеженням
поточного прототипу.
