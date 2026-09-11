"""技能基类：贾维斯的一切本地能力都继承它。

一个技能有两条触发路径，两条最终都走同一个 run()：
  1. **正则快速路径**：patterns 命中 → 直接执行，零延迟（TUI 本地优先）；
  2. **LLM 工具调用**：tool_spec() 把技能描述成 OpenAI 风格 function，
     模型决定调用时由 invoke(args) 填参执行。

所以：想加能力，只要继承 Skill、写清楚 description/parameters/patterns，再实现 run()。
"""

from __future__ import annotations

import re
from abc import ABC, abstractmethod
from typing import Any


class Skill(ABC):
    """本地技能接口。"""

    name: str = "skill"
    description: str = ""
    # 命中规则（正则，忽略大小写）——快速路径
    patterns: list[str] = []
    # 触发关键词：供离线演示提供商猜工具，也起到文档作用
    keywords: list[str] = []
    # JSON Schema properties，描述工具参数
    parameters: dict[str, Any] = {}
    required: list[str] = []

    # ---------- 工具化 ----------

    def tool_spec(self) -> dict[str, Any]:
        """转成 OpenAI 风格 function 描述，交给模型挑选。"""
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": {
                    "type": "object",
                    "properties": self.parameters,
                    "required": self.required,
                },
            },
        }

    def invoke(self, args: dict[str, Any] | None) -> str:
        """工具调用入口：把模型给的 JSON 参数摊平成 run() 的 kwargs。"""
        data = dict(args or {})
        text = str(data.pop("text", "") or "")
        return self.run(text, **data)

    # ---------- 快速路径 ----------

    def match(self, text: str) -> re.Match | None:
        for pattern in self.patterns:
            m = re.search(pattern, text, re.IGNORECASE)
            if m:
                return m
        return None

    @abstractmethod
    def run(self, text: str = "", **kwargs: Any) -> str:
        """执行技能，返回给用户看的文本结果。"""
