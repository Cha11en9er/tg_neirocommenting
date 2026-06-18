# tg_neirocommenting

Бот для автоматических комментариев под постами Telegram-каналов. LLM (OpenRouter) + Telethon (user account).

## Структура

```
tg_neirocommenting/
├── .env                    # секреты (в корне, общие для prod и test)
├── neuro_session.session   # сессия Telegram (общая)
├── prod/                   # боевой бот
│   ├── neuro_commenter.py
│   ├── neuro_config.py
│   ├── channels.json
│   └── ...
└── test/                   # тесты (отдельная копия модулей)
    ├── neuro_commenter_test.py   # тестовый бот в Telegram
    ├── test_comment.py           # LLM без Telegram
    ├── test_provider.py          # проверка OpenRouter
    └── ...
```

## Установка

Python 3.10+, из корня репозитория:

```powershell
python -m venv venv
.\venv\Scripts\Activate.ps1
pip install -r requirements.txt
copy .env.example .env
```

Заполните `.env`:

```env
API_ID=...
API_HASH=...
PHONE=+7...
OPENROUTER_API_KEY=sk-or-v1-...
```

## Запуск

**Боевой бот** (заморозки, фильтры, мониторинг каждые 30 мин):

```powershell
python prod/neuro_commenter.py
```

**Тестовый бот** (только новые посты, без заморозок):

```powershell
python test/neuro_commenter_test.py
```

**LLM без Telegram:**

```powershell
python test/test_comment.py
python test/test_provider.py
```

## Каналы

Список каналов — `prod/channels.json` и `test/channels.json` (можно настроить отдельно).

Добавление через личку аккаунта-комментатора (admin id в `neuro_config.py`):

```
https://t.me/username - . -3511597340
```

## Настройки

| Файл | Назначение |
|------|------------|
| `prod/neuro_config.py` | интервалы, заморозка, промпты, админ |
| `prod/channels.json` | каналы и параметры по каждому |
| `prod/neuro_state.json` | cooldown и обработанные посты (боевой) |
| `test/neuro_state_test.json` | baseline новых постов (тест) |

## Безопасность

Не коммитьте `.env`, `*.session`, state-файлы.

## Деплой на сервер

Развёртывание на Ubuntu (venv в папке проекта, Docker для test/prod, systemd): [docs/deploy-test-ubuntu.md](docs/deploy-test-ubuntu.md).
