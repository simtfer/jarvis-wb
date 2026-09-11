"""会话记忆：维护带系统提示词的对话历史，自动裁剪旧轮次。"""

from __future__ import annotations

from ..config import settings
from ..providers.base import Message


class ConversationMemory:
    """短期记忆。max_turns 控制保留的用户/助手轮数。"""

    def __init__(self, system_prompt: str | None = None, max_turns: int | None = None) -> None:
        self.system_prompt = system_prompt or settings.load().system_prompt
        self.max_turns = max_turns or settings.max_turns
        self._history: list[Message] = []

    def add(self, role: str, content: str) -> None:
        self._history.append({"role": role, "content": content})
        self._trim()

    def _trim(self) -> None:
        # 每轮 = 一条 user + 一条 assistant，裁掉最旧的整轮
        overflow = len([m for m in self._history if m["role"] == "user"]) - self.max_turns
        if overflow > 0:
            removed = 0
            kept: list[Message] = []
            for m in self._history:
                if m["role"] == "user" and removed < overflow:
                    removed += 1
                    continue
                if m["role"] == "assistant" and removed > 0:
                    continue  # 丢掉与之配对的回复
                kept.append(m)
            self._history = kept

    def messages(self) -> list[Message]:
        """返回可直接发给 LLM 的完整消息列表（含系统提示词）。"""
        return [{"role": "system", "content": self.system_prompt}, *self._history]

    def clear(self) -> None:
        self._history.clear()

    def __len__(self) -> int:
        return len(self._history)
