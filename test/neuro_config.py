"""Настройки тестового нейрокомментинга — короткие интервалы (5 мин)."""

import os
from datetime import timedelta, timezone
from pathlib import Path

from dotenv import load_dotenv

ROOT_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = ROOT_DIR.parent

load_dotenv(PROJECT_ROOT / ".env")

MODEL = "qwen/qwen3.6-flash"

CHANNELS_FILE = ROOT_DIR / "channels.json"

CHANNELS_FALLBACK: list[str] = [
    "test_neirocoment",
    "neyrocommentimpopolnoy",
]

GLOBAL_COOLDOWN = timedelta(minutes=5)
MONITORING_INTERVAL = timedelta(minutes=5)
POST_MIN_AGE = timedelta(minutes=5)
POST_ACTIVITY_WINDOW = timedelta(minutes=5)
MIN_COMMENTS_UNDER_POST = 3
POSTS_SCAN_LIMIT = 30
DEFAULT_FREEZE_MINUTES = 5

MIN_CHANNEL_SUBSCRIBERS = 0

SUITABLE_POST_TYPES = [
    "Разборы сделок — закрытые плюсовые или минусовые, с цифрами",
    "Обзоры BTC/ETH/альтов с техническим анализом",
    "Посты про ИИ и нейросети в трейдинге",
    "Обучающий контент: стратегии, риск-менеджмент, психология",
    "Проп-трейдинг: прохождение челленджей, условия фондирования",
    "Пассивный доход: стейкинг, DeFi, инвестиции в крипту",
    "Вебинары и эфиры — анонсы и записи",
]

UNSUITABLE_POST_TYPES = [
    "Рекламные посты и партнёрские акции со скидками",
    "Розыгрыши, конкурсы, голосования",
    "Новостные посты без аналитики (просто факт без мнения)",
    "Посты с закрытыми комментариями",
    "Посты без аналитики и без торгового/обучающего контекста",
]

COMMENT_STYLE_DO = [
    "Писать от первого лица, как живой трейдер",
    "Делиться личным опытом или конкретным наблюдением по теме",
    "Называть конкретные цифры, уровни, монеты",
    "Длина: 2–4 предложения — коротко и по делу",
    "Можно мягко не согласиться с автором — это вызывает дискуссию",
    "Использовать живую разговорную речь",
]

COMMENT_STYLE_DONT = [
    "Шаблонные фразы: «отличный пост», «согласен», «спасибо»",
    "Рекламировать канал напрямую — ссылка только в профиле",
    "Общие слова без конкретики",
    "Длинные «простыни» текста",
    "Агрессивный спор или обесценивание контента канала",
    "AI-маркеры: «таким образом», «при этом», «следует отметить»",
]

COMMENT_SEND_DELAY = (3, 8)

ADMIN_USER_IDS: list[int] = [
    508607571,
]

INITIAL_NOTIFICATION_SUBSCRIBERS: list[int] = [
    508607571,
]

MSK = timezone(timedelta(hours=3))
DAILY_REPORT_ENABLED = True
DAILY_REPORT_HOUR_MSK = 6
DAILY_REPORT_INTERVAL = timedelta(minutes=5)

STATE_FILE = ROOT_DIR / "neuro_state_test.json"
SESSION_PATH = str(PROJECT_ROOT / "neuro_session")

# Тест: весь разбор LLM уходит в комментарий под постом, без фильтра по числу комментариев.
VERBOSE_COMMENT_MODE = True
