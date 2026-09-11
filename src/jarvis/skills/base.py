"""技能基类：贾维斯的一切本地点能（时间、系统控制、日程……）都继承它。"""

from __future__ import annotations

import re
from abc import ABC, abstractmethod


class Skill(ABC):
    """本地技能接口。

    子类只需定义 name / description / patterns 并实现 run()。
    patterns 是正则列表，命中任意一条即触发本技能（优先于 LLM）。
    """

    name: str = "skill"
    description: str = ""
    # 命中规则（正则，忽略大小写）
    patterns: list[str] = []

    def match(self, text: str) -> re.Match | None:
        for p in self.patterns:
            m = re.search(p, text, re.IGNORECASE)
            if m:
                return m
        return None

    @abstractmethod
    def run(self, text: str, match: re.Match) -> str:
        """执行技能，返回给用户看的文本结果。"""
