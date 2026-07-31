# Audit logging transport-команд

M25 створює один canonical JSON record для кожної команди, яку зовнішній
agent ставить у filesystem queue Resolve.

Записи зберігаються в:

```text
%LOCALAPPDATA%\DaVinciResolveAgent\runtime\logs\audit\
```

Lifecycle:

```text
submitting → pending → success
                     → error
                     → timeout
```

Record створюється атомарно до публікації command envelope. Після enqueue та
після завершення очікування той самий файл атомарно замінюється новим
валідованим станом.

Atomic audit replacement повторюється максимум тричі з інтервалом 10 ms лише
для transient Windows `PermissionError`. Інші filesystem помилки не
маскуються й не повторюються автоматично.

Audit містить лише:

- command ID, provider та allowlisted action;
- safety flags;
- submitted/finished timestamps;
- duration;
- status, event, level;
- безпечний error code та retryable flag.

Audit навмисно не містить arguments, media paths, idempotency keys, response
payloads або error messages. Директорія `logs\audit` не може бути symlink.

M25 охоплює transport-команди Resolve, які використовують
`FilesystemCommandClient`. Локальні rough-cut та audio workflows не
представляються як Resolve-команди. Їхній окремий application-level шар
описано в [workflow-audit.md](workflow-audit.md).
