# tg_neirocommenting

Бот для автоматических комментариев под постами Telegram-каналов. Слушает новые посты, генерирует короткий ответ через LLM (OpenRouter) и публикует его в обсуждении канала от имени вашего аккаунта.

## Что нужно получить заранее

### 1. Telegram API (`API_ID`, `API_HASH`)

1. Войдите на [my.telegram.org](https://my.telegram.org) под аккаунтом, который будет комментировать.
2. Откройте **API development tools**.
3. Создайте приложение (название и short name — любые).
4. Скопируйте **App api_id** → `API_ID` и **App api_hash** → `API_HASH`.

### 2. Номер телефона (`PHONE`)

Номер того же Telegram-аккаунта в международном формате, например `+79991234567`.

При первом запуске Telethon запросит код из Telegram (и пароль 2FA, если включён). После авторизации создаётся файл сессии `neuro_session.session` — повторный ввод кода не нужен.

### 3. OpenRouter API key (`OPENROUTER_API_KEY`)

1. Зарегистрируйтесь на [openrouter.ai](https://openrouter.ai).
2. Пополните баланс (модель платная по токенам).
3. Создайте ключ: [openrouter.ai/keys](https://openrouter.ai/keys) → `OPENROUTER_API_KEY`.

Проверка ключа без Telegram:

```bash
python test_provider.py
```

### 4. Настройка каналов (в коде)

В `neuro_commenter.py` отредактируйте список `CHANNELS`:

```python
CHANNELS = [
    {"channel": "username_канала", "discussion_id": -1234567890},
]
```

| Поле | Описание |
|------|----------|
| `channel` | Username канала **без** `@` |
| `discussion_id` | ID группы обсуждений (для логов; отрицательное число) |

**Как узнать `discussion_id`:**

1. У канала должны быть включены **комментарии** (привязанная группа обсуждений).
2. Аккаунт бота должен быть **подписан на канал** и **участником** группы обсуждений.
3. Перешлите любое сообщение из группы обсуждений боту [@userinfobot](https://t.me/userinfobot) или [@getidsbot](https://t.me/getidsbot) — он покажет chat id (обычно вида `-100...`; в конфиге используйте то значение, которое уже работает у вас, либо id из логов при первом запуске).

Также в `neuro_commenter.py` можно менять:

- `MODEL` — модель на OpenRouter (по умолчанию `qwen/qwen3.6-flash`)
- `COOLDOWN` — минимальный интервал между комментариями в один канал
- `SYSTEM_PROMPT` — стиль комментариев

## Установка

Требуется **Python 3.10+**.

```bash
git clone <url-репозитория>
cd tg_neirocommenting

python -m venv .venv

# Windows
.venv\Scripts\activate

# Linux / macOS
source .venv/bin/activate

pip install -r requirements.txt
```

## Настройка `.env`

Скопируйте пример и заполните своими значениями:

```bash
# Windows
copy .env.example .env

# Linux / macOS
cp .env.example .env
```

Пример `.env`:

```env
API_ID=12345678
API_HASH=0123456789abcdef0123456789abcdef
PHONE=+79991234567
OPENROUTER_API_KEY=sk-or-v1-xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx
```

Файл `.env` не коммитится в git — храните ключи только локально.

## Запуск

```bash
python neuro_commenter.py
```

При первом запуске в консоли:

1. Введите код из Telegram.
2. При необходимости — пароль двухфакторной аутентификации.

Успешный старт выглядит так:

```
✅ Нейрокомментер запущен!
Модель: qwen/qwen3.6-flash
Заморозка на канал: 5 мин
Каналов: 2
  • @channel_name (chat_id ...) → беседа ... [готов]
```

Бот работает, пока открыт терминал. Состояние cooldown сохраняется в `comment_cooldowns.json`.

## Запуск в фоне (Linux, systemd)

Пример unit-файла `/etc/systemd/system/neuro-commenter.service`:

```ini
[Unit]
Description=Telegram neuro commenter
After=network.target

[Service]
Type=simple
User=your_user
WorkingDirectory=/path/to/tg_neirocommenting
Environment=PATH=/path/to/tg_neirocommenting/.venv/bin
ExecStart=/path/to/tg_neirocommenting/.venv/bin/python neuro_commenter.py
Restart=on-failure
RestartSec=30

[Install]
WantedBy=multi-user.target
```

```bash
sudo systemctl daemon-reload
sudo systemctl enable --now neuro-commenter
sudo journalctl -u neuro-commenter -f
```

На Windows можно запускать через Планировщик заданий или держать процесс в отдельном терминале.

## Структура проекта

| Файл | Назначение |
|------|------------|
| `neuro_commenter.py` | Основной бот |
| `test_provider.py` | Проверка OpenRouter без Telegram |
| `requirements.txt` | Зависимости Python |
| `.env` | Секреты (создаётся вручную) |
| `neuro_session.session` | Сессия Telegram (создаётся при первом входе) |
| `comment_cooldowns.json` | Время последних комментариев по каналам |

## Частые проблемы

| Симптом | Что проверить |
|---------|----------------|
| `API_ID` / `API_HASH` ошибка | Значения из my.telegram.org, без кавычек в `.env` |
| Не приходит код | Правильный `PHONE`, код в приложении Telegram, не SMS |
| `OPENROUTER_API_KEY не задан` | Файл `.env` в корне проекта, ключ без пробелов |
| Ошибка 429 от OpenRouter | Лимит запросов или нулевой баланс на openrouter.ai |
| Комментарий не отправляется | Аккаунт в группе обсуждений, комментарии включены у канала |
| Канал не в списке | Username в `CHANNELS` без `@`, аккаунт подписан на канал |

## Безопасность

- Не публикуйте `.env`, `*.session` и ключи API.
- Используйте отдельный Telegram-аккаунт, если боитесь ограничений за автоматизацию.
- Соблюдайте правила Telegram и OpenRouter.
