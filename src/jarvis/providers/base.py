"""LLM 提供商抽象基类。

所有大脑（LLM）后端都实现同一个接口，主程序不关心具体是哪家模型。
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any

Message = dict[str, str]  # {"role": "system"|"user"|"assistant", "content": str}


class ProviderError(RuntimeError):
    """提供商调用失败。"""


class BaseProvider(ABC):
    """对话提供商接口。"""

    name: str = "base"

    @abstractmethod
    def chat(self, messages: list[Message]) -> str:
        """输入完整消息历史，返回助手的回复文本。"""

    def health_check(self) -> bool:
        """可选的健康检查，默认认为可用。"""
        return True

    def describe(self) -> dict[str, Any]:
        return {"name": self.name}
