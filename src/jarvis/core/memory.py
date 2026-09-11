"""会话记忆：按"轮"存储的对话历史，自动裁剪旧轮次。

为什么按轮而不是按条存：工具调用会产生 assistant(tool_calls) → tool → assistant
这样的消息链，如果按条裁剪，很容易把 tool 结果和它的调用请求拆散，
发给 LLM 时会直接报错（孤立的 tool 消息）。按轮裁剪天然保证链的完整性。
"""

from __future__ import annotations

from typing import Any

from ..config import settings
from ..providers.base import Message

Turn = list[Message]


class ConversationMemory:
    """短期记忆。max_turns 控制保留的完整对话轮数（1 轮 = 1 次用户输入及其后续）。"""

    def __init__(self, system_prompt: str | None = None, max_turns: int | None = None) -> None:
        self.system_prompt = system_prompt or settings.load().system_prompt
        self.max_turns = max_turns or settings.max_turns
        self._turns: list[Turn] = []

    # ---------- 写入 ----------

    def add(self, role: str, content: str) -> None:
        """通用入口：user 会开启新一轮，其他角色追加到当前轮。"""
        if role == "user":
            self._turns.append([{"role": "user", "content": content}])
            self._trim()
        else:
            self._append({"role": role, "content": content})

    def add_assistant(self, content: str = "", tool_calls: list[Any] | None = None) -> None:
        """助手消息，可携带工具调用请求。"""
        message: Message = {"role": "assistant", "content": content}
        if tool_calls:
            message["tool_calls"] = [
                call.to_openai() if hasattr(call, "to_openai") else call for call in tool_calls
            ]
        self._append(message)

    def add_tool(self, tool_call_id: str, name: str, content: str) -> None:
        """工具执行结果，必须紧跟对应的 assistant.tool_calls。"""
        self._append(
            {"role": "tool", "tool_call_id": tool_call_id, "name": name, "content": content}
        )

    def _append(self, message: Message) -> None:
        if not self._turns:
            self._turns.append([])
        self._turns[-1].append(message)
        self._trim()

    # ---------- 读取 ----------

    def messages(self) -> list[Message]:
        """返回可直接发给 LLM 的完整消息列表（含系统提示词）。"""
        flat: list[Message] = []
        for turn in self._turns:
            flat.extend(turn)
        return [{"role": "system", "content": self.system_prompt}, *flat]

    def last_role(self) -> str | None:
        if not self._turns or not self._turns[-1]:
            return None
        return self._turns[-1][-1].get("role")

    # ---------- 维护 ----------

    def _trim(self) -> None:
        while len(self._turns) > self.max_turns:
            self._turns.pop(0)

    def drop_last_turn(self) -> None:
        """回滚最近一轮（用于调用失败时保持上下文干净）。"""
        if self._turns:
            self._turns.pop()

    def clear(self) -> None:
        self._turns.clear()

    def __len__(self) -> int:
        return sum(len(turn) for turn in self._turns)
