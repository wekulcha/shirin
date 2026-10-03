# Аудит исходной основы — 3 октября 2026

- KULCHA: `../kulcha`, commit `1014621fc56167c4a8fbe2e77fd6a860ce64b4fc`, ветка `KBE-1/am_python_version`.
- KULCHA Market: `../market`, commit `4bf905f1693597296945ea636b8b0dbfb2ed23cd`, ветка `dev/v1`, origin `https://github.com/wekulcha/market.git`.
- На начало аудита оба `git status --short` пусты. AGENTS.md в проектах не обнаружены. Исходные ветки не переключаются.
- Market новее; последний commit отменяет B2B. Остаточный `b2b_panel` содержит зависимости, но не рабочую реализацию. Не восстанавливаем отменённый продукт.

## Подтверждённая архитектура

Backend: Python, FastAPI ≥0.115, SQLAlchemy async ≥2.0, PostgreSQL/asyncpg, Alembic, pydantic-settings, httpx. Панели: React, TypeScript, Vite, react-router-dom, TanStack Query. Боты: aiogram 3.13+, httpx. CI и тесты в отслеживаемых файлах отсутствуют.

`StaffPermission` имеет ровно два уровня: `CAN_EDIT_MENU` и `CAN_LOOK_ORDERS`. Это записи прав сотрудников по магазину, а не поле role у пользователя. Обычный пользователь может оформлять заказ, но не менять каталог и оплату. Суперадминка обращается к одному backend Market и управляет `Restaurant`; безопасной маршрутизации к независимым проектам нет. Привилегия разработчика — `superadmin_allowed_ids`, не третья роль. Для новой интеграции пустой allowlist закрывает доступ (в старом коде проверка пустого списка пропускается).

Авторизация: проверка Telegram initData, собственный HMAC access JWT, refresh-session в базе и HttpOnly cookie. Переиспользуем session_auth, User, RefreshSession, database/get_db; исправляем срок initData, refresh rotation и область cookie для независимого приложения.

Каталог Market (`Meal`) содержит Numeric price, category, is_available, но не ведёт количественный склад. Заказы и позиции ресторанные, без SKU, отдельной цены упаковки и клиентов-магазинов. Поэтому новые бизнес-модели сохраняют те же слои и Numeric, а ресторанные таблицы не переносятся. Складскую систему не добавляем.

Медиа: `ObjectStorageService` (boto3, Yandex S3), UUID-ключи и legacy local uploads. Сохраняем S3-адаптер; добавляем проверку реального содержимого, локальное хранилище для чистого запуска и закрытую выдачу фотографий магазинов. Реальные uploads не копируются.

Развёртывание: Compose/PostgreSQL 16, отдельные nginx SPA контейнеры, Caddy 2.8 gateway и shared-gateway example. Домены подтверждены `market/deploy/Caddyfile`. Production-конфигурация и живой сервер не доступны. Подготовим правила `/shirin/` перед корневыми proxy, сохраняя префикс API. Docker установлен, daemon на начало аудита выключен.

## Переиспользование и изоляция

Скопированы только перечисленные исходные модули, конфигурация TS, lockfile и API transport React. Новая БД, SHIRIN_ окружение, собственный бот, cookies и localStorage. Ни .git, ни .env, ни дампы, ни зависимости и персональные данные не копируются. LICENSE в обоих исходниках не найден; права на дальнейшее распространение исходной основы следует подтвердить владельцу. Происхождение сохраняется этим документом.

Интеграция в отдельном worktree `../market-shirin-integration`, ветка `feature/shirin-integration`: backend Market проверяет существующий bearer и явный allowlist, затем подписывает запрос к Shirin; браузер не видит секрет. Полноценная страница управления в существующей суперадминке работает через этот proxy. Данные остаются в разных базах.

Официальная Telegram документация проверена: https://core.telegram.org/bots/webapps#locationmanager, https://core.telegram.org/bots/webapps#validating-data-received-via-the-mini-app, https://core.telegram.org/bots/api#setwebhook. LocationManager.init/getLocation поддерживается с Bot API 8.0; ручной адрес/карта остаются доступны. Не используем вымышленную отправку Location из Mini App.
