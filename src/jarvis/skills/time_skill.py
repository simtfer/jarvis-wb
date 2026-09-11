"""示例技能：报时。展示如何编写一个贾维斯技能（无参数工具）。"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from .base import Skill

_WEEKDAY = ["周一", "周二", "周三", "周四", "周五", "周六", "周日"]


class TimeSkill(Skill):
    name = "get_time"
    description = "获取当前日期与时间。当用户询问现在几点、今天几号、星期几时使用。"
    keywords = ["几点", "时间", "日期", "星期", "time", "date"]
    patterns = [
        r"几点[了吗ni了]*",
        r"现在.{0,4}时间",
        r"今天.{0,3}(几号|日期|星期)",
        r"\btime\b",
    ]
    parameters: dict[str, Any] = {}
    required: list[str] = []

    def run(self, text: str = "", **kwargs: Any) -> str:
        now = datetime.now()
        return f"现在是 {now.strftime('%Y-%m-%d %H:%M:%S')}，{_WEEKDAY[now.weekday()]}。"
