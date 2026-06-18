# Развёртывание на Ubuntu (test / prod)

Инструкция для сервера: клон репозитория, `.env`, сессия Telegram, запуск через **venv** или **Docker**.

> **Важно:** prod и test используют **одну** сессию (`neuro_session.session`). Не запускайте оба бота одновременно — ни `neuro-test` + `neuro-prod`, ни сервер + ПК с той же сессией.

**Содержание**

1. [Что понадобится](#что-понадобится)
2. [Подготовка сервера](#1-подготовка-сервера)
3. [Клонирование](#2-клонирование-репозитория)
4. [venv в папке проекта](#3-venv-в-папке-проекта)
5. [Секреты и вход в Telegram](#4-секреты-и-вход-в-telegram)
6. [Запуск через venv](#5-запуск-через-venv)
7. [Запуск через Docker](#6-запуск-через-docker)
8. [Автозапуск systemd (без Docker)](#7-автозапуск-systemd-без-docker)
9. [Обновление](#8-обновление-после-git-pull)
10. [Частые проблемы](#9-частые-проблемы)
11. [Чеклист](#10-чеклист)

---

## Что понадобится

| Что | Где лежит | В git? |
|-----|-----------|--------|
| Код | репозиторий | да |
| `.env` | корень проекта | **нет** — создаёте на сервере или копируете с ПК |
| `neuro_session.session` | корень проекта | **нет** — создаётся при первом входе бота **или** копируется с ПК |
| `venv/` | корень проекта | **нет** — создаёте локально (`python -m venv venv`) |
| `prod/channels.json` | каналы prod | да |
| `test/channels.json` | каналы test | да |
| `prod/neuro_state.json` | состояние prod | **нет** — создаётся сам |
| `test/neuro_state_test.json` | состояние test | **нет** — создаётся сам |

> **Про сессию:** `neuro_session.session` — это **не** папка `data`/`tdata` из Telegram Desktop. Это локальная база Telethon: бот создаёт её при первом запуске, когда вы вводите код из приложения Telegram.

В `.env`:

```env
API_ID=...
API_HASH=...
PHONE=+7...
OPENROUTER_API_KEY=sk-or-v1-...
```

- `API_ID` / `API_HASH`: https://my.telegram.org/apps  
- OpenRouter: https://openrouter.ai/keys

---

## 1. Подготовка сервера

### Для venv

```bash
sudo apt update
sudo apt install -y git python3 python3-venv python3-pip
python3 --version   # нужен Python 3.10+
```

### Для Docker (можно вместо python3-venv)

```bash
sudo apt update
sudo apt install -y git ca-certificates curl
sudo install -m 0755 -d /etc/apt/keyrings
sudo curl -fsSL https://download.docker.com/linux/ubuntu/gpg -o /etc/apt/keyrings/docker.asc
sudo chmod a+r /etc/apt/keyrings/docker.asc

echo "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.asc] https://download.docker.com/linux/ubuntu \
  $(. /etc/os-release && echo "${VERSION_CODENAME}") stable" | \
  sudo tee /etc/apt/sources.list.d/docker.list > /dev/null

sudo apt update
sudo apt install -y docker-ce docker-ce-cli containerd.io docker-compose-plugin
sudo usermod -aG docker $USER
# перелогиньтесь, чтобы группа docker применилась
```

Отдельный пользователь (рекомендуется):

```bash
sudo adduser --disabled-password neurobot
sudo usermod -aG docker neurobot   # если используете Docker
sudo su - neurobot
```

---

## 2. Клонирование репозитория

```bash
cd ~
git clone https://github.com/Cha11en9er/tg_neirocommenting.git
cd tg_neirocommenting
```

Обновление:

```bash
cd ~/tg_neirocommenting
git pull
```

---

## 3. venv в папке проекта

Виртуальное окружение создаётся **внутри репозитория** — папка `venv/` в корне (не в системный Python):

```bash
cd ~/tg_neirocommenting
python3 -m venv venv
```

Активация (каждый новый терминал):

```bash
cd ~/tg_neirocommenting
source venv/bin/activate
```

В начале строки появится `(venv)`. Установка зависимостей:

```bash
pip install --upgrade pip
pip install -r requirements.txt
```

Деактивация: `deactivate`.

Папка `venv/` в `.gitignore` — в git не попадает. На сервере она живёт только локально рядом с кодом:

```
~/tg_neirocommenting/
├── venv/              ← виртуальное окружение
├── .env
├── neuro_session.session
├── prod/
└── test/
```

> **Docker:** если запускаете только через Docker, `venv/` на хосте **не обязателен** — зависимости ставятся внутри образа. Но venv удобен для первого интерактивного входа без Docker.

---

## 4. Секреты и вход в Telegram

Создайте `.env` в корне (скопируйте с ПК или `cp .env.example .env` и заполните):

```bash
cd ~/tg_neirocommenting
nano .env
chmod 600 .env
```

### Первый вход (код с телефона)

Запустите бота **вручную** в терминале (venv или Docker — см. ниже). Telethon попросит код из Telegram → введите в терминал → появится `neuro_session.session` в корне проекта.

Папку `data` / `tdata` с Telegram Desktop **переносить не нужно**.

### Уже входили на ПК

Скопируйте готовую сессию (бот на ПК должен быть **остановлен**):

```powershell
scp .env neurobot@YOUR_SERVER_IP:~/tg_neirocommenting/
scp neuro_session.session neurobot@YOUR_SERVER_IP:~/tg_neirocommenting/
```

`neuro_session.session-journal` переносить **не обязательно**.

---

## 5. Запуск через venv

### Тестовый бот

Интервалы 5 мин, разбор LLM — в комментарий под постом:

```bash
cd ~/tg_neirocommenting
source venv/bin/activate
python test/neuro_commenter_test.py
```

### Боевой бот

Заморозки, фильтры, мониторинг каждые 30 мин:

```bash
cd ~/tg_neirocommenting
source venv/bin/activate
python prod/neuro_commenter.py
```

Остановка: `Ctrl+C`. Запускайте **только один** из двух.

### Каналы и админ

- Каналы: `test/channels.json` или `prod/channels.json`
- Добавление в личку боту: `https://t.me/username - . -GROUP_ID`
- Админ-команды — только от ID из `ADMIN_USER_IDS` в соответствующем `neuro_config.py`

---

## 6. Запуск через Docker

В репозитории есть `Dockerfile` и `docker-compose.yml` с двумя сервисами:

| Сервис | Команда внутри контейнера |
|--------|---------------------------|
| `neuro-test` | `python test/neuro_commenter_test.py` |
| `neuro-prod` | `python prod/neuro_commenter.py` |

Код и runtime-файлы (`.env`, session, state) монтируются с хоста (`volumes: .:/app`), поэтому сессия и состояние сохраняются между перезапусками.

### Сборка

```bash
cd ~/tg_neirocommenting
docker compose build
```

### Первый вход (интерактивно, с кодом из Telegram)

**Тест:**

```bash
docker compose run --rm -it neuro-test
```

**Prod:**

```bash
docker compose run --rm -it neuro-prod
```

Введите код → убедитесь, что `neuro_session.session` появился в корне проекта на хосте → `Ctrl+C`.

### Фоновый запуск

**Только тест:**

```bash
docker compose up -d neuro-test
```

**Только prod:**

```bash
docker compose up -d neuro-prod
```

Логи:

```bash
docker compose logs -f neuro-test
docker compose logs -f neuro-prod
```

Остановка:

```bash
docker compose stop neuro-test
docker compose stop neuro-prod
```

Перезапуск после изменений кода:

```bash
docker compose build
docker compose up -d neuro-test    # или neuro-prod
```

### Docker: что где лежит

```
~/tg_neirocommenting/          ← монтируется в /app внутри контейнера
├── .env                       ← env_file для compose
├── neuro_session.session      ← общая сессия
├── prod/neuro_state.json      ← состояние prod (создаётся сам)
├── test/neuro_state_test.json ← состояние test (создаётся сам)
├── docker-compose.yml
└── Dockerfile
```

Зависимости Python — **внутри образа**. Папка `venv/` на хосте для Docker не нужна.

---

## 7. Автозапуск systemd (без Docker)

Если не используете Docker — unit для **теста**:

```bash
sudo nano /etc/systemd/system/neuro-test.service
```

```ini
[Unit]
Description=Telegram neuro commenting test bot
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
User=neurobot
WorkingDirectory=/home/neurobot/tg_neirocommenting
Environment=PYTHONUNBUFFERED=1
ExecStart=/home/neurobot/tg_neirocommenting/venv/bin/python test/neuro_commenter_test.py
Restart=on-failure
RestartSec=30

[Install]
WantedBy=multi-user.target
```

Для **prod** — файл `neuro-prod.service`, в `ExecStart` замените на:

```
ExecStart=/home/neurobot/tg_neirocommenting/venv/bin/python prod/neuro_commenter.py
```

Включение:

```bash
sudo systemctl daemon-reload
sudo systemctl enable neuro-test    # или neuro-prod
sudo systemctl start neuro-test
sudo journalctl -u neuro-test -f
```

### systemd + Docker (альтернатива)

Контейнер с `restart: unless-stopped` в `docker-compose.yml` уже перезапускается сам. Дополнительный systemd не обязателен. Если нужен автозапуск при загрузке сервера:

```bash
sudo nano /etc/systemd/system/neuro-docker-test.service
```

```ini
[Unit]
Description=Neuro test bot (Docker)
After=docker.service
Requires=docker.service

[Service]
Type=oneshot
RemainAfterExit=yes
User=neurobot
WorkingDirectory=/home/neurobot/tg_neirocommenting
ExecStart=/usr/bin/docker compose up -d neuro-test
ExecStop=/usr/bin/docker compose stop neuro-test

[Install]
WantedBy=multi-user.target
```

---

## 8. Обновление после `git pull`

### venv

```bash
cd ~/tg_neirocommenting
git pull
source venv/bin/activate
pip install -r requirements.txt
sudo systemctl restart neuro-test    # или neuro-prod
```

### Docker

```bash
cd ~/tg_neirocommenting
git pull
docker compose build
docker compose up -d neuro-test      # или neuro-prod
```

`.env`, `neuro_session.session` и state-файлы git **не трогает**.

---

## 9. Частые проблемы

### `SessionRevokedError` / снова просит код

Сессия сброшена (вход с телефона, второй процесс с той же сессией). Остановите бота везде, войдите заново (`venv` или `docker compose run --rm -it`).

### Бот на ПК и на сервере одновременно

Одна сессия — один активный процесс.

### Docker: `env_file .env not found`

Создайте `.env` в корне проекта до `docker compose up`.

### `OPENROUTER_API_KEY` / ошибки LLM

Проверьте `.env`, баланс OpenRouter, интернет с сервера.

### Комментарии не появляются

- аккаунт в канале и группе обсуждений;
- комментарии у канала включены;
- канал не в заморозке (`статус каналов` в личку);
- логи: `journalctl -u neuro-test -f` или `docker compose logs -f neuro-test`.

---

## 10. Чеклист

- [ ] Репозиторий склонирован в `~/tg_neirocommenting`
- [ ] `.env` в корне, права `600`
- [ ] `neuro_session.session` создан (первый вход) или скопирован с ПК
- [ ] **venv:** `~/tg_neirocommenting/venv/` создан, `pip install -r requirements.txt` OK  
      **или Docker:** `docker compose build` OK
- [ ] Запущен **только один** бот: test **или** prod
- [ ] Бот **не** запущен на ПК с той же сессией
- [ ] Каналы в нужном `channels.json`
- [ ] Ваш ID в `ADMIN_USER_IDS`
- [ ] В логах нет повторяющихся ошибок API / Telegram

---

## Структура на сервере (итог)

```
/home/neurobot/tg_neirocommenting/
├── .env
├── neuro_session.session
├── venv/                         # только для запуска без Docker
├── Dockerfile
├── docker-compose.yml
├── prod/
│   ├── neuro_commenter.py
│   ├── channels.json
│   └── neuro_state.json
└── test/
    ├── neuro_commenter_test.py
    ├── channels.json
    └── neuro_state_test.json
```

| Способ | Тест | Prod |
|--------|------|------|
| venv | `python test/neuro_commenter_test.py` | `python prod/neuro_commenter.py` |
| Docker | `docker compose up -d neuro-test` | `docker compose up -d neuro-prod` |
