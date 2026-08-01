# Roadmap DaVinci Resolve Agent

## Межа v1

Версія v1 має дозволяти Codex змонтувати та перевірити готове відео за
вказівками користувача, зберігаючи оригінали й використовуючи лише
документовані та live-підтверджені можливості активного provider.

До обов'язкової межі v1 входять:

- повний керований шлях від локальних source-файлів до перевіреного render;
- очищення та інтеграція звуку;
- транскрипція, субтитри й декларативні editing recipes;
- керовані титри, zoom та reframing;
- B-roll;
- складні анімації;
- кольорокорекція;
- розумний вибір дублів;
- end-to-end acceptance на чистому підтримуваному Windows-комп'ютері.

## Заплановані milestones

- **M45** — контрольований старт finalized render і перевірка MP4.
- **M46** — інтеграція очищеного звуку в timeline.
- **M47** — транскрипція та субтитри.
- **M48** — декларативні MCP editing recipes.
- **M49** — керовані титри, zoom та reframing.
- **M50** — baseline end-to-end монтаж і QA.
- **M51** — B-roll planning, review та bounded application.
- **M52** — складні анімації й reusable templates.
- **M53** — кольорокорекція, presets та visual QC.
- **M54** — аналіз і розумний вибір дублів із review boundary.
- **M55** — повний creative v1 end-to-end acceptance і repeatable install test.

Milestone може бути розділений на discovery/preview/apply підетапи, якщо
Resolve API або безпечне live-тестування цього потребують. Roadmap не є заявою
про доступність конкретної функції у DaVinci Resolve 21 Free: unsupported або
недокументовані можливості повинні блокуватися, а не емулюватися припущеннями.
