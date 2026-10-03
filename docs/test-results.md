# Результаты проверок — 3 октября 2026

Проверки выполнены на этой машине с синтетическими данными. Локальная PostgreSQL 18 использует отдельный cluster `/private/tmp/shirin-postgres`, порт 5544, пользователя `shirin_test`. Тестовые базы не связаны с исходными проектами. Runtime: Python 3.14; Chromium Playwright, iPhone 13 viewport и desktop 1440×980. Установленные Python версии сохранены в `backend/requirements.lock.txt`, npm — в lockfiles каждой панели.

| Проверка | Результат |
| --- | --- |
| PostgreSQL: `TEST_DATABASE_URL=postgresql+asyncpg://shirin_test@127.0.0.1:5544/shirin_test .venv/bin/pytest -q` | **23 passed** |
| SQLite: `.venv/bin/pytest -q` | **22 passed, 1 skipped**; race оформления специально проверяется на PostgreSQL |
| Пустая PostgreSQL `shirin_migration_check`: `alembic upgrade head`, `alembic check` | Обе миграции применены; нет новых операций/расхождений |
| `make check` | Ruff backend/scripts и ESLint обеих панелей Shirin проходят |
| `make build` | TypeScript и обе Vite production-сборки проходят |
| Market: build + ESLint новых/изменённых UI модулей | Проходят |
| Market: полный ESLint | Две ошибки в неизменённом `src/context/AuthContext.tsx`: react-hooks/set-state-in-effect и react-refresh/only-export-components. Исходная основа, вне интеграции |
| `SHIRIN_BUILT_PREVIEW=1 SHIRIN_MARKET_SMOKE=1 npx playwright test` | **4 passed**; Shirin обслуживается из dist через Caddy, Market — из существующей панели Vite |
| `.venv/bin/python scripts/run-market-demo.py --check` | Реальный HTTP между изолированными Market/Shirin: bearer/allowlist, CRUD, клиенты, заказы/доступы, multipart Excel, изоляция и прежние root API проходят |
| Caddy 2.8.4 validate | `deploy/Caddyfile.local`, `deploy/Caddyfile.routes.example` и оба изменённых gateway примера Market валидны |
| Compose обоих проектов: `docker compose config -q` | Проходит |
| Наличие случайной рублёвой валюты в Shirin app/UI | RUB/₽/рублёвые подписи не обнаружены |
| `git diff --check` | Проходит; `.env`, demo БД, media, outputs, deps и builds игнорируются |

## Что подтверждают тесты

Backend проверяет три формата продажи, отключение лишних цен, независимую цену ящика, Decimal итоги, неизменность снимков, повтор и конкурирующее оформление. Доставка/оплата тестируются в обоих порядках, повторные события не появляются. Обычный пользователь не получает права каталога/оплаты/чужих клиентов и private фото.

Авторизация проверяет HMAC initData, срок, `+` и новые поля, неправильный token проекта, replay integration nonce, issuer access token, одноразовый refresh/cookie scope и webhook secret/deduplication. PostgreSQL тест обновления сессии подтвердил исправление ограничения блокировки nullable join.

Excel проверяет круговой экспорт/импорт, текстовый SKU с нулями и значениями вида `=…`, новый SKU, цены/форматы, дубли, отсутствующие/пустые поля, 0/false/очистку, archive, сохранность фото, формулы/макросы/external relationships, ошибки строк, повторное применение, изменённые права/срок/версию. Инъекция ошибки flush подтверждает откат всех товаров, журнала и состояния preview.

Bot handler тесты подтверждают прикрепление фото только к выбранному товару/пользователю, preview и явное подтверждение, истечение ожидания и проверку доступа. Outbox адаптеры проверяют временную ошибку, retry, restart, частично доставленное сообщение, reclaim истекшей аренды, RU/UZ и UTF-16 лимиты длинного сообщения.

Браузер проверяет смешанную корзину 306000 UZS, справочник клиента, подтверждение новых координат, снимок адреса, заказ без фото, прямой вход/refresh деталей, две независимые вкладки checkout, Excel preview/apply, каталог/клиентов/доступы, сохранение UZ и существующий root «Магазины» Market. Проверка мобильной страницы не обнаружила горизонтального overflow или JS ошибок. Скриншоты находятся в игнорируемой `outputs/` и визуально просмотрены.

## Что ещё требуется снаружи

- **Telegram end-to-end:** реальные token и явно выбранная тестовая группа не предоставлены. Настроить отдельное тестовое окружение и пройти сценарий по `telegram.md`. Реальные сообщения не отправлялись.
- **S3:** нет тестовых credentials/bucket. Локальные media проверены, унаследованный S3 adapter подготовлен; проверить upload/public URL на выбранном тестовом bucket.
- **Docker:** daemon не запущен. Конфигурация проходит; собрать и запустить images при доступном daemon. Python 3.12/PostgreSQL 16 внутри images здесь не выполнялись.
- **Production HTTPS:** сервер/gateway/DNS не изменены; конфигурации готовы. После отдельного указания разместить контейнеры, объединить фактический Caddy и проверить оба домена/refresh/webhook/TLS.
- **Git remote:** создать приватный `shirin` у выбранного провайдера, подключить origin и push main/develop по README. Инструмента создания repo нет, `gh` не установлен; remote/draft PR не существуют. Ветка интеграции Market также локальная.

Локальный обзор доступен через `make dev`. Внешние действия не являются скрытыми выполненными этапами и не отменяют проверенный код локальных сценариев.
