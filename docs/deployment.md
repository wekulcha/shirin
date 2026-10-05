# Развёртывание Shirin

Shirin запускается отдельным Compose-проектом: своя PostgreSQL, backend, worker уведомлений, три панели и три бота. На ВМ с уже работающими Market/KULCHA приложение подключается к существующему gateway. Домены и корневые страницы соседних приложений сохраняются.

## Адреса и префиксы

| Назначение | URL |
| --- | --- |
| Mini App | `https://market.wekulcha.ru/shirin/` |
| Панель сотрудников | `https://adminmarket.wekulcha.online/shirin/` |
| Суперадминка | `https://adminmarket.wekulcha.online/shirin/superadmin/` |
| API | `/shirin/api/` на обоих доменах |
| Telegram webhooks | `/shirin/webhooks/telegram/user/`, `/admin/`, `/superadmin/` на публичном домене |

Vite base/router basename совпадают с путями панелей. Caddy сохраняет префикс `/shirin/`; API и webhook обрабатываются до SPA, `/shirin/superadmin/*` — до общей панели сотрудников. nginx возвращает fallback для вложенных страниц; отсутствующие assets и неизвестные API получают настоящий 404.

Панели используют вход `/shirin/api/auth/telegram/{role}`, где `role` — `user`, `admin` или `superadmin`. Подпись Telegram initData проверяется по token соответствующего бота. Запуск admin bot не выдаёт права: backend проверяет `CAN_EDIT_MENU`/`CAN_LOOK_ORDERS`, а для суперадминистратора — `SHIRIN_SUPERADMIN_ALLOWED_IDS`. Refresh/logout и cookies разделены по назначению панели. CORS задаётся явно; refresh/logout проверяют Origin. Имена браузерного хранилища Shirin отделены от Market.

## Существующая ВМ с Market/KULCHA

Все команды выполняются **на сервере в папке Shirin**, например `~/shirin`. Уже настроенную `.env` нужно дополнить, сохранив пароль существующей БД, access secret, домены, proxy, рабочую группу и Object Storage. При первом запуске:

```bash
cp .env.example .env
chmod 600 .env
nano .env
```

Основные поля:

| Поле | Значение |
| --- | --- |
| `SHIRIN_USER_BOT_TOKEN` | Token пользовательского бота Shirin |
| `SHIRIN_ADMIN_BOT_TOKEN` | Token административного бота Shirin |
| `SHIRIN_SUPERADMIN_BOT_TOKEN` | Token бота суперадминистратора Shirin |
| `SHIRIN_SUPERADMIN_ALLOWED_IDS` | Разрешённые Telegram ID |
| `SHIRIN_POSTGRES_PASSWORD` | Пароль БД Shirin; для существующей БД сохранить прежний |
| `SHIRIN_DATABASE_URL` | `postgresql+asyncpg://shirin:ТОТ_ЖЕ_ПАРОЛЬ@postgres:5432/shirin` |
| `SHIRIN_AUTH_ACCESS_SECRET` | Отдельный случайный secret, минимум 32 символа |
| `SHIRIN_MINI_APP_URL` | `https://market.wekulcha.ru/shirin/` |
| `SHIRIN_ADMIN_APP_URL` | `https://adminmarket.wekulcha.online/shirin/` |
| `SHIRIN_SUPERADMIN_APP_URL` | `https://adminmarket.wekulcha.online/shirin/superadmin/` |
| `SHIRIN_CORS_ALLOWED_ORIGINS` | `https://market.wekulcha.ru,https://adminmarket.wekulcha.online` |
| `SHIRIN_TELEGRAM_PROXY_URL` | Рабочий HTTP proxy для Telegram, если нужен на этой ВМ |
| `SHIRIN_WORK_GROUP_ID` | Рабочая группа; `0` сохраняет уведомления в очереди |
| `SHIRIN_SHARED_GATEWAY` | `true` для существующего общего gateway |
| `SHIRIN_SHARED_GATEWAY_CONTAINER` | Имя действующего gateway для подключения к сети Shirin; пусто для ручного подключения |

Пароль в connection URL должен быть URL-encoded, если содержит специальные символы. Для новой БД можно использовать `openssl rand -hex 32`; access secret генерируется отдельной командой. Замена значения `.env` не меняет пароль уже инициализированного PostgreSQL.

Запуск, обновление и остановка из корня Shirin:

```bash
./up.sh
docker compose ps -a
docker compose logs --tail=80 backend worker user_bot admin_bot superadmin_bot

# При следующем обновлении кода:
git pull --ff-only
./up.sh

# Остановка Shirin с сохранением volumes:
./down.sh
```

Корневые `up.sh`/`down.sh` вызывают одноимённые скрипты в `deploy/`, как в Market/KULCHA. `up.sh` проверяет конфигурацию, ждёт PostgreSQL и применяет миграции перед стартом рабочих сервисов; предыдущий одиночный контейнер `bot` удаляется. Миграции выполняются только в БД Shirin; production не засеивается demo-скриптом. `down.sh` сохраняет БД и media volumes. Заранее настройте backup PostgreSQL и фотографий вне этой ВМ.

По умолчанию запуск использует общий gateway. `./up.sh --shared` выбирает этот режим явно; `./up.sh --cloud` — отдельный публичный Caddy. Параметр команды имеет приоритет над `SHIRIN_SHARED_GATEWAY` в окружении/`.env`. Для скриптов нужен Docker Compose plugin 2.17+ с поддержкой `--wait`.

## Общий Caddy

Базовый Compose Shirin не занимает публичные порты 80/443. Он создаёт сеть `shirin_gateway`, имя которой задаётся `SHIRIN_GATEWAY_NETWORK`. Контейнеру действующего Caddy нужен доступ к этой сети. Узнать его имя:

```bash
docker ps --format '{{.Names}}\t{{.Ports}}'
```

Подключить выбранный gateway к сети Shirin можно после запуска приложения:

```bash
docker network connect shirin_gateway ИМЯ_КОНТЕЙНЕРА_CADDY
```

Имя сети заменить фактическим, если оно переопределено в `.env`. Закрепите подключение в Compose существующего gateway как внешнюю сеть, чтобы оно сохранялось после пересоздания контейнера.

Если указать `SHIRIN_SHARED_GATEWAY_CONTAINER`, `up.sh` подключит этот уже работающий контейнер к сети Shirin; повторный запуск не добавляет дубликат. Пустое значение не меняет сети соседних контейнеров. Скрипт не переписывает действующий Caddyfile.

В `deploy/Caddyfile.routes.example` подготовлены два блока доменов с маршрутами Shirin и корневым proxy в соответствующую панель Market. Замените ими **только существующие блоки** `market.wekulcha.ru` и `adminmarket.wekulcha.online`. Остальные домены, глобальные настройки и дополнительные маршруты действующего файла сохраните. Если в этих двух блоках уже есть собственные дополнительные правила, перенесите `handle /shirin…` и сохраните их вместе с корневым fallback `handle`. Не добавляйте вторые блоки с теми же доменами и не заменяйте весь Caddyfile этим примером.

На текущей ВМ публичные 80/443 занимает `kulcha-gateway`; `kulcha-market-gateway` на 18080/18443 не обслуживает обычные HTTPS-адреса. В `.env` Shirin задайте `SHIRIN_SHARED_GATEWAY_CONTAINER=kulcha-gateway`, чтобы `up.sh` восстанавливал подключение при следующих запусках. Для уже запущенных контейнеров достаточно `docker network connect shirin_gateway kulcha-gateway` (если сеть уже подключена, повторять команду не нужно).

Общий gateway должен обращаться к контейнерам по полным именам. В оставшихся блоках Kulcha используйте `kulcha-backend:8000`, `kulcha-user-panel:80`, `kulcha-admin-panel:80`, `kulcha-superadmin-panel:80` вместо `backend`, `user_panel`, `admin_panel`, `superadmin_panel`: такие Compose service aliases повторяются в сетях разных проектов.

Найдите действующий файл и посмотрите его до изменения:

```bash
docker inspect kulcha-gateway --format '{{range .Mounts}}{{if eq .Destination "/etc/caddy/Caddyfile"}}{{.Source}}{{end}}{{end}}'
docker exec kulcha-gateway cat /etc/caddy/Caddyfile
```

Сделайте резервную копию найденного файла и редактируйте его на хосте. Для file bind mount сохраняйте изменение в тот же файл, чтобы контейнер видел новое содержимое. На текущей ВМ подтверждён путь `/opt/kulcha/app/deploy/Caddyfile`.

Для полного Caddyfile, предоставленного 5 октября 2026, готова замена `deploy/Caddyfile.kulcha-shared.example`. Она сохраняет четыре домена Kulcha и четыре домена Market, добавляет три панели/API Shirin, заменяет неоднозначные upstream aliases Kulcha на полные имена контейнеров. Ограничение upload 9 MB действует только под `/shirin/*`. Пример из двух блоков `Caddyfile.routes.example` предназначен для ручного объединения, полный файл — для этой конкретной конфигурации ВМ.

Если действующий файл по-прежнему совпадает с предоставленным, примените полный файл из актуального checkout Shirin. Сначала проверяется временная копия в контейнере:

```bash
cd ~/shirin
docker cp deploy/Caddyfile.kulcha-shared.example kulcha-gateway:/tmp/Caddyfile.shirin
docker exec kulcha-gateway caddy validate --config /tmp/Caddyfile.shirin --adapter caddyfile
```

После `Valid configuration` сохраните backup и запишите содержимое в существующий bind-mounted файл, затем reload:

```bash
sudo cp -p /opt/kulcha/app/deploy/Caddyfile "/opt/kulcha/app/deploy/Caddyfile.bak.$(date +%Y%m%d-%H%M%S)"
sudo tee /opt/kulcha/app/deploy/Caddyfile < deploy/Caddyfile.kulcha-shared.example > /dev/null
docker exec kulcha-gateway caddy reload --config /etc/caddy/Caddyfile --adapter caddyfile
```

После reload подключите `kulcha-gateway` к `shirin_gateway`, если он ещё не подключён. Неоднозначные upstream заменяются до добавления новой сети. Ошибка `endpoint ... already exists` означает, что контейнер уже находится в сети; другие ошибки подключения нужно устранить. После подключения выполните проверки health ниже.

До reload проверьте объединённый файл:

```bash
docker exec kulcha-gateway caddy validate --config /etc/caddy/Caddyfile --adapter caddyfile
# Выполнить только после успешной проверки:
docker exec kulcha-gateway caddy reload --config /etc/caddy/Caddyfile --adapter caddyfile
```

DNS для этого сценария менять не нужно. Общий gateway маршрутизирует HTTP; данные, сессии и права принадлежат Shirin, связь с backend Market удалена.

Проверка опубликованного приложения:

```bash
curl -i https://market.wekulcha.ru/shirin/api/health
curl -i https://adminmarket.wekulcha.online/shirin/api/health
```

Оба адреса должны возвращать JSON `{"status":"ok","project":"shirin"}`. HTML с `<title>Kulcha Market</title>` вместо JSON означает, что запрос попал в корневую панель Market: маршруты Shirin ещё не применены к публичному gateway. React-сообщение `Unexpected Application Error! 404 Not Found` при открытии `/shirin/` в таком случае выдаёт роутер Market. Ошибка 502 после добавления маршрутов означает недоступность upstream; проверьте подключение `kulcha-gateway` к `shirin_gateway` и состояние backend/панелей.

После правильного ответа health откройте `/shirin/` и `/shirin/superadmin/` на нужных доменах: HTML должен содержать название «Ширин», ссылки на assets — префикс соответствующей панели. Затем закройте старое окно Mini App, отправьте боту `/start` и откройте новую кнопку.

## Telegram и хранилище

В личных диалогах каждого из трёх ботов `/start` открывает свою панель. User bot — каталог, admin bot — административную панель для разрешённых сотрудников, superadmin bot — суперадминку для allowlist. Настройка polling/webhook, рабочей группы, proxy и проверка входа описаны в [telegram.md](telegram.md).

Worker уведомлений отправляет заказы через admin bot. Его нужно добавить в рабочую группу и предоставить право отправки сообщений/фото. При незаданной группе уведомления сохраняются в outbox и ждут настройки; изменение режима polling/webhook оператор выполняет отдельно.

Фото товаров сохраняются в настроенное Object Storage, если заполнены bucket, keys и public URL; при пустых S3-полях используется media volume. Фото магазинов выдаются с проверкой доступа из закрытого хранилища. Настроенные значения не нужно очищать ради обновления ботов.

## Отдельная новая ВМ

Этот вариант нужен только при намеренном размещении Shirin на отдельной ВМ. `deploy/docker-compose.cloud.yml` добавляет публичный Caddy; для него нужны свои домены/IP и свободные 80/443. Такой gateway не запускают вторым на сервере с действующим публичным Caddy. Поля консоли, HOST, `.env` и команды — в [yandex-cloud.md](yandex-cloud.md).

## Проверка production-сборок локальным Caddy

```bash
make build
# Backend demo должен работать на 8083:
SHIRIN_PROJECT_ROOT="$PWD" caddy run --config deploy/Caddyfile.local --adapter caddyfile
.venv/bin/python scripts/demo.py --links-only --built
cd user_panel
SHIRIN_BUILT_PREVIEW=1 npx playwright test
```

Порты `8093`/`8094`/`8095` обслуживают готовые сборки Mini App/сотрудников/суперадминки. Суперадминка дополнительно доступна через `8094/shirin/superadmin/`. Эти команды относятся к синтетическому demo-окружению; успешная локальная проверка не означает размещение на сервере. Актуальные выполненные проверки находятся в [test-results.md](test-results.md).
