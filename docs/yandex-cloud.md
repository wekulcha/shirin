# Яндекс Облако: отдельная ВМ для Shirin

Подготовлены Compose с публичным Caddy и шаблон production `.env`. Инструкция рассчитана на новую ВМ Ubuntu 24.04 x86_64. Стартовые 2 vCPU / 4 ГБ RAM — рекомендация для небольшой нагрузки; нагрузочное тестирование не выполнялось. Платные ресурсы и DNS этой локальной работой не создавались.

## 1. Виртуальная машина

В [консоли Яндекс Облака](https://console.yandex.cloud/) выбрать облако и каталог, например создать каталог `shirin`. Нужен активный платёжный аккаунт. Открыть Compute Cloud → Виртуальные машины → Создать виртуальную машину. [Официальная инструкция](https://yandex.cloud/ru/docs/compute/operations/vm-create/create-linux-vm).

| Поле | Рекомендуемое значение для первого запуска |
| --- | --- |
| Имя | `shirin-prod` |
| Образ | Ubuntu 24.04 LTS, x86_64 |
| Зона | Например `ru-central1-a` |
| Диск | SSD, 40 ГБ |
| Вычислительные ресурсы | 2 vCPU, доля 100%, RAM 4 ГБ |
| Прерываемая | Выключено |
| Сеть | Создать `shirin-network` или выбрать подходящую |
| Подсеть | В сети и зоне этой ВМ |
| Публичный IP | Автоматически; затем сделать статическим |
| Группа безопасности | `shirin-web`, правила ниже |
| Доступ | SSH-ключ |
| Логин | `ubuntu` |
| SSH-ключ | Открытый ключ с Mac, файл `.pub` |
| Сервисный аккаунт | Для этого запуска можно оставить пустым |

Для отдельного ключа ВМ выполнить на Mac, выбрав другое имя файла, если такой ключ уже существует:

```bash
ssh-keygen -t ed25519 -f ~/.ssh/shirin_yc -C "shirin-yc"
cat ~/.ssh/shirin_yc.pub
```

В поле ключа консоли вставляется только строка из `.pub`. После создания ВМ открыть Virtual Private Cloud → Публичные IP-адреса → адрес ВМ → Сделать статическим. [Инструкция по статическому IP](https://yandex.cloud/ru/docs/vpc/operations/set-static-ip). Стоимость ВМ и IP проверять в консоли перед созданием.

## 2. Группа безопасности

В Virtual Private Cloud → Группы безопасности создать `shirin-web` в сети ВМ и назначить её сетевому интерфейсу ВМ. В правилах выбрать источник/назначение «Диапазон адресов». [Инструкция по полям правил](https://yandex.cloud/ru/docs/vpc/operations/security-group-create).

| Направление | Протокол | Порты | IPv4 CIDR |
| --- | --- | --- | --- |
| Входящий | TCP | 22 | Твой текущий публичный IPv4 с `/32` |
| Входящий | TCP | 80 | `0.0.0.0/0` |
| Входящий | TCP | 443 | `0.0.0.0/0` |
| Исходящий | Любой | Все | `0.0.0.0/0` |

При смене домашнего/VPN IP обновить правило SSH. PostgreSQL и backend остаются во внутренних контейнерных сетях.

## 3. Два домена

Примеры ниже используют новые поддомены `shirin.wekulcha.ru` и `adminshirin.wekulcha.ru`. Эти имена здесь не зарегистрированы и не настроены. Можно выбрать любые два разных имени на домене, которым вы управляете.

У действующего DNS-провайдера домена добавить:

| Имя в зоне `wekulcha.ru` | Тип | Значение | TTL |
| --- | --- | --- | --- |
| `shirin` | A | Статический публичный IPv4 новой ВМ | 300 |
| `adminshirin` | A | Тот же IPv4 | 300 |

Если зона уже обслуживается Cloud DNS, записи создаются там: [инструкция](https://yandex.cloud/ru/docs/dns/operations/resource-record-create). Новая зона Cloud DNS сама по себе не меняет делегирование домена. Вносить записи нужно у его текущего DNS-провайдера. Существующие `market` и `adminmarket` обслуживают Market и сохраняются.

## 4. Код и Docker на сервере

На Mac отправить проект:

```bash
cd /Users/amonulloh/Downloads/klch_project/shirin
git push origin main
ssh -i ~/.ssh/shirin_yc ubuntu@VM_IP
```

`VM_IP` заменить фактическим IP ВМ. Дальнейшие команды выполнять в SSH-сессии **на сервере**.

Установить Docker Engine и Compose plugin по [официальной инструкции Ubuntu](https://docs.docker.com/engine/install/ubuntu/), раздел Install using the apt repository. Затем проверить `sudo docker compose version`. Node.js и Python на ВМ отдельно не устанавливаются: они находятся в контейнерах. Для Git нужны `git` и `openssh-client`, для генерации secrets — `openssl`.

Приватный репозиторий удобно читать отдельным GitHub deploy key. На ВМ:

```bash
ssh-keygen -t ed25519 -f ~/.ssh/shirin_github -C "shirin-prod-deploy"
cat ~/.ssh/shirin_github.pub
```

В GitHub: `wekulcha/shirin` → Settings → Deploy keys → Add deploy key. Title: `shirin-prod`; Key: содержимое `.pub`; Allow write access оставить выключенным. Если ключ защищён passphrase, добавьте его в SSH agent для текущей сессии. [Deploy keys GitHub](https://docs.github.com/en/authentication/connecting-to-github-with-ssh/managing-deploy-keys).

На ВМ:

```bash
mkdir -p ~/apps
cd ~/apps
GIT_SSH_COMMAND='ssh -i ~/.ssh/shirin_github -o IdentitiesOnly=yes' git clone git@github.com:wekulcha/shirin.git shirin
cd shirin
git config core.sshCommand 'ssh -i ~/.ssh/shirin_github -o IdentitiesOnly=yes'
```

## 5. Рабочий `.env`

Рабочий файл находится **в корне Shirin**, рядом с `docker-compose.yml`: `~/apps/shirin/.env`. Шаблон `deploy/yandex-cloud.env.example` включает HOST-переменные публичного gateway. Обычный `.env.example` подходит для базового Compose с отдельно настроенным gateway.

На сервере, из `~/apps/shirin`:

```bash
cp deploy/yandex-cloud.env.example .env
chmod 600 .env
openssl rand -hex 32
openssl rand -hex 32
nano .env
```

Если рабочая `.env` уже существует, сначала сохранить её отдельную резервную копию, затем редактировать выбранный файл. Команда `cp` заменяет существующий файл. Локальная `.env` на Mac настроена для demo SQLite; её на сервер не переносить.

Первое случайное значение использовать как пароль БД, второе — как отдельный access secret. В nano сохранить Ctrl+O, Enter; выйти Ctrl+X.

| Переменная | Что вписать |
| --- | --- |
| `SHIRIN_PUBLIC_HOST` | `shirin.wekulcha.ru`, либо свой домен, без схемы и пути |
| `SHIRIN_ADMIN_HOST` | `adminshirin.wekulcha.ru`, либо свой второй домен |
| `SHIRIN_POSTGRES_PASSWORD` | Первое случайное значение |
| `SHIRIN_DATABASE_URL` | `postgresql+asyncpg://shirin:ТОТ_ЖЕ_ПАРОЛЬ@postgres:5432/shirin` |
| `SHIRIN_AUTH_ACCESS_SECRET` | Второе случайное значение |
| `SHIRIN_USER_BOT_TOKEN` | Token отдельного бота Shirin из BotFather |
| `SHIRIN_BOT_USERNAME` | Имя этого бота без `@` |
| `SHIRIN_SUPERADMIN_ALLOWED_IDS` | Твой числовой Telegram ID; несколько — через запятую |
| `SHIRIN_MINI_APP_URL` | `https://shirin.wekulcha.ru/shirin/` |
| `SHIRIN_ADMIN_APP_URL` | `https://adminshirin.wekulcha.ru/shirin/` |
| `SHIRIN_SUPERADMIN_APP_URL` | `https://adminshirin.wekulcha.ru/shirin/superadmin/` |
| `SHIRIN_CORS_ALLOWED_ORIGINS` | `https://shirin.wekulcha.ru,https://adminshirin.wekulcha.ru` |
| `SHIRIN_WORK_GROUP_ID` | `0` для запуска без групповых уведомлений; затем ID выбранной группы |
| `SHIRIN_WORK_GROUP_TOPIC_ID` | `0`, если отдельная forum-тема не используется |
| `SHIRIN_BOT_MODE` | Оставить `polling` для нового бота |
| `SHIRIN_WEBHOOK_SECRET` | В polling пусто |
| `SHIRIN_AUTH_COOKIE_DOMAIN` | Пусто |
| `SHIRIN_AUTH_COOKIE_SECURE` | `true` |
| Object Storage bucket/keys/public URL | Можно оставить пустыми: фото хранятся в Docker volume |
| Остальные значения шаблона | Оставить как есть |

При замене доменов одновременно обновить оба HOST, три URL и CORS. В CORS только origins без пути. Hex-пароль не требует URL-encoding. Значения token/password/access secret остаются на сервере; `.env` исключена из Git.

Бот создаётся отдельно через BotFather `/newbot`; Telegram ID суперадминистратора — число, а не username. Если ID неизвестен, до запуска bot-контейнера отправьте `/start` своему новому боту и получите `message.from.id` через его Bot API `getUpdates`. Для нового бота без webhook можно прочитать только ID таким скриптом на сервере после заполнения token и secrets:

```bash
sudo docker compose -f docker-compose.yml -f deploy/docker-compose.cloud.yml build bot
sudo docker compose -f docker-compose.yml -f deploy/docker-compose.cloud.yml run --rm -T --no-deps bot python - <<'PY'
import asyncio
from aiogram import Bot
from app.config import get_settings

async def main():
    async with Bot(get_settings().user_bot_token) as bot:
        for update in await bot.get_updates():
            message = update.message
            if message and message.chat.type == 'private' and message.from_user:
                print('Telegram ID:', message.from_user.id)

asyncio.run(main())
PY
```

Если вывода нет, отправить боту новое сообщение и повторить. Вписать свой ID в `.env` перед запуском. Настройка Telegram — [telegram.md](telegram.md).

## 6. Запуск и проверка

На сервере из `~/apps/shirin`:

```bash
sudo docker compose -f docker-compose.yml -f deploy/docker-compose.cloud.yml config -q
sudo docker compose -f docker-compose.yml -f deploy/docker-compose.cloud.yml up -d --build
sudo docker compose -f docker-compose.yml -f deploy/docker-compose.cloud.yml ps -a
sudo docker compose -f docker-compose.yml -f deploy/docker-compose.cloud.yml logs --tail=80 backend bot worker gateway
```

`migrate` должен завершиться с кодом 0; затем стартует backend. Caddy получит HTTPS-сертификаты, когда оба имени разрешаются в IP ВМ и доступны порты 80/443; сертификаты сохраняются в `caddy_data`. [Автоматический HTTPS Caddy](https://caddyserver.com/docs/automatic-https).

Проверить `https://shirin.wekulcha.ru/shirin/api/health`: ожидается `{"status":"ok","project":"shirin"}`. Панели доступны по URL из `.env`; без Telegram-сессии показывают вход. База создаётся пустой, demo-товары на сервер не добавляются.

В BotFather `/mybots` выбрать Shirin → Bot Settings → Menu Button, задать `SHIRIN_MINI_APP_URL`. В личном диалоге с ботом отправить `/start`: пользователь из allowlist увидит кнопку «Суперадмин Shirin». Открыть её и добавить реальные товары/Excel.

При группе `0` уведомления ждут в outbox. Для доставки добавить бота в выбранную группу, заполнить её ID и при необходимости topic ID в `.env`, повторить `up -d`. Старый бот с webhook требует отдельного согласования режима: приложение webhook не удаляет.

## 7. Обновления и данные

После commit/push на Mac выполнить на сервере:

```bash
cd ~/apps/shirin
git pull --ff-only
sudo docker compose -f docker-compose.yml -f deploy/docker-compose.cloud.yml up -d --build
```

База и фото сохраняются в volumes. Команда `down -v` удаляет эти данные; для обновлений используйте `up -d --build`. До рабочих заказов настройте backup PostgreSQL и media volume вне ВМ.

Compose/Caddy-шаблоны проверены локально; Docker daemon здесь выключен, контейнеры на облачной ВМ ещё не запускались. При размещении рядом с уже работающим Market нужен его существующий gateway и [инструкция объединения маршрутов](deployment.md); файл `docker-compose.cloud.yml` добавляет второй gateway на 80/443 и предназначен для отдельной ВМ.
