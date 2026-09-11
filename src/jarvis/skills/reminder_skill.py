"""日程提醒技能：让贾维斯能设提醒、查日程、删提醒。"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from ..scheduler import get_store, parse_when
from .base import Skill

_FMT = "%m-%d %H:%M"


class AddReminderSkill(Skill):
    name = "add_reminder"
    description = (
        "设置一个提醒/日程，到点会主动通知用户。"
        "when 支持相对时间（10分钟后、2小时后、3天后）与绝对时间（明天9点、下午3点半、2026-12-01 09:00）。"
    )
    keywords = ["提醒", "日程", "别忘", "到点", "remind"]
    patterns: list[str] = []
    parameters: dict[str, Any] = {
        "content": {"type": "string", "description": "提醒内容，如：喝水 / 参加周会"},
        "when": {"type": "string", "description": "什么时候提醒，如：10分钟后 / 明天9点 / 2026-12-01 09:00"},
    }
    required = ["content", "when"]

    def run(self, text: str = "", content: str = "", when: str = "", **kwargs: Any) -> str:
        body = (content or text or "").strip()
        if not body:
            return "要提醒什么内容呢，先生？"
        try:
            due = parse_when(when or text)
        except ValueError as e:
            return f"设不了提醒：{e}"
        if due <= datetime.now():
            return "这个时间已经过去了，先生。"
        item = get_store().add(content, due)
        return f"好的，{item.due.strftime(_FMT)} 我会提醒您：{item.text}（#{item.id[:8]}）"


class ListRemindersSkill(Skill):
    name = "list_reminders"
    description = "查看当前所有未到期的提醒/日程安排。"
    keywords = ["安排", "日程", "有哪些提醒"]
    patterns: list[str] = []
    parameters: dict[str, Any] = {}
    required: list[str] = []

    def run(self, text: str = "", **kwargs: Any) -> str:
        items = get_store().pending()
        if not items:
            return "目前没有任何日程安排，先生。"
        lines = [f"[#{i.id[:8]}] {i.due.strftime(_FMT)} —— {i.text}" for i in items]
        return "接下来的安排：\n" + "\n".join(lines)


class RemoveReminderSkill(Skill):
    name = "remove_reminder"
    description = "按编号前缀或内容关键词取消一个提醒。仅在用户明确要求取消时使用。"
    keywords = ["取消提醒", "删掉提醒"]
    patterns: list[str] = []
    parameters: dict[str, Any] = {
        "ident": {"type": "string", "description": "提醒编号前缀或内容关键词"}
    }
    required = ["ident"]

    def run(self, text: str = "", ident: str = "", **kwargs: Any) -> str:
        removed = get_store().remove(ident or text)
        if not removed:
            return f"没有匹配「{ident}」的提醒，先生。"
        return f"已取消 {removed} 个提醒。"
