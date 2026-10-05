# Результаты проверок — 5 октября 2026

Проверена версия с тремя отдельными ботами Shirin, самостоятельной суперадминкой и скриптами up.sh/down.sh. Данные тестов синтетические; PostgreSQL 18 работает в отдельном cluster `/private/tmp/shirin-postgres` на порту 5544. Локальный runtime: Python 3.14, Chromium Playwright, мобильный и desktop viewport.

| Проверка | Результат |
| --- | --- |
| Все backend-тесты на выделенной PostgreSQL `shirin_test` | **49 passed** |
| Все backend-тесты на временной SQLite | **48 passed, 1 skipped**; конкурентное оформление проверяется на PostgreSQL |
| Миграция старой схемы PostgreSQL и SQLite до head | Старые webhook сохранены как user; одинаковые update ID трёх ботов независимы |
| Alembic check на мигрированных PostgreSQL и SQLite | Расхождений с моделями нет; четыре миграции |
| Ruff backend/scripts и ESLint трёх панелей | Проходят |
| TypeScript и три Vite production-сборки | Проходят |
| `SHIRIN_BUILT_PREVIEW=1 npx playwright test` через локальный Caddy | **6 passed** |
| Caddy local/routes/cloud: adapt и редиректы | Каждый redirect получает 308 и правильный Location; четыре локальных корневых URL проверены HTTP-запросами |
| Compose с синтетической `.env`, shared/cloud | Конфигурации проходят проверку |
| Bash и startup/shutdown сценарии с подменённым Docker | Миграции до runtime, остановка при ошибке, сохранение volumes, подключение gateway, отказ при пустых/одинаковых токенах |
| Telegram getMe/getWebhookInfo трёх предоставленных ботов | Имена подтверждены; webhook отсутствуют, polling совместим. Сообщения не отправлялись |
| Исходные Market/KULCHA | Рабочие деревья чистые |
| Git/секретные файлы | `.env`, `.env.production`, outputs, demo-БД, media, deps и builds игнорируются |

## Авторизация и боты

Для user/admin/superadmin проверены соответствующие подписи initData, отказ по токенам других ботов, отсутствующие токены, права сотрудников и закрытый allowlist. Три refresh-cookie независимы: rotation, повторное использование, подстановка cookie другого бота, отзыв прав и выход проверены. PostgreSQL logout блокирует только RefreshSession, без блокировки nullable joined User.

Настоящий aiogram dispatcher получает свою роль и показывает только соответствующую панель. User/superadmin bots не могут применить или отменить admin-диалог. Фото/Excel подтверждения проверяют отправителя, срок, версии товара и актуальные права. Уведомления используют admin bot; создание транспорта с HTTP proxy проверено без сетевой отправки. Webhook дедупликация разделена по роли.

## Панели и бизнес-операции

Браузер проверяет корзину 306000 UZS, выбор клиента и подтверждение точки, снимок адреса, оформление заказа без фото, вложенные URL, refresh, черновики вкладок, каталог/клиентов, Excel preview/apply и язык. Суперадминка проверена на обзор, выдачу/отзыв прав, оплату/доставку/завершение, выход и отказ сотруднику.

Отдельный сценарий открывает admin и superadmin на одном hostname: выход из admin оставляет superadmin-сессию рабочей. Настоящий Telegram SDK не может автоматически восстановить тот же вход после выхода. Новый initData или явное повторение входа допускается; sessionStorage содержит только fingerprint.

Backend дополнительно проверяет Decimal UZS, форматы продажи, независимую цену ящика, снимки, идемпотентность, PostgreSQL race, доступ к клиентам/private фото, Excel roundtrip/атомарность/версии и outbox retry/lease/message IDs.

## Внешнее окружение

Docker daemon локально выключен: контейнерные Python 3.12/PostgreSQL 16 и nginx images не запускались. Реальная отправка заказов в Telegram, S3, production HTTPS и маршруты существующего gateway требуют проверки на выбранной ВМ. Production-сервер, webhook и база не изменялись.

Готовая приватная production-конфигурация дополнена тремя токенами и проверенными usernames; ранее созданные пароль БД, access secret, домены, CORS и timezone сохранены. Рабочая группа остаётся `0` до указания её ID.
