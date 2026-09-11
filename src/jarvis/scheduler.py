"""提醒调度：中文时间解析 + JSON 持久化 + 后台到点回调。

parse_when() 尽量"在句子里找时间"而不是全句匹配：
  "10分钟后提醒我喝水"  → 10 分钟后
  "明天9点开会"         → 明天 09:00
  "下午3点半"           → 今天 15:30（已过则顺延明天）
  "2026-12-01 09:00"    → 原样
"""

from __future__ import annotations

import json
import re
import threading
import uuid
from dataclasses import asdict, dataclass, field
from datetime import datetime, timedelta
from pathlib import Path
from typing import Callable

from .config import settings

_DAY_OFFSET = {"今天": 0, "明天": 1, "后天": 2, "大后天": 3}

_REL_RE = re.compile(r"(\d+(?:\.\d+)?)\s*(分钟|分|小时|钟头|天)(?:之|以)?后")
_ABS_DT_RE = re.compile(r"(\d{4})-(\d{1,2})-(\d{1,2})[ T](\d{1,2}):(\d{2})")
_DAY_RE = re.compile(
    r"(今天|明天|后天|大后天)?\s*(上午|下午|晚上|中午)?\s*(\d{1,2})[点:：时]\s*(?:(\d{1,2})\s*分|半)?"
)
_DAY_WORD_RE = re.compile(r"(今天|明天|后天|大后天)")


def _apply_half_day(base: datetime, period: str | None, hour: int) -> int:
    if period in ("下午", "晚上") and hour < 12:
        return hour + 12
    if period == "中午" and hour < 12:
        return 12
    return hour


def parse_when(text: str, now: datetime | None = None) -> datetime:
    """从一句话里解析出目标时间，解析失败抛 ValueError。"""
    now = now or datetime.now()
    text = (text or "").strip()
    if not text:
        raise ValueError("没有提供时间")

    # 1) ISO 绝对时间
    m = _ABS_DT_RE.search(text)
    if m:
        y, mo, d, h, mi = (int(g) for g in m.groups())
        return datetime(y, mo, d, h, mi)

    # 2) 相对时间：N 分钟/小时/天后
    m = _REL_RE.search(text)
    if m:
        value = float(m.group(1))
        unit = m.group(2)
        if unit in ("分钟", "分"):
            return now + timedelta(minutes=value)
        if unit in ("小时", "钟头"):
            return now + timedelta(hours=value)
        return now + timedelta(days=value)

    # 3) 今天/明天/后天 + 时刻（时刻可省略，默认 09:00；"3点半"也认）
    day_word_m = _DAY_WORD_RE.search(text)
    day_word = day_word_m.group(0) if day_word_m else None
    m = _DAY_RE.search(text)
    if m and m.group(3):
        offset = _DAY_OFFSET.get(m.group(1) or day_word or "今天", 0)
        hour = int(m.group(3))
        minute = int(m.group(4)) if m.group(4) else (30 if m.group(0).rstrip().endswith("半") else 0)
        hour = _apply_half_day(now, m.group(2), hour)
        candidate = (now + timedelta(days=offset)).replace(
            hour=hour, minute=minute, second=0, microsecond=0
        )
        # 没写"明天"只写了时刻，且已过 → 顺延到明天
        if not m.group(1) and not day_word and candidate <= now:
            candidate += timedelta(days=1)
        return candidate
    if day_word:
        return (now + timedelta(days=_DAY_OFFSET[day_word])).replace(
            hour=9, minute=0, second=0, microsecond=0
        )

    raise ValueError(f"无法识别时间：{text}（示例：10分钟后 / 明天9点 / 下午3点半 / 2026-12-01 09:00）")


@dataclass
class Reminder:
    id: str
    text: str
    due_at: str  # ISO
    created_at: str = ""
    done: bool = False

    @property
    def due(self) -> datetime:
        return datetime.fromisoformat(self.due_at)


class ReminderStore:
    """持久化提醒库，线程安全（TUI 主线程与后台线程并发访问）。"""

    def __init__(self, path: Path | None = None) -> None:
        self.path = Path(path or Path(settings.load().data_dir) / "reminders.json")
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()
        self._items: list[Reminder] = []
        self._load()

    def _load(self) -> None:
        if not self.path.exists():
            self._items = []
            return
        try:
            raw = json.loads(self.path.read_text(encoding="utf-8"))
            self._items = [Reminder(**entry) for entry in raw]
        except (json.JSONDecodeError, TypeError, KeyError):
            backup = self.path.with_suffix(".json.bak")
            if self.path.exists():
                self.path.replace(backup)
            self._items = []

    def _save(self) -> None:
        self.path.write_text(
            json.dumps([asdict(i) for i in self._items], ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

    def add(self, text: str, due_at: datetime) -> Reminder:
        with self._lock:
            item = Reminder(
                id=uuid.uuid4().hex,
                text=text.strip(),
                due_at=due_at.isoformat(timespec="seconds"),
                created_at=datetime.now().isoformat(timespec="seconds"),
            )
            self._items.append(item)
            self._save()
            return item

    def pending(self) -> list[Reminder]:
        with self._lock:
            return [i for i in self._items if not i.done]

    def all(self) -> list[Reminder]:
        with self._lock:
            return list(self._items)

    def due(self, now: datetime | None = None) -> list[Reminder]:
        """取走所有已到期未完成的提醒（标记 done），供后台线程消费。"""
        now = now or datetime.now()
        with self._lock:
            fired = [i for i in self._items if not i.done and i.due <= now]
            for item in fired:
                item.done = True
            if fired:
                self._save()
            return fired

    def remove(self, ident: str) -> int:
        ident = (ident or "").strip().lower()
        with self._lock:
            before = len(self._items)
            self._items = [
                i for i in self._items
                if not (i.id.lower().startswith(ident) or ident in i.text.lower())
            ]
            removed = before - len(self._items)
            if removed:
                self._save()
            return removed

    def __len__(self) -> int:
        return len(self._items)


# ---------- 后台线程 ----------

def start_reminder_worker(
    store: ReminderStore, notify: Callable[[str], None], interval: float = 20.0
) -> threading.Thread:
    """每 interval 秒扫一次到期提醒并回调 notify(f"提醒：{text}")。"""

    def _loop() -> None:
        while True:
            try:
                for item in store.due():
                    notify(f"提醒：{item.text}")
            except Exception:  # 后台线程绝不允许带着异常死掉
                pass
            threading.Event().wait(interval)

    thread = threading.Thread(target=_loop, name="jarvis-reminders", daemon=True)
    thread.start()
    return thread


# ---------- 进程级单例 ----------

_STORE: ReminderStore | None = None


def get_store() -> ReminderStore:
    global _STORE
    if _STORE is None:
        _STORE = ReminderStore()
    return _STORE


def reset_store() -> None:
    global _STORE
    _STORE = None
