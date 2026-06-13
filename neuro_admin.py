"""Дебаг-команды для админа в личных сообщениях аккаунта-комментатора."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import TYPE_CHECKING, Awaitable, Callable

import neuro_config as cfg

if TYPE_CHECKING:
    from channels_store import ChannelEntry
    from neuro_commenter import ChannelConfig, NeuroState, RuntimeMonitor


def _format_timedelta(delta: timedelta) -> str:
    total = int(delta.total_seconds())
    if total < 0:
        total = 0
    if total < 60:
        return f"{total} сек"
    if total < 3600:
        return f"{total // 60} мин"
    if total < 86400:
        hours = total // 3600
        mins = (total % 3600) // 60
        return f"{hours} ч {mins} мин" if mins else f"{hours} ч"
    days = total // 86400
    hours = (total % 86400) // 3600
    return f"{days} д {hours} ч" if hours else f"{days} д"


def _estimate_ticks(delta: timedelta) -> int:
    interval = max(int(cfg.MONITORING_INTERVAL.total_seconds()), 1)
    return max(1, (int(delta.total_seconds()) + interval - 1) // interval)


@dataclass
class PendingPostInfo:
    post_id: int
    reason: str
    ticks_left: int


@dataclass
class AdminContext:
    state: "NeuroState"
    runtime: "RuntimeMonitor"
    channels: dict[str, "ChannelConfig"]
    channel_key: Callable[[str], str]
    load_channels_raw: Callable[[], dict[str, "ChannelEntry"]]
    scan_pending: Callable[["ChannelConfig"], Awaitable[list[PendingPostInfo]]]
    reload_channels: Callable[[], Awaitable[None]] | None = None


class AdminCommands:
    def __init__(self, ctx: AdminContext) -> None:
        self.ctx = ctx

    def handle(self, text: str) -> str:
        cmd = (text or "").strip().lower()
        if cmd in ("каналы", "channels"):
            return self._cmd_channels()
        if cmd in ("статус", "status"):
            return self._cmd_status()
        if cmd in ("статус каналов", "status channels", "статус канала"):
            return self._cmd_channels_status()
        if cmd in ("помощь", "help", "?"):
            return self._cmd_help()
        return self._cmd_help()

    def _cmd_help(self) -> str:
        return (
            "Команды:\n"
            "• каналы — список из channels.json\n"
            "• статус — общее состояние\n"
            "• статус каналов — фриз и ожидание по каналам\n\n"
            "Добавить канал (одной строкой):\n"
            "https://t.me/username - . -3511597340\n"
            "или: добавить https://t.me/username -3511597340\n\n"
            "Перед добавлением: зайти в канал и чат с аккаунта бота."
        )

    def _cmd_channels(self) -> str:
        entries = self.ctx.load_channels_raw()
        if not entries:
            return "channels.json пуст."

        lines = ["Каналы (channels.json):", ""]
        for eid in sorted(entries.keys(), key=lambda k: int(k) if str(k).isdigit() else k):
            entry = entries[eid]
            ch_key = self.ctx.channel_key(entry.username or "")
            loaded = self.ctx.channels.get(ch_key)
            status = "✓ в мониторинге" if loaded else ("выкл" if not entry.enabled else "не загружен")
            lines.append(f"#{eid} {entry.channel_link}")
            lines.append(f"   group_id: {entry.group_id} | {status}")
            lines.append(
                f"   freeze: {entry.freeze_days}д | "
                f"min комментов: {entry.min_comments} | "
                f"min подписчиков: {entry.min_subscribers:,}"
            )
            lines.append(
                f"   возраст поста: {entry.post_min_age_minutes} мин | "
                f"окно активности: {entry.post_activity_window_minutes} мин"
            )
            lines.append("")
        return "\n".join(lines).rstrip()

    def _cmd_status(self) -> str:
        rt = self.ctx.runtime
        now = datetime.now().astimezone()
        uptime = now - rt.started_at.astimezone()
        lines = [
            "✅ Нейрокомментер работает",
            "",
            f"Модель: {cfg.MODEL}",
            f"Uptime: {_format_timedelta(uptime)}",
            f"Тиков мониторинга: {rt.tick_count}",
        ]

        if rt.last_tick_at:
            lines.append(
                f"Последний тик: {rt.last_tick_at.astimezone().strftime('%d.%m.%Y %H:%M:%S')}"
            )
        if rt.next_tick_at:
            left = rt.next_tick_at - datetime.now(tz=rt.next_tick_at.tzinfo)
            lines.append(
                f"Следующий тик: через {_format_timedelta(left)} "
                f"({rt.next_tick_at.astimezone().strftime('%H:%M:%S')})"
            )

        lines.extend(
            [
                "",
                f"Интервал мониторинга: {_format_timedelta(cfg.MONITORING_INTERVAL)}",
                f"Каналов в json: {len(self.ctx.load_channels_raw())}",
                f"Каналов в мониторинге: {len(self.ctx.channels)}",
            ]
        )

        if rt.last_tick_errors:
            lines.append("")
            lines.append("Ошибки последнего тика:")
            lines.extend(f"• {err}" for err in rt.last_tick_errors[-5:])

        return "\n".join(lines)

    async def handle_async(self, text: str) -> str:
        cmd = (text or "").strip().lower()
        if cmd in ("статус каналов", "status channels", "статус канала"):
            return await self._cmd_channels_status_async()
        return self.handle(text)

    async def _cmd_channels_status_async(self) -> str:
        lines = ["Статус каналов:", ""]
        rt = self.ctx.runtime

        if rt.next_tick_at:
            left = rt.next_tick_at - datetime.now(tz=rt.next_tick_at.tzinfo)
            lines.append(
                f"⏱ Следующий тик мониторинга: через {_format_timedelta(left)}"
            )
            lines.append("")

        if not self.ctx.channels:
            lines.append("Нет загруженных каналов.")
            return "\n".join(lines)

        for ch in self.ctx.channels.values():
            key = self.ctx.channel_key(ch.channel)
            allowed, next_at = self.ctx.state.can_comment(key, ch.entry.freeze_time)

            lines.append(f"#{ch.entry.entry_id} @{ch.channel}")
            if allowed:
                lines.append(f"  Заморозка ({ch.entry.freeze_days}д): готов")
            else:
                left = next_at - datetime.now(tz=next_at.tzinfo)
                lines.append(
                    f"  Заморозка: {_format_timedelta(left)} "
                    f"(до {next_at.astimezone().strftime('%d.%m.%Y %H:%M')})"
                )

            subs = ch.subscribers
            if subs is not None:
                ok = subs >= ch.entry.min_subscribers
                lines.append(
                    f"  Подписчики: {subs:,} "
                    f"({'ok' if ok else f'< {ch.entry.min_subscribers:,}'})"
                )

            gid = ch.entry.group_id or ch.discussion_id
            if not gid:
                lines.append("  ⚠ Нет group_id / беседы")
            else:
                lines.append(f"  group_id: {gid}")

            pending = await self.ctx.scan_pending(ch)
            if not pending:
                lines.append("  Ожидание постов: нет активных кандидатов")
            else:
                lines.append(f"  Ожидание постов ({len(pending)}):")
                for item in pending[:5]:
                    lines.append(
                        f"    • #{item.post_id}: {item.reason} "
                        f"(~{item.ticks_left} тик(ов))"
                    )
                if len(pending) > 5:
                    lines.append(f"    … ещё {len(pending) - 5}")

            commented = len(self.ctx.state.commented_posts.get(key, []))
            rejected = len(self.ctx.state.rejected_posts.get(key, []))
            lines.append(
                f"  Обработано: {commented} коммент., {rejected} отклон."
            )
            lines.append("")

        return "\n".join(lines).rstrip()

    def _cmd_channels_status(self) -> str:
        return "Используйте «статус каналов»"
