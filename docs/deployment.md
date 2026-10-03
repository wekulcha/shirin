# Развёртывание Shirin

Production ещё не изменён. Конфигурации подготовлены для собственного backend, БД и трёх панелей Shirin.

## Адреса и префиксы

| Назначение | URL |
| --- | --- |
| Mini App | `https://market.wekulcha.ru/shirin/` |
| Панель сотрудников | `https://adminmarket.wekulcha.online/shirin/` |
| Суперадминка | `https://adminmarket.wekulcha.online/shirin/superadmin/` |
| API | `/shirin/api/` на обоих доменах |
| Telegram webhook | `https://market.wekulcha.ru/shirin/webhooks/telegram/` |

Vite base/router basename совпадают с путями каждой панели. Caddy сохраняет префикс `/shirin/`; API/webhook обрабатываются до SPA, `/shirin/superadmin/*` — до общей панели сотрудников. nginx возвращает fallback для вложенных страниц и настоящий 404 для отсутствующих assets; API 404 остаётся JSON.

Cookie — `shirin_refresh_token`, path `/shirin/api/auth`, host-only, HttpOnly, Secure, SameSite=Lax. Все панели используют сессию собственного бота Shirin. CORS перечислен явно; refresh/logout проверяют Origin. Браузерные ключи имеют префикс `shirin.`, корзина отделена по Telegram ID. Service worker не используется.

## Окружение и Compose

1. Создать production `.env` из `.env.example`: собственный пароль/URL БД, случайный access secret (32+ символов), token бота Shirin, ID рабочей группы, явный список Telegram ID суперадминистраторов и три HTTPS URL панелей. Пароль в URL должен быть URL-encoded при наличии специальных символов. Demo `.env` предназначена для локальной SQLite.
2. Compose создаёт собственную сеть `shirin_gateway` (имя меняется через `SHIRIN_GATEWAY_NETWORK`). Backend и три панели подключаются к ней; Postgres доступен во внутренней сети проекта. Внешнему gateway нужен доступ к сети Shirin. Если используется общий Caddy, подключите его контейнер к `shirin_gateway` и закрепите подключение в его Compose. Авторизация и БД Market для этого не требуются.
3. Volumes `postgres_data` и `media_data` принадлежат проекту `shirin`; подготовить их backup/restore. Фото товаров поддерживают отдельный S3 bucket/prefix, фото магазинов выдаются с проверкой доступа из закрытого media volume.

Команды для выбранного серверного окружения:

```bash
docker compose config -q
docker compose build
docker compose up -d
```

`migrate` выполняет Alembic до старта backend/worker/bot. Все миграции предназначены только для БД Shirin. Миграция `7b425c210cc9` удаляет служебную таблицу старой интеграции, сохраняя бизнес-данные. Связь с Market, HMAC proxy и интеграционные secrets больше не используются. PostgreSQL применяется в production; SQLite — в локальных demo/tests.

Compose не занимает порты 80/443. В `deploy/Caddyfile.routes.example` подготовлены маршруты Shirin. При объединении с существующим gateway перенесите только `handle /shirin…` в уже имеющиеся блоки доменов, перед корневым handler; существующий корневой proxy сохраните. Завершающий `respond 404` в примере подходит для самостоятельного gateway. Проверьте объединённый файл до перезагрузки:

```bash
caddy validate --config /path/to/merged/Caddyfile --adapter caddyfile
```

## Telegram и суперадминистратор

`/start` бота Shirin выдаёт кнопки Mini App, панели сотрудников по правам и суперадминки по `SHIRIN_SUPERADMIN_ALLOWED_IDS`. Пустой allowlist запрещает вход всем. `SHIRIN_SUPERADMIN_APP_URL` указывает на отдельный интерфейс; каждую привилегированную операцию проверяет backend. Инструкции — [superadmin.md](superadmin.md) и [telegram.md](telegram.md).

Polling и webhook взаимоисключающие. Скрипты не регистрируют/удаляют webhook автоматически. Outbox worker работает постоянно; при незаданной группе/token сохраняет задания в PENDING. Для webhook запускается один bot consumer, который читает сохранённые updates; backend проверяет secret и дедуплицирует их.

## Проверка production-сборок локальным Caddy

```bash
make build
# Backend demo должен работать на 8083:
SHIRIN_PROJECT_ROOT="$PWD" caddy run --config deploy/Caddyfile.local --adapter caddyfile
.venv/bin/python scripts/demo.py --links-only --built
cd user_panel
SHIRIN_BUILT_PREVIEW=1 npx playwright test
```

Порты `8093`/`8094`/`8095` обслуживают готовые сборки Mini App/сотрудников/суперадминки. Суперадминка дополнительно доступна через `8094/shirin/superadmin/`. Проверки включают прямые вложенные URL, refresh, вход/отказ, права, оплату/доставку и logout.

Docker daemon здесь выключен: Compose проверен, контейнерные images не запускались. Реальные HTTPS/Telegram/S3 требуют выбранного серверного или тестового окружения. Размещение на сервере этой локальной работой не выполнено.
