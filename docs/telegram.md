# Настройка Telegram

Один отдельный бот обслуживает Mini App, административные диалоги и группу. Токен Market/KULCHA не используется. Для проверки нужен отдельный тестовый бот и тестовая группа. Демо token локального `.env` предназначен только для подписания синтетических initData и непригоден для Telegram.

## BotFather и окружение

Создайте бота у BotFather и поместите token в `SHIRIN_USER_BOT_TOKEN` через окружение/секретное хранилище. Настройте описание и кнопку меню Web App на `SHIRIN_MINI_APP_URL`. Адреса панелей — HTTPS с `/shirin/`, суперадминка — `/shirin/superadmin/`, согласно `deployment.md`. Команда `/start` также выдаёт кнопки открытия; административные кнопки появляются по правам пользователя. Отдельная кнопка «Суперадмин Shirin» показывается только Telegram ID из `SHIRIN_SUPERADMIN_ALLOWED_IDS`.

Основные параметры:

| Параметр | Значение |
| --- | --- |
| SHIRIN_USER_BOT_TOKEN | Только token бота Shirin |
| SHIRIN_BOT_USERNAME | Имя бота без @, при необходимости |
| SHIRIN_SUPERADMIN_ALLOWED_IDS | Telegram IDs разработчиков через запятую |
| SHIRIN_SUPERADMIN_APP_URL | HTTPS адрес отдельной суперадминки Shirin |
| SHIRIN_WORK_GROUP_ID | ID выбранной тестовой/рабочей группы |
| SHIRIN_WORK_GROUP_TOPIC_ID | ID темы forum-группы; 0 для общей группы |
| SHIRIN_GROUP_LANGUAGE | ru или uz |
| SHIRIN_BOT_MODE | polling или webhook |
| SHIRIN_WEBHOOK_SECRET | Отдельный случайный secret для webhook |

Пользователю нужно начать диалог с ботом до выдачи ему доступа из админки. Язык выбирается кнопкой RU/UZ и сохраняется в User. Для Mini App выбор отдельно сохраняется в браузере; backend берёт личность только из проверенного initData или собственного access token.

## Polling

Для локального настоящего тестового окружения выберите `SHIRIN_BOT_MODE=polling`. Из `backend` запустите `../.venv/bin/python -m app.bot` и отдельный worker `../.venv/bin/python -m app.services.notifications`. Все панели используют один backend и БД Shirin.

Если для этого же тестового бота уже установлен webhook, оператор сначала удаляет его через официальный Bot API. Код приложения сам не вызывает `deleteWebhook` и не переключает режим существующего бота. Polling и webhook одного бота одновременно не запускаются.

## Webhook

После размещения тестового/production backend на HTTPS выберите `SHIRIN_BOT_MODE=webhook`. Оператор регистрирует через Bot API `setWebhook` URL `https://market.wekulcha.ru/shirin/webhooks/telegram/` с `secret_token`, равным `SHIRIN_WEBHOOK_SECRET`. Передавайте token/secret через безопасное окружение, не сохраняйте их в командной истории или репозитории. Проверьте `getWebhookInfo`: URL, pending updates и last_error.

Endpoint проверяет `X-Telegram-Bot-Api-Secret-Token`, валидирует update, транзакционно сохраняет и дедуплицирует update_id. Отдельный процесс `app.bot` читает очередь; после успешной обработки исходное тело очищается. Запускайте один bot consumer. Worker уведомлений запускается отдельно в обоих режимах.

## Группа и проверка

Добавьте тестового бота в выбранную группу и разрешите отправлять сообщения/фото. Настройте ID группы и, если нужен, темы. Не включайте реальную рабочую группу в окружении с demo-заказами.

В тестовом окружении откройте `/start`, Mini App и оформите небольшой заказ. Проверьте номер, сумму, оба формата, магазин/адрес/карту, optional фото, сообщение и кнопки. Уполномоченный сотрудник последовательно отмечает READY/DELIVERED/PAID; обычному пользователю действия запрещены. В админке видно состояние outbox и message IDs. При временном отказе Telegram запись заказа сохраняется, worker повторяет доставку.

Команды `/export_meals`, `/update_meals`, `/add_meal`, `/remove_meal`, `/set_photo` описаны в `excel.md`. Выбор товара/Excel preview/фото привязан к отправителю, действует 30 минут и отменяется кнопкой либо `/cancel`. Preview импорта имеет отдельный ограниченный срок. Команды управления принимаются в личном диалоге; callbacks статусов — также в группе, с проверкой прав.

В этой реализации Telegram end-to-end пока не выполнен: реальные token и тестовая группа не предоставлены. Handler/transport, подпись initData, webhook, фото-диалог, отказ/повтор отправки проверены изолированными адаптерами.

Официальные контракты: [Mini App и проверка данных](https://core.telegram.org/bots/webapps#validating-data-received-via-the-mini-app), [LocationManager](https://core.telegram.org/bots/webapps#locationmanager), [setWebhook](https://core.telegram.org/bots/api#setwebhook), [getFile](https://core.telegram.org/bots/api#getfile). Лимит приложения 8 MB ниже ограничения скачивания Bot API; runtime также проверяет фактический размер и содержимое.
