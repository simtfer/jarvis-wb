"""示例技能：报时。展示如何编写一个贾维斯技能。"""

from __future__ import annotations

import re
from datetime import datetime

from .base import Skill


class TimeSkill(Skill):
    name = "time"
    description = "报出当前时间（'几点' / 'time' 触发）"
    patterns = [r"几点[了吗ni了]*", r"现在.{0,4}时间", r"\btime\b"]

    def run(self, text: str, match: re.Match) -> str:
        now = datetime.now()
        return f"现在是 {now.strftime('%Y-%m-%d %H:%M:%S')}，{now.strftime('%A')}。"
