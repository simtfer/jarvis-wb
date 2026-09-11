"""贾维斯的大脑：把「提供商(LLM) + 记忆 + 本地工具」组装成一个完整的 Agent Loop。

一次 think() 的流程：
    用户输入 → 流式请求模型
        ├─ 模型只是说话 → 文本流给界面，写入记忆，结束
        └─ 模型要调工具 → 本地执行 → 结果回填消息链 → 再次请求模型
                          （最多 max_tool_rounds 轮，防止模型无限循环）
"""

from __future__ import annotations

from typing import Any, Callable

from ..config import settings
from ..providers import create_provider
from ..providers.base import (
    BaseProvider,
    Chunk,
    ProviderError,
    ToolCall,
    ToolCallsEvent,
)
from ..skills import invoke_tool, tool_hints, tool_specs
from .memory import ConversationMemory

# 回调：文本增量 / 工具执行完毕（调用本身 + 返回结果）
TextCallback = Callable[[str], None]
ToolCallback = Callable[[ToolCall, str], None]


class Brain:
    """封装一次对话所需的一切：模型调用、上下文维护、工具编排。"""

    def __init__(
        self,
        provider: BaseProvider | None = None,
        memory: ConversationMemory | None = None,
    ) -> None:
        cfg = settings.load()
        self.provider = provider or create_provider(cfg.provider, tool_hints=tool_hints())
        self.memory = memory or ConversationMemory()
        self.max_tool_rounds = cfg.max_tool_rounds
        self.tools_enabled = cfg.tools_enabled
        self.stream = cfg.stream

    # ---------- 主流程 ----------

    def think(
        self,
        user_text: str,
        on_text: TextCallback | None = None,
        on_tool: ToolCallback | None = None,
    ) -> str:
        """处理一句用户输入：流式产出文本、按需调用本地工具，返回最终回复。"""
        self.memory.add("user", user_text)
        tools = tool_specs() if self.tools_enabled else None

        text = ""
        calls: list[ToolCall] = []
        for _round in range(self.max_tool_rounds + 1):
            try:
                text, calls = self._run_once(tools, on_text)
            except ProviderError:
                self.memory.drop_last_turn()  # 失败时不留半截上下文
                raise

            if not calls:
                self.memory.add("assistant", text)
                return text

            # 模型要求调用工具：记录调用 → 本地执行 → 结果回填
            self.memory.add_assistant(text, tool_calls=calls)
            for call in calls:
                result = invoke_tool(call.name, call.arguments)
                self.memory.add_tool(call.id, call.name, result)
                if on_tool:
                    on_tool(call, result)

        notice = text or "抱歉先生，工具调用的层数已达上限。"
        self.memory.add("assistant", notice)
        return notice

    def _run_once(
        self, tools: list[dict[str, Any]] | None, on_text: TextCallback | None
    ) -> tuple[str, list[ToolCall]]:
        """跑一轮模型请求，收集文本与工具调用请求。"""
        buffer: list[str] = []
        calls: list[ToolCall] = []

        for event in self.provider.stream(self.memory.messages(), tools=tools):
            if isinstance(event, Chunk):
                buffer.append(event.text)
                if on_text and self.stream:
                    on_text(event.text)
            elif isinstance(event, ToolCallsEvent):
                calls.extend(event.calls)

        text = "".join(buffer).strip()
        if on_text and not self.stream and text:
            on_text(text)  # 非流式模式：一次性交给界面
        return text, calls

    # ---------- 记忆 ----------

    def remember(self, user_text: str, reply: str) -> None:
        """把一次本地技能（快速路径）的问答写入记忆，保持上下文连续。"""
        self.memory.add("user", user_text)
        self.memory.add("assistant", reply)

    def reset(self) -> None:
        self.memory.clear()

    def describe(self) -> dict[str, Any]:
        info = dict(self.provider.describe())
        info.update(
            {"tools": self.tools_enabled, "stream": self.stream, "memory": len(self.memory)}
        )
        return info
