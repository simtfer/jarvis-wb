"""贾维斯的大脑：把 提供商(LLM) + 记忆 组合成可对话的整体。"""

from __future__ import annotations

from ..config import settings
from ..providers import create_provider
from ..providers.base import BaseProvider, ProviderError
from .memory import ConversationMemory


class Brain:
    """封装一次对话所需的一切：模型调用、上下文维护。"""

    def __init__(self, provider: BaseProvider | None = None) -> None:
        cfg = settings.load()
        self.provider = provider or create_provider(cfg.provider)
        self.memory = ConversationMemory()

    def think(self, user_text: str) -> str:
        """处理一句用户输入，返回回复并写入记忆。"""
        self.memory.add("user", user_text)
        try:
            reply = self.provider.chat(self.memory.messages())
        except ProviderError:
            # 失败时撤回这条 user 消息，避免污染上下文
            self._pop_user()
            raise
        self.memory.add("assistant", reply)
        return reply

    def _pop_user(self) -> None:
        if self.memory and getattr(self.memory, "_history", []):
            if self.memory._history[-1]["role"] == "user":
                self.memory._history.pop()

    def reset(self) -> None:
        self.memory.clear()
