"""Дебаг-команды для админа в личных сообщениях аккаунта-комментатора."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import TYPE_CHECKING, Awaitable, Callable

import neuro_config as cfg

if TYPE_CHECKING:
    from channels_store import ChannelEntry
    from neuro_commenter import ChannelConfig, NeuroState, RuntimeMonitor

# Единые названия настроек во всех ответах админу
LBL_FREEZE = "заморозка"
LBL_MONITORING = "мониторинг"
LBL_POST_AGE = "возраст поста"
LBL_COMMENTS = "комментариев"
LBL_SUBSCRIBERS = "подписчиков"
LBL_ACTIVITY_WINDOW = "окно активности"
LBL_MODEL = "модель"


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


def _format_freeze(entry: "ChannelEntry") -> str:
    ft = entry.freeze_time
    if ft.total_seconds() < 86400:
        return f"{int(ft.total_seconds() // 60)} мин"
    return f"{entry.freeze_days:g} д"


def _estimate_ticks(delta: timedelta) -> int:
    interval = max(int(cfg.MONITORING_INTERVAL.total_seconds()), 1)
    return max(1, (int(delta.total_seconds()) + interval - 1) // interval)


def _format_global_settings_lines() -> list[str]:
    return [
        f"• {LBL_FREEZE}: {_format_timedelta(cfg.GLOBAL_COOLDOWN)}",
        f"• {LBL_MONITORING}: {_format_timedelta(cfg.MONITORING_INTERVAL)}",
        f"• {LBL_POST_AGE}: {_format_timedelta(cfg.POST_MIN_AGE)}",
        f"• {LBL_COMMENTS}: {cfg.MIN_COMMENTS_UNDER_POST}",
        f"• {LBL_MODEL}: {cfg.MODEL}",
    ]


def _format_channel_settings_lines(
    entry: "ChannelEntry", *, indent: str = "   "
) -> list[str]:
    return [
        (
            f"{indent}{LBL_FREEZE}: {_format_freeze(entry)} | "
            f"{LBL_COMMENTS}: {entry.min_comments} | "
            f"{LBL_SUBSCRIBERS}: {entry.min_subscribers:,}"
        ),
        (
            f"{indent}{LBL_POST_AGE}: {entry.post_min_age_minutes} мин | "
            f"{LBL_ACTIVITY_WINDOW}: {entry.post_activity_window_minutes} мин"
        ),
    ]


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
    check_access: Callable[["ChannelConfig"], Awaitable[str]] | None = None
    reload_channels: Callable[[], Awaitable[None]] | None = None


class AdminCommands:
    def __init__(self, ctx: AdminContext) -> None:
        self.ctx = ctx

    def handle(self, text: str) -> str | None:
        cmd = (text or "").strip().lower()
        if cmd == "настройки":
            return self._cmd_settings()
        if cmd in ("каналы", "channels"):
            return self._cmd_channels()
        if cmd in ("статус", "status"):
            return self._cmd_status()
        if cmd in ("статус каналов", "status channels", "статус канала"):
            return "Запрос обрабатывается…"
        return None

    def _cmd_settings(self) -> str:
        if getattr(cfg, "DAILY_REPORT_INTERVAL", None):
            report_line = (
                f"Каждые {_format_timedelta(cfg.DAILY_REPORT_INTERVAL)} — "
                "«статус» + «статус каналов» (только подписчикам).\n"
            )
        else:
            report_line = (
                f"Каждый день в {cfg.DAILY_REPORT_HOUR_MSK}:00 МСК — "
                "«статус» + «статус каналов» (только подписчикам).\n"
            )
        return (
            "⚙️ Команды\n"
            "\n"
            "статус — работает ли бот, uptime, тики\n"
            "статус каналов — заморозка, пропуски, комментарии, бан\n"
            "каналы — список из channels.json\n"
            "настройки — это сообщение\n"
            "\n"
            "старт отправки — включить системные уведомления\n"
            "стоп отправки — отключить уведомления\n"
            "\n"
            "Добавить канал (подписка + чат обсуждений с аккаунта бота):\n"
            "https://t.me/username - . -3511597340\n"
            "\n"
            "Удалить из мониторинга (бот не выходит сам):\n"
            "удаление https://t.me/username - . -3511597340\n"
            "\n"
            f"{report_line}"
            "\n"
            "── Текущие настройки ──\n"
            + "\n".join(_format_global_settings_lines())
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
            if not entry.enabled:
                status = "отключён"
            elif loaded:
                status = "✓ в мониторинге"
            else:
                status = "не загружен"
            lines.append(f"#{eid} {entry.channel_link}")
            lines.append(f"   group_id: {entry.group_id} | {status}")
            lines.extend(_format_channel_settings_lines(entry))
            lines.append("")
        return "\n".join(lines).rstrip()

    def _cmd_status(self) -> str:
        rt = self.ctx.runtime
        now = datetime.now().astimezone()
        uptime = now - rt.started_at.astimezone()
        lines = [
            "✅ Нейрокомментер работает",
            "",
            f"{LBL_MODEL}: {cfg.MODEL}",
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
                f"{LBL_MONITORING}: {_format_timedelta(cfg.MONITORING_INTERVAL)}",
                f"{LBL_FREEZE}: {_format_timedelta(cfg.GLOBAL_COOLDOWN)}",
                f"Каналов в json: {len(self.ctx.load_channels_raw())}",
                f"Каналов в мониторинге: {len(self.ctx.channels)}",
            ]
        )

        if rt.last_tick_errors:
            lines.append("")
            lines.append("Ошибки последнего тика:")
            lines.extend(f"• {err}" for err in rt.last_tick_errors[-5:])

        return "\n".join(lines)

    async def handle_async(self, text: str) -> str | None:
        cmd = (text or "").strip().lower()
        if cmd in ("статус каналов", "status channels", "статус канала"):
            if self.ctx.reload_channels:
                await self.ctx.reload_channels()
            return await self._cmd_channels_status_async()
        return self.handle(text)

    async def build_daily_report(self) -> str:
        status = self._cmd_status()
        channels = await self._cmd_channels_status_async()
        now_msk = datetime.now(cfg.MSK).strftime("%d.%m.%Y %H:%M")
        return f"📋 Ежедневный отчёт ({now_msk} МСК)\n\n{status}\n\n{channels}"

    async def _cmd_channels_status_async(self) -> str:
        lines = ["Статус каналов:", ""]
        rt = self.ctx.runtime

        if rt.next_tick_at:
            left = rt.next_tick_at - datetime.now(tz=rt.next_tick_at.tzinfo)
            if left.total_seconds() < 0:
                left = timedelta(0)
            lines.append(
                f"⏱ Следующий тик мониторинга: через {_format_timedelta(left)}"
            )
            lines.append("")

        entries = self.ctx.load_channels_raw()
        enabled_entries = [e for e in entries.values() if e.enabled]
        if not enabled_entries:
            lines.append("Нет активных каналов в channels.json.")
            return "\n".join(lines)

        for entry in sorted(
            enabled_entries,
            key=lambda e: int(e.entry_id) if e.entry_id.isdigit() else e.entry_id,
        ):
            ch = self.ctx.channels.get(self.ctx.channel_key(entry.username or ""))
            key = self.ctx.channel_key(entry.username or "")
            lines.append(f"#{entry.entry_id} {entry.channel_link}")

            if not ch:
                err = rt.channel_load_errors.get(entry.username or "")
                lines.append("  ⚠ Не загружен (проверьте подписку и доступ)")
                if err:
                    lines.append(f"  Ошибка загрузки: {err}")
                lines.append("")
                continue

            lines.extend(_format_channel_settings_lines(entry, indent="  "))

            allowed, next_at = self.ctx.state.can_comment(key, entry.freeze_time)
            freeze_label = _format_freeze(entry)

            if allowed:
                lines.append(f"  {LBL_FREEZE} ({freeze_label}): ✅ готов к комменту")
                unfreeze_raw = self.ctx.state.unfreeze_at.get(key)
                if unfreeze_raw:
                    unfreeze = datetime.fromisoformat(unfreeze_raw)
                    if unfreeze.tzinfo is None:
                        unfreeze = unfreeze.replace(tzinfo=timezone.utc)
                    since = datetime.now(timezone.utc) - unfreeze
                    lines.append(
                        f"  После заморозки: {_format_timedelta(since)}, "
                        f"пропущено постов (не подошли): "
                        f"{self.ctx.state.rejected_since_unfreeze.get(key, 0)}"
                    )
                skip = self.ctx.state.skip_below_post_id.get(key)
                if skip:
                    lines.append(
                        f"  Мониторинг с поста #{skip + 1} "
                        f"(ниже #{skip} — во время заморозки)"
                    )
            else:
                left = next_at - datetime.now(tz=next_at.tzinfo)
                lines.append(
                    f"  {LBL_FREEZE} ({freeze_label}): ⏸ {_format_timedelta(left)} "
                    f"(до {next_at.astimezone().strftime('%d.%m.%Y %H:%M')})"
                )
                lines.append("  Канал не мониторится до конца заморозки")

            last_commented = self.ctx.state.last_commented_post_id.get(key)
            if last_commented:
                lines.append(f"  Последний комментарий к посту #{last_commented}")

            commented = len(self.ctx.state.commented_posts.get(key, []))
            rejected = len(self.ctx.state.rejected_posts.get(key, []))
            lines.append(
                f"  Всего: {commented} коммент., {rejected} отклон. навсегда"
            )

            if self.ctx.check_access:
                access = await self.ctx.check_access(ch)
                if access == "ok":
                    lines.append("  Доступ: ✅ можно писать")
                else:
                    lines.append(f"  Доступ: ⚠ {access}")

            if allowed:
                pending = await self.ctx.scan_pending(ch)
                if pending:
                    lines.append(f"  В очереди ({len(pending)}):")
                    for item in pending[:3]:
                        lines.append(
                            f"    • #{item.post_id}: {item.reason} "
                            f"(~{item.ticks_left} тик.)"
                        )
                    if len(pending) > 3:
                        lines.append(f"    … ещё {len(pending) - 3}")

            lines.append("")

        return "\n".join(lines).rstrip()

    def _cmd_channels_status(self) -> str:
        return "Используйте «статус каналов»"
