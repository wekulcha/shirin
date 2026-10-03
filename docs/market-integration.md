# Управление «Ширин» из KULCHA Market

Market не имеет готового безопасного подключения отдельных backend-проектов. «Ширин» работает с собственной БД и одним ботом. Его панель управления встроена в существующую суперадминку по `/projects/shirin/{section}/{id?}`. Там действительно доступны товары, клиенты, заказы, фотографии, импорт/экспорт Excel и два существующих права. Отдельная суперадминка не создана.

## Изменения в Market

Worktree: `../market-shirin-integration`, ветка `feature/shirin-integration`, основание `4bf905f1693597296945ea636b8b0dbfb2ed23cd`.

- `backend/app/routers/shirin_projects.py`: серверный реестр проектов и proxy с ограниченным набором операций. Доступ только после существующего bearer и **непустого** `MARKET_SUPERADMIN_ALLOWED_IDS`.
- `backend/app/config.py`, `main.py`: два параметра интеграции и подключение router.
- `superadmin_panel`: пункт «Ширин», полноценный AdminWorkspace с API adapter к Market. Стили ограничены `.shirin-admin`, корневые страницы не получают глобальное оформление «Ширин».
- Compose передаёт два новых backend-параметра. Caddy добавляет правила `/shirin/` перед существующими корневыми proxy; адреса Market сохранены.
- Миграции и данные Market не меняются. Исходная рабочая папка `market` остаётся в `dev/v1`.

## Серверная аутентификация

Браузер отправляет только собственный Market bearer. Market извлекает Telegram ID из проверенной сессии, выбирает фиксированный backend из окружения и подписывает метод, path, исходный query, SHA-256 тела, actor, timestamp и случайный nonce через HMAC-SHA256. «Ширин» проверяет общий секрет, свой явный allowlist, активность пользователя, 60-секундный срок и одноразовый nonce в БД. Пользовательский `project_id` не выбирает БД или права. Multipart проверяется по исходным байтам перед разбором файла.

Назначения `CAN_EDIT_MENU` / `CAN_LOOK_ORDERS` хранятся только в базе «Ширин». Привилегия разработчика наследуется через allowlist, без введения третьей роли. Для редактирования каталога нужны права меню; для чужих заказов и отметки оплаты — права заказов. Полномочия пересчитываются при каждом применении импорта, изменении заказа и callback бота.

Установите один случайный секрет длиной не менее 32 символов в:

```dotenv
# Market, только backend
MARKET_SHIRIN_API_BASE=http://shirin-backend:8000/shirin/api
MARKET_SHIRIN_INTEGRATION_SECRET=<shared-random-secret>
MARKET_SUPERADMIN_ALLOWED_IDS=<existing-approved-telegram-ids>
# Shirin
SHIRIN_MARKET_INTEGRATION_SECRET=<same-shared-random-secret>
SHIRIN_SUPERADMIN_ALLOWED_IDS=<same-approved-telegram-ids>
```

Секрет не должен совпадать с access secret или токеном бота. Его нет в Vite env, bundle, ответах API или логах. Не передавайте браузеру прямой внутренний URL сервиса.

## Синхронизация интерфейса

Основной модуль управления расположен в `shirin/user_panel/src`. Проверенная копия включена в Market, чтобы репозитории собирались отдельно без файловых зависимостей друг от друга. При обновлении модуля выполните из `shirin`:

```bash
node scripts/sync-market-ui.mjs ../market-shirin-integration/superadmin_panel/src/shirin
```

Скрипт копирует только интерфейс управления и ограничивает все CSS selectors контейнером проекта. Backend-бизнес-логика всегда остаётся единственной — в «Ширин».

## Локальная проверка двух сервисов

При работающем демонстрационном backend «Ширин» на 8083:

```bash
.venv/bin/python scripts/run-market-demo.py
# Во втором терминале:
.venv/bin/python scripts/run-market-demo.py --check
# Панель Market из её worktree:
cd ../market-shirin-integration/superadmin_panel
VITE_API_URL=http://localhost:8085/api/v1 npm run dev
```

Используется отдельная синтетическая SQLite база `/private/tmp/shirin-market-smoke.db`, а не база Market. Скрипт проверяет настоящее взаимодействие по HTTP: права, товары, клиенты/заказы/доступы, multipart Excel, отсутствие данных «Ширин» в Market и сохранность старого API. Для production нужна общая контейнерная сеть, доступная gateway и обоим backend.
