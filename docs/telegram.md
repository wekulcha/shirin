# Настройка трёх ботов Shirin

У Shirin три отдельных бота, как в Market/KULCHA. Каждый открывает свою панель и использует свой token. Все три работают с одним backend и БД Shirin; сохранённые права сотрудников общие.

| Бот | Поле `.env` | Кнопка Web App |
| --- | --- | --- |
| User | `SHIRIN_USER_BOT_TOKEN` | `SHIRIN_MINI_APP_URL` — каталог |
| Admin | `SHIRIN_ADMIN_BOT_TOKEN` | `SHIRIN_ADMIN_APP_URL` — панель сотрудников |
| Superadmin | `SHIRIN_SUPERADMIN_BOT_TOKEN` | `SHIRIN_SUPERADMIN_APP_URL` — отдельная суперадминка |

Token ботов Market/KULCHA в эти поля не переносят. Демо token локальной `.env` предназначен только для подписания синтетических initData; demo не подключается к Telegram.

## BotFather и окружение

Для каждого бота у BotFather `/mybots` → Bot Settings → Menu Button задайте соответствующий HTTPS URL из таблицы. В каждом личном диалоге `/start` также показывает кнопку своей панели. Для появления сотрудника в списке доступов ему нужно начать диалог с ботом Shirin или войти в Mini App.

Основные параметры:

| Параметр | Что указать |
| --- | --- |
| `SHIRIN_USER_BOT_TOKEN` | Token user bot Shirin |
| `SHIRIN_ADMIN_BOT_TOKEN` | Token admin bot Shirin |
| `SHIRIN_SUPERADMIN_BOT_TOKEN` | Token superadmin bot Shirin |
| `SHIRIN_BOT_USERNAME` | Username user bot без `@` |
| `SHIRIN_USER_BOT_USERNAME` | Username user bot; имеет приоритет над совместимым `SHIRIN_BOT_USERNAME` |
| `SHIRIN_ADMIN_BOT_USERNAME` | Username admin bot без `@` |
| `SHIRIN_SUPERADMIN_BOT_USERNAME` | Username superadmin bot без `@` |
| `SHIRIN_SUPERADMIN_ALLOWED_IDS` | Числовые Telegram ID через запятую или JSON-массив, как в Market |
| `SHIRIN_WORK_GROUP_ID` | ID выбранной тестовой/рабочей группы; `0` для запуска без отправки |
| `SHIRIN_WORK_GROUP_TOPIC_ID` | ID темы forum-группы; `0` для общей группы |
| `SHIRIN_GROUP_LANGUAGE` | `ru` или `uz` |
| `SHIRIN_BOT_MODE` | `polling` или `webhook` |
| `SHIRIN_WEBHOOK_SECRET` | Случайный secret для webhook; в polling не нужен |
| `SHIRIN_TELEGRAM_PROXY_URL` | HTTP proxy для Bot API, если нужен на этой ВМ |

Два существующих права — `CAN_EDIT_MENU` и `CAN_LOOK_ORDERS`. Admin bot и backend проверяют актуальные права сотрудника. Superadmin bot и backend проверяют `SHIRIN_SUPERADMIN_ALLOWED_IDS`; пустой allowlist закрывает доступ всем. Выдача обоих прав сотруднику не делает его суперадминистратором. Появление кнопки или открытие URL не заменяет проверку прав на сервере.

Язык выбирается кнопкой RU/UZ и сохраняется для пользователя. Backend берёт личность только из проверенного Telegram initData или собственной сессии Shirin. Mini App обращается к `/shirin/api/auth/telegram/user`, панель сотрудников — `/admin`, суперадминка — `/superadmin`: каждому назначению соответствует свой bot token. Данные, подписанные другим ботом, не подходят для входа. Refresh/logout и cookies также разделены по назначению панели.

## Polling

На сервере задайте `SHIRIN_BOT_MODE=polling` и запустите из корня Shirin:

```bash
./up.sh
docker compose ps -a
docker compose logs --tail=80 user_bot admin_bot superadmin_bot worker
```

Compose запускает отдельные процессы `user_bot`, `admin_bot`, `superadmin_bot`. Они читают один `.env`; `SHIRIN_BOT_ROLE` задаётся каждому контейнеру отдельно. Worker уведомлений работает независимо и отправляет заказы через admin bot.

При `SHIRIN_COMPACT_WORKERS=true` или запуске `./up.sh --compact` эти четыре задачи выполняются в одном процессе сервиса `workers`; журнал доступен через `docker logs --tail=80 shirin-workers`. У каждой роли свой Dispatcher и token, права и ссылки панелей сохраняются. Каждый бот обрабатывает по одному update за раз; это ограничивает число одновременно работающих обработчиков, но длинная операция задерживает следующие сообщения этому боту. Ошибка одной задачи вызывает её повторный запуск через 5 секунд; завершение всего процесса затрагивает все четыре задачи. Для смены режима используйте `up.sh`, который останавливает прежние pollers перед запуском новых.

Для локального настоящего тестового окружения из `backend` в разных терминалах:

```bash
../.venv/bin/python -m app.bot --role user
../.venv/bin/python -m app.bot --role admin
../.venv/bin/python -m app.bot --role superadmin
../.venv/bin/python -m app.services.notifications
```

Приложение не удаляет webhook автоматически. Если для конкретного бота уже установлен webhook, перед polling оператор удаляет его через Bot API. Одновременные pollers одного и того же token конфликтуют; для каждого бота должен работать один poller.

## Webhook

После размещения backend на HTTPS задайте `SHIRIN_BOT_MODE=webhook`. Оператор регистрирует `setWebhook` **для каждого token отдельно**:

| Бот | URL |
| --- | --- |
| User | `https://market.wekulcha.ru/shirin/webhooks/telegram/user/` |
| Admin | `https://market.wekulcha.ru/shirin/webhooks/telegram/admin/` |
| Superadmin | `https://market.wekulcha.ru/shirin/webhooks/telegram/superadmin/` |

Во всех регистрациях `secret_token` равен `SHIRIN_WEBHOOK_SECRET`. Token и secret передавайте через окружение/секретное хранилище, не записывайте в репозиторий. Через `getWebhookInfo` каждого бота проверьте URL, pending updates и last_error. Старый unsuffixed endpoint `/shirin/webhooks/telegram/` остаётся совместимым алиасом user bot.

Backend проверяет `X-Telegram-Bot-Api-Secret-Token`, валидирует и транзакционно сохраняет update. Очередь и дедупликация разделены по bot role: одинаковый `update_id` разных ботов не конфликтует. Три bot consumers читают свои очереди; после успешной обработки исходное тело очищается. Сохраняемые административные диалоги выполняются только в admin bot; user/superadmin bots не меняют их состояние. Цикл уведомлений работает и в polling, и в webhook: отдельным процессом по умолчанию либо задачей общего `workers` в компактном режиме.

Для компактного webhook нужен запас соединений под транзакции очереди и вложенные обработчики. Compose задаёт общему процессу пул `SHIRIN_COMPACT_DATABASE_POOL_SIZE=4` плюс до `SHIRIN_COMPACT_DATABASE_MAX_OVERFLOW=2` дополнительных соединений. При ручном запуске `python -m app.workers` значения передаются как `SHIRIN_DATABASE_POOL_SIZE`/`SHIRIN_DATABASE_MAX_OVERFLOW`; их сумма для PostgreSQL webhook должна быть не меньше 5. API и отдельные процессы по умолчанию используют пул 2 + 1.

## Рабочая группа и проверка

Добавьте **admin bot Shirin** в выбранную группу и разрешите отправлять сообщения/фото. Настройте её ID и при необходимости ID темы. User и superadmin bots в группу для отправки заказов не нужны. В окружении demo группа равна `0`; реальные заказы туда не отправляются.

Проверьте три входа: user bot открывает каталог, разрешённый сотрудник через admin bot — панель сотрудников, Telegram ID из allowlist через superadmin bot — суперадминку. Обычному пользователю admin/superadmin вход должен быть запрещён. Затем оформите тестовый заказ: проверьте номер, сумму UZS, форматы товара, магазин/адрес/карту и сообщение admin bot в группе.

Кнопки статуса проверяют права `CAN_LOOK_ORDERS`: уполномоченный сотрудник отмечает READY/DELIVERED/PAID, обычному пользователю действия запрещены. В админке видно состояние outbox и message IDs. При временном отказе Telegram заказ остаётся в базе; worker повторяет доставку уведомления.

Команды `/export_meals`, `/update_meals`, `/add_meal`, `/remove_meal`, `/set_photo` выполняются в admin bot с проверкой `CAN_EDIT_MENU`; подробнее — [excel.md](excel.md). Суперадминистратор тоже может использовать их через admin bot. Выбор товара/Excel preview/фото привязан к отправителю, отменяется кнопкой либо `/cancel` в этом боте. Команды управления принимаются в личном диалоге; callbacks статусов admin bot — также в группе с проверкой прав.

## Переход с прежней версии с одним ботом

`up.sh` удаляет старый Compose-сервис `bot` перед запуском трёх новых процессов. Пользовательский token, каталог, заказы и выданные права сохраняются. Старые кнопки user bot для открытия админки/суперадминки больше не подходят: вход теперь подписывает соответствующий admin/superadmin bot. Откройте нужного бота заново через `/start` и обновите его Menu Button у BotFather.

Незаконченный Excel/фото-диалог прежнего user bot начните заново в admin bot. Старые сообщения группы, отправленные user bot, не переносятся другому Telegram-боту; их административные callback-кнопки больше не выполняются. Такие заказы остаются доступны в панели сотрудников, а новые уведомления отправляет admin bot. До отправки новых заказов добавьте его в ту же рабочую группу.

Локальные выполненные проверки описаны в [test-results.md](test-results.md). Проверка подписи/handler изолированными тестами не заменяет проверку реальной отправки сообщения, HTTPS и доступности Bot API с выбранной ВМ.

Официальные контракты: [Mini App и проверка данных](https://core.telegram.org/bots/webapps#validating-data-received-via-the-mini-app), [LocationManager](https://core.telegram.org/bots/webapps#locationmanager), [setWebhook](https://core.telegram.org/bots/api#setwebhook), [getFile](https://core.telegram.org/bots/api#getfile).
