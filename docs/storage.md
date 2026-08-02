# Зберігання даних на окремому диску

Великі дані Agent зберігаються під одним configurable `DataRoot`:

```text
<DataRoot>/
├── media/
│   ├── audio-sources/
│   ├── processed/
│   ├── renders/
│   └── subtitles/
└── runtime/
    ├── models/
    ├── backups/
    ├── state/
    ├── logs/
    ├── take-sequence-bindings/
    └── інші receipts та queue directories
```

Для диска `G:`:

```powershell
.\installer\install.ps1 -DataRoot "G:\DaVinciResolveAgent"
.\installer\verify.ps1
```

Інсталятор записує resolved machine-local manifest у
`%APPDATA%\DaVinciResolveAgent\storage.json`. Він потрібен, бо внутрішній
ResolveBridge не імпортує зовнішній Python package. Manifest містить лише
версію layout та абсолютний локальний `data_root`; у Git він не потрапляє.

Без параметра `-DataRoot` portable fallback —
`%LOCALAPPDATA%\DaVinciResolveAgent`. Репозиторій не містить прив'язки до
конкретної літери диска.

Для перенесення legacy data спочатку cleanly зупини ResolveBridge, потім виконай:

```powershell
.\installer\migrate-storage.ps1 `
  -DataRoot "G:\DaVinciResolveAgent" `
  -ConfirmBridgeStopped `
  -RemoveSource
```

Migration спочатку копіює файли, перевіряє size і SHA-256 кожного файла, записує
manifest і лише потім видаляє source directories. Compatibility junctions
залишають старі durable receipt paths робочими, але фізичні дані лежать на
цільовому диску.

Перед render або full-timeline audio export ResolveBridge залишає щонайменше
10 GiB вільного місця на configured output volume. Якщо reserve відсутній,
операція завершується `OUTPUT_STORAGE_LOW` до створення нового великого файла.

## Live acceptance

2 серпня 2026 року 1440 legacy-файлів загальним розміром 8,369 GiB перенесено
з системного диска в `G:\DaVinciResolveAgent`. Size і SHA-256 кожного файла
збіглися до видалення source directories. Після встановлення нового bridge
`verify.ps1` підтвердив `DataRoot=G:`, writable directories, heartbeat 0,1 s та
Resolve 21.0.3.7; CLI `ping` повернув `pong`. Активний bridge state записується
безпосередньо в `G:\DaVinciResolveAgent\runtime\state\bridge.json`.

M55 source bindings зберігають public redacted receipt і сусідній private JSON
з allowlisted absolute paths у `<DataRoot>/runtime/take-sequence-bindings`.
Private artifact є machine-local, не комітиться і не повертається через MCP.
