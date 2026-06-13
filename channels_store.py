"""Загрузка и сохранение channels.json."""

from __future__ import annotations

import json
import re
from copy import deepcopy
from dataclasses import dataclass, field
from datetime import timedelta
from pathlib import Path
from typing import Any

import neuro_config as cfg

CHANNEL_LINK_RE = re.compile(r"t\.me/([A-Za-z0-9_]+)", re.IGNORECASE)
ADD_CMD_RE = re.compile(
    r"^(?:добавить|add)\s+",
    re.IGNORECASE,
)
# ссылка ... - ... id (гибко: «- .», «|», «-»)
ADD_LINE_RE = re.compile(
    r"^(?P<link>https?://t\.me/\S+|@[\w]+|\w+)\s*"
    r"(?:[-–|]\s*\.?\s*)+"
    r"(?P<gid>-?\d+)\s*$",
    re.IGNORECASE,
)


def _defaults() -> dict[str, Any]:
    return {
        "enabled": True,
        "freeze_days": cfg.GLOBAL_COOLDOWN.total_seconds() / 86400,
        "post_min_age_minutes": int(cfg.POST_MIN_AGE.total_seconds() // 60),
        "post_activity_window_minutes": int(cfg.POST_ACTIVITY_WINDOW.total_seconds() // 60),
        "min_comments": cfg.MIN_COMMENTS_UNDER_POST,
        "min_subscribers": cfg.MIN_CHANNEL_SUBSCRIBERS,
        "posts_scan_limit": cfg.POSTS_SCAN_LIMIT,
    }


@dataclass
class ChannelEntry:
    entry_id: str
    channel_link: str
    group_id: int
    enabled: bool = True
    freeze_days: float = 7.0
    post_min_age_minutes: int = 30
    post_activity_window_minutes: int = 30
    min_comments: int = 3
    min_subscribers: int = 20_000
    posts_scan_limit: int = 30

    @property
    def username(self) -> str | None:
        return username_from_link(self.channel_link)

    @property
    def freeze_time(self) -> timedelta:
        return timedelta(days=self.freeze_days)

    @property
    def post_min_age(self) -> timedelta:
        return timedelta(minutes=self.post_min_age_minutes)

    @property
    def post_activity_window(self) -> timedelta:
        return timedelta(minutes=self.post_activity_window_minutes)

    def to_dict(self) -> dict[str, Any]:
        return {
            "channel_link": self.channel_link,
            "group_id": self.group_id,
            "enabled": self.enabled,
            "freeze_days": self.freeze_days,
            "post_min_age_minutes": self.post_min_age_minutes,
            "post_activity_window_minutes": self.post_activity_window_minutes,
            "min_comments": self.min_comments,
            "min_subscribers": self.min_subscribers,
            "posts_scan_limit": self.posts_scan_limit,
        }

    @classmethod
    def from_dict(cls, entry_id: str, data: dict[str, Any]) -> ChannelEntry | None:
        link = data.get("channel_link") or data.get("chanel_link")
        group_id = data.get("group_id")
        if not link or group_id is None:
            return None
        defaults = _defaults()
        return cls(
            entry_id=entry_id,
            channel_link=str(link).strip(),
            group_id=int(group_id),
            enabled=bool(data.get("enabled", defaults["enabled"])),
            freeze_days=float(data.get("freeze_days", data.get("freeze_time_days", defaults["freeze_days"]))),
            post_min_age_minutes=int(data.get("post_min_age_minutes", defaults["post_min_age_minutes"])),
            post_activity_window_minutes=int(
                data.get("post_activity_window_minutes", defaults["post_activity_window_minutes"])
            ),
            min_comments=int(data.get("min_comments", defaults["min_comments"])),
            min_subscribers=int(data.get("min_subscribers", defaults["min_subscribers"])),
            posts_scan_limit=int(data.get("posts_scan_limit", defaults["posts_scan_limit"])),
        )


def username_from_link(ref: str) -> str | None:
    ref = ref.strip()
    match = CHANNEL_LINK_RE.search(ref)
    if match:
        return match.group(1)
    token = ref.lstrip("@").split()[0]
    return token or None


def normalize_link(ref: str) -> str:
    ref = ref.strip()
    user = username_from_link(ref)
    if user:
        return f"https://t.me/{user}"
    return ref


def _migrate_legacy(raw: dict[str, Any]) -> dict[str, Any]:
    """Старый формат {"1": "https://t.me/..."} → новый."""
    if "channels" in raw:
        return raw
    channels: dict[str, Any] = {}
    defaults = _defaults()
    for key in sorted(raw.keys(), key=lambda k: int(k) if str(k).isdigit() else k):
        val = raw[key]
        if isinstance(val, str):
            channels[key] = {
                "channel_link": normalize_link(val),
                "group_id": 0,
                **{k: v for k, v in defaults.items() if k != "enabled"},
                "enabled": True,
            }
        elif isinstance(val, dict):
            channels[key] = val
    return {"channels": channels}


def load_store(path: Path | None = None) -> dict[str, ChannelEntry]:
    path = path or cfg.CHANNELS_FILE
    if not path.exists():
        return {}
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {}
    if not isinstance(raw, dict):
        return {}

    raw = _migrate_legacy(raw)
    result: dict[str, ChannelEntry] = {}
    for entry_id, data in raw.get("channels", {}).items():
        if not isinstance(data, dict):
            continue
        entry = ChannelEntry.from_dict(str(entry_id), data)
        if entry and entry.username:
            result[str(entry_id)] = entry
    return result


def save_store(entries: dict[str, ChannelEntry], path: Path | None = None) -> None:
    path = path or cfg.CHANNELS_FILE
    payload = {
        "channels": {
            eid: entry.to_dict() for eid, entry in sorted(entries.items(), key=lambda x: int(x[0]) if x[0].isdigit() else x[0])
        }
    }
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def next_entry_id(entries: dict[str, ChannelEntry]) -> str:
    nums = [int(k) for k in entries if str(k).isdigit()]
    return str(max(nums, default=0) + 1)


def parse_add_channel(text: str) -> tuple[str, int] | None:
    """Парсит добавление: «https://t.me/foo - . -3511597340» или «add @foo -123»."""
    text = (text or "").strip()
    if ADD_CMD_RE.match(text):
        text = ADD_CMD_RE.sub("", text).strip()

    m = ADD_LINE_RE.match(text)
    if m:
        return normalize_link(m.group("link")), int(m.group("gid"))

    parts = re.split(r"\s*[-–|]\s*", text)
    if len(parts) >= 2:
        link_part = parts[0].strip()
        for part in reversed(parts[1:]):
            num = re.search(r"-?\d+", part.replace(" ", ""))
            if num and username_from_link(link_part):
                return normalize_link(link_part), int(num.group())

    return None


def add_channel_entry(
    link: str,
    group_id: int,
    *,
    entries: dict[str, ChannelEntry] | None = None,
) -> ChannelEntry:
    store = entries if entries is not None else load_store()
    link = normalize_link(link)
    user = username_from_link(link)
    if not user:
        raise ValueError("Не удалось распознать ссылку на канал")

    for entry in store.values():
        if entry.username and entry.username.lower() == user.lower():
            raise ValueError(f"Канал @{user} уже в списке (id {entry.entry_id})")

    defaults = _defaults()
    eid = next_entry_id(store)
    entry = ChannelEntry(
        entry_id=eid,
        channel_link=link,
        group_id=int(group_id),
        enabled=True,
        freeze_days=float(defaults["freeze_days"]),
        post_min_age_minutes=int(defaults["post_min_age_minutes"]),
        post_activity_window_minutes=int(defaults["post_activity_window_minutes"]),
        min_comments=int(defaults["min_comments"]),
        min_subscribers=int(defaults["min_subscribers"]),
        posts_scan_limit=int(defaults["posts_scan_limit"]),
    )
    store[eid] = entry
    save_store(store)
    return entry
