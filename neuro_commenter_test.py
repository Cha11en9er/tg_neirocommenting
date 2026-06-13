"""
Тестовый бот — без заморозок и без боевого state.
Комментирует только НОВЫЕ посты (появившиеся после запуска или с прошлого тика).

Запуск:
  python neuro_commenter_test.py

Опционально:
  TEST_MONITORING_MINUTES=5 — пауза между проходами (по умолчанию 0)
  TEST_RESET_BASELINE=1     — при старте снова «отсечь» старые посты без комментов
"""
import asyncio
import json
import os
from datetime import timedelta
from pathlib import Path

from telethon import events
from telethon.tl.types import Message

import neuro_config as cfg
import neuro_commenter as nc
from neuro_commenter import (
    ChannelConfig,
    PostCandidate,
    _channel_key,
    _comment_count,
    _comments_open,
    _format_timedelta,
    _message_age,
    _post_text,
    _utc_now,
    admin_message_handler,
    channels,
    classify_post,
    client,
    generate_comment,
    send_channel_comment,
    setup_channels,
)

PHONE = nc.PHONE
TEST_STATE_FILE = Path(__file__).with_name("neuro_state_test.json")
TEST_MONITORING_MINUTES = int(os.getenv("TEST_MONITORING_MINUTES", "0"))
TEST_RESET_BASELINE = os.getenv("TEST_RESET_BASELINE", "").lower() in (
    "1",
    "true",
    "yes",
)


class TestState:
    """Только для теста: последний виденный пост и уже прокомментированные."""

    def __init__(self, path: Path) -> None:
        self.path = path
        self.last_post_id: dict[str, int] = {}
        self.commented_posts: dict[str, list[int]] = {}
        self._load()

    def _load(self) -> None:
        if not self.path.exists():
            return
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            return
        self.last_post_id = {
            k: int(v) for k, v in data.get("last_post_id", {}).items()
        }
        self.commented_posts = {
            k: list(v) for k, v in data.get("commented_posts", {}).items()
        }

    def save(self) -> None:
        self.path.write_text(
            json.dumps(
                {
                    "last_post_id": self.last_post_id,
                    "commented_posts": self.commented_posts,
                },
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
        )

    def is_commented(self, channel_key: str, post_id: int) -> bool:
        return post_id in self.commented_posts.get(channel_key, [])

    def mark_commented(self, channel_key: str, post_id: int) -> None:
        ids = self.commented_posts.setdefault(channel_key, [])
        if post_id not in ids:
            ids.append(post_id)
        self.set_last_seen(channel_key, post_id)
        self.save()

    def set_last_seen(self, channel_key: str, post_id: int) -> None:
        prev = self.last_post_id.get(channel_key, 0)
        if post_id > prev:
            self.last_post_id[channel_key] = post_id

    def last_seen(self, channel_key: str) -> int:
        return self.last_post_id.get(channel_key, 0)


test_state = TestState(TEST_STATE_FILE)


def _heuristic_reason(post: PostCandidate, ch: ChannelConfig) -> str | None:
    if not post.comments_open:
        return "комментарии закрыты"
    if post.age < ch.entry.post_min_age:
        left = ch.entry.post_min_age - post.age
        return f"слишком свежий, ждём ещё {_format_timedelta(left)}"
    if post.comment_count < ch.entry.min_comments:
        if post.age >= ch.entry.post_activity_window:
            return (
                f"мало активности ({post.comment_count} "
                f"< {ch.entry.min_comments})"
            )
        return (
            f"мало комментариев ({post.comment_count}), "
            f"ждём следующий тик"
        )
    return None


def _build_test_comment(
    *,
    post_type: str,
    reason: str,
    suitable: bool,
    heuristic: str | None,
    generated: str | None,
) -> str:
    lines = [
        "🧪 тест нейрокомментинга",
        f"Тип: {post_type}",
        f"Подходит: {'да' if suitable else 'нет'}",
        f"О чём: {reason}",
    ]
    if heuristic:
        lines.append(f"Фильтр бота: {heuristic}")
    if suitable and generated:
        lines.extend(["", "Комментарий:", generated])
    elif suitable and not generated:
        lines.append("Комментарий: не удалось сгенерировать")
    return "\n".join(lines)


async def _fetch_recent_posts(
    ch: ChannelConfig, *, after_id: int = 0
) -> list[PostCandidate]:
    if not ch.discussion_id:
        return []

    now = _utc_now()
    result: list[PostCandidate] = []

    async for msg in client.iter_messages(
        ch.channel, limit=ch.entry.posts_scan_limit
    ):
        if not isinstance(msg, Message):
            continue
        if msg.id <= after_id:
            break
        text = _post_text(msg)
        if not text:
            continue
        result.append(
            PostCandidate(
                message_id=msg.id,
                text=text,
                age=_message_age(msg, now),
                comment_count=_comment_count(msg),
                comments_open=_comments_open(msg),
            )
        )

    result.sort(key=lambda p: p.message_id)
    return result


async def init_baseline(ch: ChannelConfig) -> None:
    """При первом запуске — запомнить последний пост, старые не трогать."""
    key = _channel_key(ch.channel)
    if TEST_RESET_BASELINE:
        test_state.last_post_id.pop(key, None)

    if key in test_state.last_post_id:
        print(
            f"  @{ch.channel}: продолжаем с поста "
            f"#{test_state.last_seen(key) + 1}"
        )
        return

    posts = await _fetch_recent_posts(ch)
    if not posts:
        test_state.set_last_seen(key, 0)
        test_state.save()
        print(f"  @{ch.channel}: постов нет, ждём новые")
        return

    latest = max(p.message_id for p in posts)
    test_state.set_last_seen(key, latest)
    test_state.save()
    print(
        f"  @{ch.channel}: базовая линия #{latest} "
        f"({len(posts)} пост(ов) в ленте — не комментируем)"
    )


async def process_channel_test(ch: ChannelConfig) -> None:
    key = _channel_key(ch.channel)

    if not ch.discussion_id:
        print(f"⏭ @{ch.channel}: нет group_id / беседы — комментарии недоступны")
        return

    after_id = test_state.last_seen(key)
    posts = await _fetch_recent_posts(ch, after_id=after_id)
    posts = [
        p
        for p in posts
        if p.message_id > after_id and not test_state.is_commented(key, p.message_id)
    ]

    if not posts:
        print(f"⏭ @{ch.channel}: новых постов нет (последний #{after_id})")
        return

    print(f"📬 @{ch.channel}: новых постов {len(posts)} (после #{after_id})")

    sent = 0
    skipped_closed = 0
    for post in posts:
        test_state.set_last_seen(key, post.message_id)

        if not post.comments_open:
            skipped_closed += 1
            print(f"  ↳ пост {post.message_id}: комментарии закрыты")
            continue

        suitable, reason, post_type = await classify_post(post.text)
        heuristic = _heuristic_reason(post, ch)
        generated = None
        if suitable:
            generated = await generate_comment(post.text)

        body = _build_test_comment(
            post_type=post_type,
            reason=reason,
            suitable=suitable,
            heuristic=heuristic,
            generated=generated,
        )

        try:
            await send_channel_comment(ch.channel, post.message_id, body)
            test_state.mark_commented(key, post.message_id)
            sent += 1
            print(f"  ✅ пост {post.message_id}: тест-коммент отправлен")
        except Exception as e:
            print(f"  ❌ пост {post.message_id}: {e}")

    test_state.save()

    if skipped_closed and not sent:
        print(
            f"⏭ @{ch.channel}: {skipped_closed} новых пост(ов), "
            f"но комментарии закрыты"
        )
    elif sent:
        print(f"🧪 @{ch.channel}: отправлено {sent} тест-комментариев")


async def monitoring_tick() -> None:
    now = _utc_now().astimezone()
    print(f"\n─── ТЕСТ-тик {now.strftime('%d.%m.%Y %H:%M')} ───")
    await setup_channels()
    for ch in channels.values():
        try:
            await process_channel_test(ch)
        except Exception as e:
            print(f"❌ @{ch.channel}: {e}")


async def monitoring_loop() -> None:
    interval = timedelta(minutes=TEST_MONITORING_MINUTES)
    while True:
        await monitoring_tick()
        if interval.total_seconds() > 0:
            print(f"\n⏳ Следующий тик через {_format_timedelta(interval)}")
            await asyncio.sleep(int(interval.total_seconds()))


async def main() -> None:
    await client.start(phone=PHONE)
    me = await client.get_me()
    name = f"@{me.username}" if me.username else me.first_name
    print("🧪 ТЕСТ: только новые посты, без заморозок, state: neuro_state_test.json")
    print(f"✅ Аккаунт: {name}")
    print(f"Модель: {cfg.MODEL}")
    if TEST_MONITORING_MINUTES:
        print(f"Интервал тиков: {TEST_MONITORING_MINUTES} мин")
    else:
        print("Интервал тиков: сразу после прохода (ждём новые посты)")
    await setup_channels()
    print("Базовая линия (старые посты не трогаем):")
    for ch in channels.values():
        await init_baseline(ch)

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
