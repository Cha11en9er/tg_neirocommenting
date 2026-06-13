import asyncio
import json
import os
import random
import re
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

from openai import APIStatusError, AsyncOpenAI, RateLimitError
from telethon import TelegramClient, events, utils
from telethon.tl.functions.channels import GetFullChannelRequest
from telethon.tl.types import Message

import neuro_config as cfg
from channels_store import (
    ChannelEntry,
    add_channel_entry,
    load_store,
    parse_add_channel,
)
from neuro_admin import AdminCommands, AdminContext, PendingPostInfo, _estimate_ticks
from neuro_prompts import build_classify_system_prompt, build_comment_system_prompt

API_ID = int(os.getenv("API_ID"))
API_HASH = os.getenv("API_HASH")
PHONE = os.getenv("PHONE")

client = TelegramClient(cfg.SESSION_NAME, API_ID, API_HASH)
openai_client = AsyncOpenAI(
    base_url="https://openrouter.ai/api/v1",
    api_key=os.getenv("OPENROUTER_API_KEY"),
)

CLASSIFY_SYSTEM = build_classify_system_prompt()
COMMENT_SYSTEM = build_comment_system_prompt()


@dataclass
class RuntimeMonitor:
    started_at: datetime
    last_tick_at: datetime | None = None
    next_tick_at: datetime | None = None
    tick_count: int = 0
    last_tick_errors: list[str] = field(default_factory=list)


@dataclass
class ChannelConfig:
    entry: ChannelEntry
    channel: str
    channel_id: int | None = None
    discussion_id: int | None = None
    subscribers: int | None = None


@dataclass
class PostCandidate:
    message_id: int
    text: str
    age: timedelta
    comment_count: int
    comments_open: bool


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


def _message_age(msg: Message, now: datetime) -> timedelta:
    posted = msg.date
    if posted.tzinfo is None:
        posted = posted.replace(tzinfo=timezone.utc)
    return now - posted


def _post_text(msg: Message) -> str | None:
    text = (msg.message or "").strip()
    if text:
        return text[:4000]
    if msg.media:
        return "[пост с медиа]"
    return None


def _comment_count(msg: Message) -> int:
    if msg.replies and msg.replies.replies is not None:
        return msg.replies.replies
    return 0


def _comments_open(msg: Message) -> bool:
    if msg.replies is None:
        return False
    return bool(msg.replies.comments)



def load_channels_raw() -> dict[str, ChannelEntry]:
    return load_store()


def load_channel_names() -> list[str]:
    entries = load_store()
    names = [e.username for e in entries.values() if e.enabled and e.username]
    if names:
        return names
    return list(cfg.CHANNELS_FALLBACK)


class NeuroState:
    """Cooldown по каналам и отклонённые посты (переживает перезапуск)."""

    def __init__(self, path: Path) -> None:
        self.path = path
        self.cooldowns: dict[str, str] = {}
        self.rejected_posts: dict[str, list[int]] = {}
        self.commented_posts: dict[str, list[int]] = {}
        self._load()

    def _load(self) -> None:
        if not self.path.exists():
            return
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            return
        self.cooldowns = data.get("cooldowns", {})
        self.rejected_posts = {
            k: list(v) for k, v in data.get("rejected_posts", {}).items()
        }
        self.commented_posts = {
            k: list(v) for k, v in data.get("commented_posts", {}).items()
        }

    def _save(self) -> None:
        self.path.write_text(
            json.dumps(
                {
                    "cooldowns": self.cooldowns,
                    "rejected_posts": self.rejected_posts,
                    "commented_posts": self.commented_posts,
                },
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
        )

    def can_comment(
        self, channel_key: str, freeze: timedelta | None = None
    ) -> tuple[bool, datetime | None]:
        raw = self.cooldowns.get(channel_key)
        if not raw:
            return True, None
        last = datetime.fromisoformat(raw)
        if last.tzinfo is None:
            last = last.replace(tzinfo=timezone.utc)
        cooldown = freeze or cfg.GLOBAL_COOLDOWN
        next_allowed = last + cooldown
        now = _utc_now()
        if now >= next_allowed:
            return True, None
        return False, next_allowed

    def mark_commented(self, channel_key: str, post_id: int) -> None:
        self.cooldowns[channel_key] = _utc_now().isoformat()
        ids = self.commented_posts.setdefault(channel_key, [])
        if post_id not in ids:
            ids.append(post_id)
        self._save()

    def mark_rejected(self, channel_key: str, post_id: int) -> None:
        ids = self.rejected_posts.setdefault(channel_key, [])
        if post_id not in ids:
            ids.append(post_id)
        self._save()

    def is_processed(self, channel_key: str, post_id: int) -> bool:
        return post_id in self.rejected_posts.get(
            channel_key, []
        ) or post_id in self.commented_posts.get(channel_key, [])


state = NeuroState(cfg.STATE_FILE)
channels: dict[str, ChannelConfig] = {}
runtime = RuntimeMonitor(started_at=_utc_now())


def _channel_key(name: str) -> str:
    return name.lower().lstrip("@")


async def _llm_request(
    system: str,
    user: str,
    *,
    max_tokens: int,
    temperature: float,
) -> str | None:
    last_error = None
    for attempt in range(1, 4):
        try:
            response = await openai_client.chat.completions.create(
                model=cfg.MODEL,
                messages=[
                    {"role": "system", "content": system},
                    {"role": "user", "content": user},
                ],
                max_tokens=max_tokens,
                temperature=temperature,
            )
            return (response.choices[0].message.content or "").strip()
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


def _parse_classification(raw: str) -> tuple[bool, str, str]:
    text = raw.strip()
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?\s*", "", text)
        text = re.sub(r"\s*```$", "", text)
    try:
        data = json.loads(text)
        suitable = bool(data.get("suitable"))
        reason = str(data.get("reason", ""))
        post_type = str(data.get("post_type", "—"))
        return suitable, reason, post_type
    except json.JSONDecodeError:
        lowered = text.lower()
        if '"suitable": true' in lowered or '"suitable":true' in lowered:
            return True, text[:120], "—"
        return False, f"не удалось разобрать ответ: {text[:120]}", "—"


async def classify_post(post_text: str) -> tuple[bool, str, str]:
    raw = await _llm_request(
        CLASSIFY_SYSTEM,
        f"Текст поста:\n{post_text}",
        max_tokens=200,
        temperature=0.2,
    )
    if not raw:
        return False, "ошибка API", "—"
    return _parse_classification(raw)


async def generate_comment(post_text: str) -> str | None:
    raw = await _llm_request(
        COMMENT_SYSTEM,
        f"Пост:\n{post_text}\n\nНапиши комментарий:",
        max_tokens=320,
        temperature=0.85,
    )
    if not raw:
        return None
    comment = raw.strip()
    if comment.startswith('"') and comment.endswith('"'):
        comment = comment[1:-1].strip()
    return comment or None


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


async def scan_pending_posts(ch: ChannelConfig) -> list[PendingPostInfo]:
    """Посты в локальном ожидании (возраст / комментарии), без LLM."""
    key = _channel_key(ch.channel)
    if not state.can_comment(key, ch.entry.freeze_time)[0]:
        return []

    pending: list[PendingPostInfo] = []
    candidates = await collect_candidates(ch)
    for post in candidates:
        reason = _skip_reason(post, key, ch)
        if not reason or reason == "уже обработан":
            continue

        ticks_left = 1
        if post.age < ch.entry.post_min_age:
            ticks_left = _estimate_ticks(ch.entry.post_min_age - post.age)
        elif "комментариев" in reason:
            ticks_left = 1

        pending.append(
            PendingPostInfo(
                post_id=post.message_id,
                reason=reason,
                ticks_left=ticks_left,
            )
        )
    return pending


def _admin_commands() -> AdminCommands:
    return AdminCommands(
        AdminContext(
            state=state,
            runtime=runtime,
            channels=channels,
            channel_key=_channel_key,
            load_channels_raw=load_channels_raw,
            scan_pending=scan_pending_posts,
            reload_channels=setup_channels,
        )
    )


async def _reply_chunks(event: events.NewMessage.Event, text: str) -> None:
    limit = 4000
    if len(text) <= limit:
        await event.reply(text)
        return
    for i in range(0, len(text), limit):
        await event.reply(text[i : i + limit])


async def admin_message_handler(event: events.NewMessage.Event) -> None:
    if not event.is_private:
        return
    sender_id = event.sender_id
    if sender_id not in cfg.ADMIN_USER_IDS:
        return
    if event.out:
        return

    text = (event.message.message or "").strip()
    if not text:
        return

    parsed = parse_add_channel(text)
    if parsed:
        link, group_id = parsed
        try:
            entry = add_channel_entry(link, group_id)
            await setup_channels()
            user = entry.username or link
            await event.reply(
                f"✅ Канал #{entry.entry_id} добавлен\n"
                f"• {entry.channel_link}\n"
                f"• group_id: {entry.group_id}\n"
                f"• freeze: {entry.freeze_days} д\n"
                f"Подхватится на следующем тике мониторинга (или уже сейчас)."
            )
        except ValueError as e:
            await event.reply(f"❌ {e}")
        return

    admin = _admin_commands()
    reply = await admin.handle_async(text)
    await _reply_chunks(event, reply)


async def setup_channels() -> None:
    channels.clear()
    entries = load_store()
    enabled = [e for e in entries.values() if e.enabled]
    if not enabled:
        print("⚠ channels.json: нет активных каналов")
        return

    for entry in sorted(enabled, key=lambda e: int(e.entry_id) if e.entry_id.isdigit() else e.entry_id):
        username = entry.username
        if not username:
            print(f"  ⚠ #{entry.entry_id}: некорректная ссылка {entry.channel_link}")
            continue
        try:
            entity = await client.get_entity(username)
            full = await client(GetFullChannelRequest(entity))
            subscribers = getattr(full.full_chat, "participants_count", None)
            linked = full.full_chat.linked_chat_id
            discussion_id = entry.group_id if entry.group_id else linked
            if entry.group_id and linked and entry.group_id != linked:
                print(
                    f"  ⚠ @{username}: group_id в json ({entry.group_id}) "
                    f"≠ linked ({linked})"
                )

            ch = ChannelConfig(
                entry=entry,
                channel=username,
                channel_id=utils.get_peer_id(entity),
                discussion_id=discussion_id,
                subscribers=subscribers,
            )
            channels[_channel_key(username)] = ch

            sub_info = f"{subscribers:,}" if subscribers else "?"
            disc = discussion_id if discussion_id else "нет"
            print(
                f"  • #{entry.entry_id} @{username}: "
                f"подписчики {sub_info}, беседа {disc}, "
                f"freeze {entry.freeze_days}д"
            )
        except Exception as e:
            print(f"  ❌ #{entry.entry_id} @{username}: {e}")


def _skip_reason(
    candidate: PostCandidate, channel_key: str, ch: ChannelConfig
) -> str | None:
    if state.is_processed(channel_key, candidate.message_id):
        return "уже обработан"

    if not candidate.comments_open:
        return "комментарии закрыты"

    if candidate.age < ch.entry.post_min_age:
        left = ch.entry.post_min_age - candidate.age
        return f"слишком свежий, ждём ещё {_format_timedelta(left)}"

    if candidate.comment_count < ch.entry.min_comments:
        if candidate.age >= ch.entry.post_activity_window:
            return (
                f"мало активности ({candidate.comment_count} "
                f"< {ch.entry.min_comments})"
            )
        return (
            f"мало комментариев ({candidate.comment_count}), "
            f"ждём следующий тик"
        )

    return None


async def collect_candidates(ch: ChannelConfig) -> list[PostCandidate]:
    if (
        ch.subscribers is not None
        and ch.subscribers < ch.entry.min_subscribers
    ):
        return []

    if not ch.discussion_id:
        return []

    now = _utc_now()
    max_age = ch.entry.post_activity_window + cfg.MONITORING_INTERVAL * 2
    result: list[PostCandidate] = []

    async for msg in client.iter_messages(
        ch.channel, limit=ch.entry.posts_scan_limit
    ):
        if not isinstance(msg, Message):
            continue
        text = _post_text(msg)
        if not text:
            continue

        age = _message_age(msg, now)
        if age > max_age:
            break

        result.append(
            PostCandidate(
                message_id=msg.id,
                text=text,
                age=age,
                comment_count=_comment_count(msg),
                comments_open=_comments_open(msg),
            )
        )

    result.sort(key=lambda p: p.message_id)
    return result


async def process_channel(ch: ChannelConfig) -> bool:
    """Ищет пост и комментирует. True — если отправили комментарий."""
    key = _channel_key(ch.channel)
    allowed, next_at = state.can_comment(key, ch.entry.freeze_time)
    if not allowed:
        left = next_at - _utc_now()
        print(
            f"⏸ @{ch.channel}: заморозка, "
            f"осталось {_format_timedelta(left)}"
        )
        return False

    if (
        ch.subscribers is not None
        and ch.subscribers < ch.entry.min_subscribers
    ):
        print(
            f"⏭ @{ch.channel}: мало подписчиков "
            f"({ch.subscribers} < {ch.entry.min_subscribers})"
        )
        return False

    if not ch.discussion_id:
        print(f"⏭ @{ch.channel}: нет группы обсуждений")
        return False

    candidates = await collect_candidates(ch)
    if not candidates:
        print(f"⏭ @{ch.channel}: нет постов для проверки")
        return False

    for post in candidates:
        reason = _skip_reason(post, key, ch)
        if reason:
            if reason.startswith("мало активности") or reason == "комментарии закрыты":
                state.mark_rejected(key, post.message_id)
            print(
                f"  ↳ пост {post.message_id}: пропуск — {reason} "
                f"(возраст {_format_timedelta(post.age)}, "
                f"комментов {post.comment_count})"
            )
            continue

        print(
            f"\n🔍 @{ch.channel}: пост {post.message_id} — "
            f"проверка типа (возраст {_format_timedelta(post.age)}, "
            f"комментов {post.comment_count})"
        )

        suitable, classify_reason, _post_type = await classify_post(post.text)
        if not suitable:
            state.mark_rejected(key, post.message_id)
            print(f"  ↳ LLM: не подходит — {classify_reason}")
            continue

        print(f"  ↳ LLM: подходит — {classify_reason}")
        comment = await generate_comment(post.text)
        if not comment:
            print("  ↳ пропуск: не удалось сгенерировать комментарий")
            continue

        lo, hi = cfg.COMMENT_SEND_DELAY
        await asyncio.sleep(random.uniform(lo, hi))

        try:
            await send_channel_comment(ch.channel, post.message_id, comment)
            state.mark_commented(key, post.message_id)
            print(
                f"✅ @{ch.channel}: комментарий к посту {post.message_id}: "
                f"{comment[:80]}..."
            )
            return True
        except Exception as e:
            print(f"❌ @{ch.channel}: ошибка отправки: {e}")
            return False

    return False


async def monitoring_tick() -> None:
    now = _utc_now().astimezone()
    runtime.last_tick_at = _utc_now()
    runtime.last_tick_errors.clear()
    print(f"\n─── Тик мониторинга {now.strftime('%d.%m.%Y %H:%M')} ───")
    await setup_channels()
    for ch in channels.values():
        try:
            await process_channel(ch)
        except Exception as e:
            msg = f"@{ch.channel}: {e}"
            runtime.last_tick_errors.append(msg)
            print(f"❌ {msg}")


async def monitoring_loop() -> None:
    while True:
        await monitoring_tick()
        runtime.tick_count += 1
        runtime.next_tick_at = _utc_now() + cfg.MONITORING_INTERVAL
        wait_sec = int(cfg.MONITORING_INTERVAL.total_seconds())
        print(f"\n⏳ Следующий тик через {_format_timedelta(cfg.MONITORING_INTERVAL)}")
        await asyncio.sleep(wait_sec)


async def main() -> None:
    await client.start(phone=PHONE)
    me = await client.get_me()
    name = f"@{me.username}" if me.username else me.first_name
    print(f"✅ Нейрокомментер запущен! Аккаунт: {name}")
    print(f"Модель: {cfg.MODEL}")
    print(f"Глобальная заморозка: {_format_timedelta(cfg.GLOBAL_COOLDOWN)}")
    print(f"Интервал мониторинга: {_format_timedelta(cfg.MONITORING_INTERVAL)}")
    print(f"Мин. возраст поста: {_format_timedelta(cfg.POST_MIN_AGE)}")
    print(f"Мин. комментариев под постом: {cfg.MIN_COMMENTS_UNDER_POST}")
    print(f"Админ-команды в личку: {cfg.ADMIN_USER_IDS}")
    print("Команды: каналы | статус | статус каналов")
    await setup_channels()

    for ch in channels.values():
        key = _channel_key(ch.channel)
        ok, next_at = state.can_comment(key, ch.entry.freeze_time)
        status = (
            "готов"
            if ok
            else f"заморозка до {next_at.astimezone().strftime('%d.%m.%Y %H:%M')}"
        )
        print(f"  @{ch.channel} [{status}]")

    runtime.next_tick_at = _utc_now() + cfg.MONITORING_INTERVAL
    client.add_event_handler(
        admin_message_handler,
        events.NewMessage(incoming=True),
    )

    loop_task = asyncio.create_task(monitoring_loop())
    try:
        await client.run_until_disconnected()
    finally:
        loop_task.cancel()


if __name__ == "__main__":
    asyncio.run(main())
