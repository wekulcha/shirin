# Запуск рядом с Market

Production ещё не изменён. Ни DNS, ни реальные боты, ни живая БД, ни gateway не переключались. Конфигурация подготовлена и проверена локально.

## Адреса и префиксы

| Назначение | URL |
| --- | --- |
| Mini App | `https://market.wekulcha.ru/shirin/` |
| Админка | `https://adminmarket.wekulcha.online/shirin/` |
| API | `/shirin/api/` на обоих доменах |
| Telegram webhook | `https://market.wekulcha.ru/shirin/webhooks/telegram/` |

Vite base и router basename — `/shirin/`. API и media URLs включают префикс. Caddy **сохраняет** `/shirin/` при reverse proxy. API/webhook обрабатываются перед SPA. nginx хранит сборку в `/usr/share/nginx/html/shirin`, assets получают настоящий 404, страницы — fallback к `/shirin/index.html`. API 404 возвращается JSON. Cookie — `shirin_refresh_token`, path `/shirin/api/auth`, host-only, HttpOnly, Secure, SameSite=Lax. CORS перечислен явно; refresh/logout дополнительно проверяют Origin. Ключи браузерного хранения начинаются с `shirin.`, корзина отделена по Telegram ID. Service worker не используется.

## Подготовка окружения

1. Создать отдельную production `.env` из `.env.example`. Локальную демо `.env` в production не переносить. Задать пароль БД и соответствующий URL, случайный access secret (32+ символов), отдельный Telegram token, ID тестовой/рабочей группы, allowlist существующих разработчиков и секрет интеграции. Пароль в URL должен быть URL-encoded при наличии специальных символов.
2. В Market настроить `MARKET_SHIRIN_API_BASE` и `MARKET_SHIRIN_INTEGRATION_SECRET`; см. `market-integration.md`.
3. `SHIRIN_GATEWAY_NETWORK` указывает на реально существующую сеть gateway/Market, по примеру `kulcha-market_default`. Контейнеры `shirin-backend`, `shirin-user-panel`, `shirin-admin-panel` подключаются к ней. Postgres остаётся в своей внутренней сети.
4. Подготовить backup и проверку восстановления отдельных БД и volumes. `postgres_data` и `media_data` принадлежат только Compose-проекту `shirin`. Фото товаров могут храниться в отдельном S3 bucket/prefix через унаследованный адаптер; фото магазинов остаются в закрытом media volume и выдаются с проверкой доступа.

После отдельного указания на production-развёртывание:

```bash
docker compose config -q
docker compose build
docker compose up -d
```

`migrate` выполняет Alembic до запуска backend/worker/bot. Таблицы создаются в **новой БД «Ширин»**. User/RefreshSession сохраняют контракт исходной основы; следующая миграция добавляет язык. Не запускайте эти миграции на БД Market. Никакие клиенты, заказы или токены из Market автоматически не импортируются. SQLAlchemy поддерживает PostgreSQL production и SQLite только для локального demo/test.

Compose не занимает общие порты 80/443. Дополнения Caddy находятся в worktree Market и `deploy/Caddyfile.routes.example`: объединить с фактическим gateway, не добавлять повторные блоки доменов. При shared gateway контейнер должен быть подключён к выбранной сети. Минимальные существующие proxy Market сохранены. Проверить конфигурацию до перезагрузки:

```bash
caddy validate --config /path/to/merged/Caddyfile --adapter caddyfile
```

## Telegram

У единственного бота есть кнопки открытия Mini App и админки. Admin URL открывается тем же ботом, backend проверяет его же initData. Инструкции BotFather, polling/webhook и группы — в `telegram.md`. Polling и webhook взаимоисключающие. Конфигурация/скрипты не вызывают setWebhook или deleteWebhook автоматически.

Outbox worker должен быть запущен постоянно. При незаданной группе/token он оставляет задания в PENDING, сохраняя заказы. Не включайте реальную группу для демонстрационных данных. Для webhook используется один bot consumer; backend только проверяет секрет и транзакционно сохраняет update. После обработки исходное тело update очищается.

## Проверка сборок локальным Caddy

```bash
make build
# Backend demo на 8083 уже запущен:
SHIRIN_PROJECT_ROOT="$PWD" caddy run --config deploy/Caddyfile.local --adapter caddyfile
.venv/bin/python scripts/demo.py --links-only --built
cd user_panel
SHIRIN_BUILT_PREVIEW=1 npx playwright test --grep-invert 'existing Market'
```

Локальные порты 8093/8094 обслуживают готовые сборки без Vite. В проверках подтверждены refresh `/shirin/checkout`, `/shirin/orders/:id`, административные вложенные страницы, статика и JSON 404 API. HTTPS и реальные домены проверяются после размещения на сервере; сертификаты для них локально не выпускались. Docker daemon на этой машине не запущен: Compose config проверен, production images здесь не запускались.
