# Shirin в Яндекс Облаке

Если Market/KULCHA уже работают на `kulcha-test-vm`, Shirin можно запустить **на этой же ВМ**: отдельные контейнеры и БД, три бота и свои маршруты `/shirin/` в общем Caddy. Существующие домены, группа безопасности и DNS сохраняются. Новая ВМ и новые домены для такого запуска не требуются.

## 1. Код на существующей ВМ

После commit/push новых файлов на Mac в SSH-сессии на сервере:

```bash
cd ~/shirin
git pull --ff-only
docker compose version
```

Нужны Docker Engine и Compose plugin 2.17+ (`up --wait`). Python/Node.js устанавливаются в images; отдельно на сервере их устанавливать не нужно. Если репозиторий ещё не клонирован, используйте GitHub-аккаунт/deploy key с доступом к `wekulcha/shirin` и клонируйте его в отдельную папку `~/shirin`.

## 2. Заполнение `.env`

Рабочий файл — `~/shirin/.env`, рядом с `docker-compose.yml`. Если он уже существует, **сохраните его и дополните**, не копируйте поверх шаблон:

```bash
cd ~/shirin
cp .env .env.backup
chmod 600 .env .env.backup
nano .env
```

Только для первого запуска, когда файла ещё нет:

```bash
cp .env.example .env
chmod 600 .env
nano .env
```

В nano сохранить Ctrl+O, Enter; выйти Ctrl+X.

| Переменная | Что вписать |
| --- | --- |
| `SHIRIN_ENVIRONMENT` | `production` |
| `SHIRIN_USER_BOT_TOKEN` | Token user bot **Shirin**, из BotFather |
| `SHIRIN_ADMIN_BOT_TOKEN` | Token admin bot **Shirin** |
| `SHIRIN_SUPERADMIN_BOT_TOKEN` | Token superadmin/ops bot **Shirin** |
| `SHIRIN_BOT_USERNAME` | Username user bot без `@` |
| `SHIRIN_USER_BOT_USERNAME` | Username user bot без `@`; имеет приоритет над `SHIRIN_BOT_USERNAME` |
| `SHIRIN_ADMIN_BOT_USERNAME` | Username admin bot без `@` |
| `SHIRIN_SUPERADMIN_BOT_USERNAME` | Username superadmin/ops bot без `@` |
| `SHIRIN_SUPERADMIN_ALLOWED_IDS` | Твой числовой Telegram ID; несколько — через запятую или JSON-массив `[123456789,987654321]` |
| `SHIRIN_POSTGRES_PASSWORD` | Прежний пароль существующей БД Shirin; случайный пароль только для новой БД |
| `SHIRIN_DATABASE_URL` | `postgresql+asyncpg://shirin:ТОТ_ЖЕ_ПАРОЛЬ@postgres:5432/shirin` |
| `SHIRIN_AUTH_ACCESS_SECRET` | Сохранить существующий secret; для первого запуска создать отдельный случайный secret 32+ символов |
| `SHIRIN_MINI_APP_URL` | `https://market.wekulcha.ru/shirin/` |
| `SHIRIN_ADMIN_APP_URL` | `https://adminmarket.wekulcha.online/shirin/` |
| `SHIRIN_SUPERADMIN_APP_URL` | `https://adminmarket.wekulcha.online/shirin/superadmin/` |
| `SHIRIN_CORS_ALLOWED_ORIGINS` | `https://market.wekulcha.ru,https://adminmarket.wekulcha.online` |
| `SHIRIN_SHARED_GATEWAY` | `true` |
| `SHIRIN_GATEWAY_NETWORK` | `shirin_gateway`, если собственное имя сети не задано |
| `SHIRIN_SHARED_GATEWAY_CONTAINER` | Имя уже работающего gateway-контейнера; можно оставить пустым и подключить сеть вручную |
| `SHIRIN_COMPACT_WORKERS` | `true` для экономии памяти: три бота и уведомления в одном процессе; по умолчанию `false` |
| `SHIRIN_BOT_MODE` | `polling` для этих новых ботов; если настроен webhook, см. [telegram.md](telegram.md) |
| `SHIRIN_TELEGRAM_PROXY_URL` | Используемый на ВМ Telegram HTTP proxy, если требуется; иначе пусто |
| `SHIRIN_WORK_GROUP_ID` | ID рабочей группы; `0` для запуска без отправки уведомлений |
| `SHIRIN_WORK_GROUP_TOPIC_ID` | ID темы либо `0` |
| `SHIRIN_GROUP_LANGUAGE` | `ru` или `uz` |
| `SHIRIN_WEBHOOK_SECRET` | В polling не требуется; для webhook отдельное случайное значение |
| `SHIRIN_AUTH_COOKIE_DOMAIN` | Пусто для cookies на hostname соответствующей панели |
| `SHIRIN_AUTH_COOKIE_SECURE` | `true` |
| `SHIRIN_TIMEZONE` | `Asia/Tashkent` |
| `SHIRIN_UPLOADS_DIR` | `/app/uploads` |
| Object Storage bucket/keys/public URL | Сохранить настроенное хранилище Shirin; если не используется, оставить пустыми для media volume |

Для новой БД и первого auth secret дважды выполните `openssl rand -hex 32`, используя разные результаты. Пароль в URL должен совпадать с `SHIRIN_POSTGRES_PASSWORD`. Изменение `.env` не меняет пароль существующей PostgreSQL: при обновлении сохраняйте оба прежних значения.

Для admin/superadmin bots используются **два отдельных token**. Нельзя ставить один token во все три поля: три pollers одного бота будут конфликтовать. Секреты остаются на сервере; `.env` исключена из Git. Локальная demo `.env` с SQLite на production не подходит.

## 3. Запуск трёх ботов и панелей

На существующей ВМ из `~/shirin`:

```bash
./up.sh --shared
docker compose ps -a
docker compose logs --tail=80 backend worker user_bot admin_bot superadmin_bot
```

Если Docker требует sudo, выполняйте `sudo ./up.sh --shared`. Скрипт использует `.env`, проверяет Compose, последовательно собирает backend и три панели, затем ждёт PostgreSQL, применяет миграции и запускает сервисы. `migrate` должен завершиться с кодом 0. Если указан `SHIRIN_SHARED_GATEWAY_CONTAINER`, скрипт подключает этот действующий контейнер к сети Shirin; Caddyfile автоматически не переписывается.

Названия контейнеров ботов: `shirin-user-bot`, `shirin-admin-bot`, `shirin-superadmin-bot`. Для обновления повторяйте `git pull --ff-only`, затем `./up.sh`; для остановки только Shirin используйте `./down.sh`. База и фотографии сохраняются в volumes.

На ВМ с небольшим запасом RAM используйте `SHIRIN_COMPACT_WORKERS=true` в существующей `.env` и `./up.sh --shared --compact`. Три бота и уведомления будут работать в одном контейнере `shirin-workers`; его журнал: `docker logs --tail=80 shirin-workers`. При первом переходе нужна сборка. Повторный запуск уже собранной версии возможен через `./up.sh --shared --no-build`; этот флаг не применяет изменения исходников после `git pull`.

По предоставленному замеру от 7 октября одни контейнеры Kulcha и Shirin потребляли около 1,67 GiB, а Docker видел около 4 ГБ памяти ВМ. Для исходной ВМ с 2 ГБ запас под ОС и сборку слишком мал. Причина перезагрузок пока не подтверждена: [измерения, ограничения компактного режима и дальнейшая диагностика](architecture-and-resources.md).

## 4. Маршруты в существующем Caddy

В `deploy/Caddyfile.routes.example` есть готовые правила `/shirin/`. Добавьте их в действующие блоки `market.wekulcha.ru` и `adminmarket.wekulcha.online` перед proxy корневых приложений. **Существующие корневые маршруты Market оставьте.** Gateway должен быть подключён к сети `shirin_gateway`; способ закрепить сеть и проверить merged Caddyfile — в [deployment.md](deployment.md).

На этой же ВМ не нужно запускать `./up.sh --cloud`: он добавляет собственный Caddy на 80/443, которые уже заняты действующим gateway. DNS существующих Market-доменов не меняется.

После добавления маршрутов проверьте:

```bash
curl -fsS https://market.wekulcha.ru/shirin/api/health
```

Ожидается `{"status":"ok","project":"shirin"}`. Mini App, admin и superadmin panel должны открываться по своим URL; без собственной сессии требуется вход через соответствующего бота. Проверка backend-контейнера сама по себе не проверяет маршруты внешнего Caddy.

## 5. Telegram и первый вход

В BotFather для **каждого** бота настройте Menu Button на URL соответствующей панели из `.env`. Затем:

1. User bot: `/start` → каталог Shirin.
2. Superadmin/ops bot: `/start` под Telegram ID из allowlist → «Суперадмин Shirin». Добавьте товары/Excel и разрешённым сотрудникам выдайте существующие права.
3. Admin bot: `/start` сотрудника → административная панель с его правами.
4. Добавьте admin bot Shirin в рабочую группу, заполните group/topic ID. Оформите тестовый заказ и проверьте уведомление и кнопки статусов.

Подпись входа проверяется по token бота той панели, которую открывает пользователь. Пустой allowlist запрещает суперадминистративный вход. Группа `0` оставляет уведомления в outbox до настройки. Подробнее — [telegram.md](telegram.md) и [superadmin.md](superadmin.md).

## 6. Если нужна отдельная новая ВМ

Это отдельный способ размещения. Создайте Linux-ВМ в [консоли Яндекс Облака](https://console.yandex.cloud/) с SSH-ключом и публичным статическим IP; описание полей — в [официальной инструкции](https://yandex.cloud/ru/docs/compute/operations/vm-create/create-linux-vm). В группе безопасности откройте TCP 22 только со своего IP и TCP 80/443 для HTTPS; PostgreSQL оставьте внутри Compose.

Установите Docker по [официальной инструкции Ubuntu](https://docs.docker.com/engine/install/ubuntu/), затем клонируйте Shirin в отдельную папку. Для этой новой ВМ используйте `deploy/yandex-cloud.env.example`, заполните три token и secrets. Выберите собственные домены и направьте их A-записи на IP новой ВМ. Существующие Market-домены не перенаправляйте: это изменит доступ к Market.

Согласованно задайте `SHIRIN_PUBLIC_HOST`/`SHIRIN_ADMIN_HOST`, три URL и CORS. HOST — только имя без `https://` и пути. Например, если отдельно выбраны `shirin.example.com` и `adminshirin.example.com`:

```dotenv
SHIRIN_PUBLIC_HOST=shirin.example.com
SHIRIN_ADMIN_HOST=adminshirin.example.com
SHIRIN_MINI_APP_URL=https://shirin.example.com/shirin/
SHIRIN_ADMIN_APP_URL=https://adminshirin.example.com/shirin/
SHIRIN_SUPERADMIN_APP_URL=https://adminshirin.example.com/shirin/superadmin/
SHIRIN_CORS_ALLOWED_ORIGINS=https://shirin.example.com,https://adminshirin.example.com
SHIRIN_SHARED_GATEWAY=false
```

На новой ВМ без другого gateway:

```bash
./up.sh --cloud
docker compose -f docker-compose.yml -f deploy/docker-compose.cloud.yml ps -a
docker compose -f docker-compose.yml -f deploy/docker-compose.cloud.yml logs --tail=80 gateway user_bot admin_bot superadmin_bot
# Остановка с сохранением данных:
./down.sh --cloud
```

Cloud override добавляет Caddy и сохраняет сертификаты в volume. HTTPS требует, чтобы HOST-имена разрешались в IP этой ВМ и 80/443 были доступны. [Автоматический HTTPS Caddy](https://caddyserver.com/docs/automatic-https). Настройки DNS меняет только оператор выбранного размещения; приложение их автоматически не меняет.

## 7. Данные и выполненные проверки

Backup PostgreSQL и media volume храните вне ВМ. Для обновлений используйте `up.sh`; `down.sh` сохраняет данные. Команда Docker `down -v` удаляет volumes и для обычного обновления не нужна.

Локальная подготовка файлов не выполняет deployment на ВМ, не меняет живые webhook и не применяет миграции к production-БД. Фактически выполненные проверки описаны в [test-results.md](test-results.md).
