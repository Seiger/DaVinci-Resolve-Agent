# Локальна діагностика

M24 додає локальну CLI-команду:

```powershell
.\.venv\Scripts\davinci-agent.exe diagnostics
```

Вона створює canonical JSON у:

```text
%LOCALAPPDATA%\DaVinciResolveAgent\runtime\diagnostics\
```

Bundle містить:

- версії agent, Python і Windows;
- локальну конфігурацію після редагування секретних значень;
- cached bridge metadata та capabilities;
- metadata максимум 20 останніх failed commands без arguments та
  idempotency keys;
- максимум 50 останніх рядків із максимум 5 локальних log-файлів.

Log discovery охоплює файли безпосередньо в `logs` і один керований рівень,
зокрема `logs\audit` та `logs\workflow`. Довільна рекурсія та
symlink-директорії не використовуються.

Команда не запускає ResolveBridge, не звертається до Resolve, не включає
медіа, render outputs, backups, raw commands або responses. Абсолютні
APPDATA, LOCALAPPDATA та USERPROFILE у конфігурації й excerpts замінюються
environment placeholders.

Поля, назви яких містять `password`, `secret`, `token`, `api_key`,
`authorization`, `credential`, `private_key` або `connection_string`,
замінюються на `[REDACTED]`. Перед передаванням bundle третій стороні все одно
переглянь його вручну: довільний текст логів може містити контекст, який не
можна надійно класифікувати автоматично.

Uninstaller зберігає diagnostics разом із logs, якщо обрано збереження логів.
Щоб видалити обидві директорії під час uninstall, передай
`-PreserveLogs $false`.
