import asyncio
import json
import os
import random
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path

from dotenv import load_dotenv
from openai import APIStatusError, AsyncOpenAI, RateLimitError
from telethon import TelegramClient, events, utils

load_dotenv()

# ===================== НАСТРОЙКИ =====================
API_ID = int(os.getenv("API_ID"))
API_HASH = os.getenv("API_HASH")
PHONE = os.getenv("PHONE")

MODEL = "qwen/qwen3.6-flash"

# Заморозка: не чаще одного комментария на канал за этот интервал
COOLDOWN = timedelta(minutes=5)  # тест
# COOLDOWN = timedelta(days=3)   # прод

# Каналы: username без @ + id группы обсуждений (для справки в логах)
CHANNELS = [
    {"channel": "test_neirocoment", "discussion_id": -3994471732},
    {"channel": "neyrocommentimpopolnoy", "discussion_id": -3511597340},
]

STATE_FILE = Path(__file__).with_name("comment_cooldowns.json")

SYSTEM_PROMPT = """Ты — живой, остроумный парень 27-30 лет. 
Пишешь короткие естественные комментарии под посты.
Максимум 1-2 предложения. Иногда эмодзи. Будь человечным."""

client = TelegramClient("neuro_session", API_ID, API_HASH)
openai_client = AsyncOpenAI(
    base_url="https://openrouter.ai/api/v1",
    api_key=os.getenv("OPENROUTER_API_KEY"),
)


@dataclass
class ChannelConfig:
    channel: str
    discussion_id: int
    channel_id: int | None = None


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _format_timedelta(delta: timedelta) -> str:
    total = int(delta.total_seconds())
    if total < 3600:
        return f"{total // 60} мин"
    if total < 86400:
        return f"{total // 3600} ч"
    days = total // 86400
    hours = (total % 86400) // 3600
    if hours:
        return f"{days} д {hours} ч"
    return f"{days} д"


class CooldownStore:
    """Время последнего комментария по каждому каналу (переживает перезапуск)."""

    def __init__(self, path: Path) -> None:
        self.path = path
        self._data: dict[str, str] = {}
        self._load()

    def _load(self) -> None:
        if self.path.exists():
            try:
                self._data = json.loads(self.path.read_text(encoding="utf-8"))
            except (json.JSONDecodeError, OSError):
                self._data = {}

    def _save(self) -> None:
        self.path.write_text(
            json.dumps(self._data, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

    def can_comment(self, channel_key: str) -> tuple[bool, datetime | None]:
        raw = self._data.get(channel_key)
        if not raw:
            return True, None
        last = datetime.fromisoformat(raw)
        if last.tzinfo is None:
            last = last.replace(tzinfo=timezone.utc)
        next_allowed = last + COOLDOWN
        now = _utc_now()
        if now >= next_allowed:
            return True, None
        return False, next_allowed

    def mark_commented(self, channel_key: str) -> None:
        self._data[channel_key] = _utc_now().isoformat()
        self._save()


cooldowns = CooldownStore(STATE_FILE)
channel_by_id: dict[int, ChannelConfig] = {}


def _post_text(event: events.NewMessage.Event) -> str | None:
    text = (event.message.message or "").strip()
    if text:
        return text[:4000]
    if event.message.media:
        return "[пост с медиа]"
    return None


def _channel_key(cfg: ChannelConfig) -> str:
    return cfg.channel.lower()


async def send_channel_comment(
    channel: str, channel_post_id: int, comment: str
) -> None:
    last_error = None
    for attempt in range(5):
        try:
            await client.send_message(
                channel,
                comment,
                comment_to=channel_post_id,
                silent=True,
            )
            return
        except Exception as e:
            last_error = e
            if attempt < 4:
                await asyncio.sleep(2)
    raise last_error


async def generate_comment(post_text: str) -> str | None:
    last_error = None
    for attempt in range(1, 4):
        try:
            response = await openai_client.chat.completions.create(
                model=MODEL,
                messages=[
                    {"role": "system", "content": SYSTEM_PROMPT},
                    {
                        "role": "user",
                        "content": f"Пост:\n{post_text}\n\nНапиши короткий живой комментарий:",
                    },
                ],
                max_tokens=140,
                temperature=0.85,
            )
            comment = response.choices[0].message.content.strip()
            if comment.startswith('"') and comment.endswith('"'):
                comment = comment[1:-1].strip()
            return comment
        except (RateLimitError, APIStatusError) as e:
            last_error = e
            if getattr(e, "status_code", None) != 429 or attempt == 3:
                break
            wait = attempt * 3
            print(f"Лимит OpenRouter, повтор через {wait} с...")
            await asyncio.sleep(wait)
        except Exception as e:
            last_error = e
            break

    print(f"❌ Ошибка OpenRouter: {last_error}")
    return None


async def setup_channels() -> list:
    """Резолвим каналы и строим карту chat_id -> конфиг."""
    channel_by_id.clear()
    entities = []
    for raw in CHANNELS:
        cfg = ChannelConfig(
            channel=raw["channel"].lstrip("@"),
            discussion_id=raw["discussion_id"],
        )
        entity = await client.get_entity(cfg.channel)
        cfg.channel_id = utils.get_peer_id(entity)
        channel_by_id[cfg.channel_id] = cfg
        entities.append(entity)
    return entities


async def new_post_handler(event: events.NewMessage.Event) -> None:
    if event.message.edit_date:
        return

    cfg = channel_by_id.get(event.chat_id)
    if not cfg:
        return

    post_text = _post_text(event)
    if not post_text:
        print(f"⏭ @{cfg.channel}: пост без текста и медиа, пропуск")
        return

    key = _channel_key(cfg)
    allowed, next_at = cooldowns.can_comment(key)
    if not allowed:
        left = next_at - _utc_now()
        print(
            f"\n⏸ @{cfg.channel}: заморозка, осталось {_format_timedelta(left)} "
            f"(можно с {next_at.astimezone().strftime('%d.%m.%Y %H:%M')})"
        )
        return

    channel_post_id = event.message.id
    print(f"\n🔔 @{cfg.channel}: новый пост (ID: {channel_post_id})")

    comment = await generate_comment(post_text)
    if not comment:
        print("⏭ Пропускаем из-за ошибки API")
        return

    await asyncio.sleep(random.uniform(12, 32))

    try:
        await send_channel_comment(cfg.channel, channel_post_id, comment)
        cooldowns.mark_commented(key)
        print(
            f"✅ @{cfg.channel}: комментарий к посту {channel_post_id} "
            f"(беседа {cfg.discussion_id}): {comment[:70]}..."
        )
    except Exception as e:
        print(f"❌ @{cfg.channel}: ошибка отправки: {e}")


async def main() -> None:
    await client.start(phone=PHONE)
    entities = await setup_channels()
    client.add_event_handler(
        new_post_handler,
        events.NewMessage(chats=entities),
    )

    print("✅ Нейрокомментер запущен!")
    print(f"Модель: {MODEL}")
    print(f"Заморозка на канал: {_format_timedelta(COOLDOWN)}")
    print(f"Каналов: {len(entities)}")
    for cfg in channel_by_id.values():
        key = _channel_key(cfg)
        ok, next_at = cooldowns.can_comment(key)
        status = "готов" if ok else f"заморозка до {next_at.astimezone().strftime('%d.%m.%Y %H:%M')}"
        print(
            f"  • @{cfg.channel} (chat_id {cfg.channel_id}) "
            f"→ беседа {cfg.discussion_id} [{status}]"
        )

    await client.run_until_disconnected()


if __name__ == "__main__":
    asyncio.run(main())
