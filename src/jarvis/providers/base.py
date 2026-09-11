"""LLM 提供商抽象基类。

所有大脑（LLM）后端都实现同一套接口，主程序不关心具体是哪家模型：
  - complete()  一次拿到完整回复（含工具调用请求）
  - chat()      便捷方法，只要文本
  - stream()    流式产出事件（文本增量 / 工具调用请求）

流式事件模型（stream 的产出）：
  Chunk(text)          —— 文本增量，边生成边吐
  ToolCallsEvent(calls) —— 本轮模型要求调用工具（流结束时一次性给出）
"""

from __future__ import annotations

import json
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, Iterator, Union

# 消息可以是普通对话消息，也可以带 tool_calls / tool_call_id
Message = dict[str, Any]

ToolSpec = dict[str, Any]  # OpenAI 风格工具描述 {"type": "function", "function": {...}}


class ProviderError(RuntimeError):
    """提供商调用失败。"""


@dataclass
class ToolCall:
    """模型发起的一次工具调用。"""

    id: str
    name: str
    arguments: dict[str, Any] = field(default_factory=dict)
    raw_arguments: str = ""

    def to_openai(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "type": "function",
            "function": {"name": self.name, "arguments": self.raw_arguments or json.dumps(self.arguments, ensure_ascii=False)},
        }


@dataclass
class AssistantTurn:
    """非流式的一次助手回复。"""

    text: str = ""
    tool_calls: list[ToolCall] = field(default_factory=list)


@dataclass
class Chunk:
    """文本增量。"""

    text: str


@dataclass
class ToolCallsEvent:
    """模型要求调用工具（一轮流式结束时给出）。"""

    calls: list[ToolCall]


StreamEvent = Union[Chunk, ToolCallsEvent]


class BaseProvider(ABC):
    """对话提供商接口。"""

    name: str = "base"

    def __init__(
        self,
        api_key: str | None = None,
        base_url: str | None = None,
        model: str | None = None,
        tool_hints: dict[str, list[str]] | None = None,
        request_timeout: float | None = None,
    ) -> None:
        # tool_hints 只有离线演示提供商（echo）会用到：{工具名: [触发关键词]}
        self.tool_hints = tool_hints or {}
        # 单次请求超时（秒）；None 表示由具体提供商决定（一般是配置里的默认值）
        self.request_timeout = request_timeout

    @abstractmethod
    def complete(self, messages: list[Message], tools: list[ToolSpec] | None = None) -> AssistantTurn:
        """输入完整消息历史，返回助手回复（可能包含工具调用请求）。"""

    def chat(self, messages: list[Message], tools: list[ToolSpec] | None = None) -> str:
        """只要文本的便捷入口。"""
        return self.complete(messages, tools).text

    def stream(
        self, messages: list[Message], tools: list[ToolSpec] | None = None
    ) -> Iterator[StreamEvent]:
        """流式产出事件。默认降级实现：一次性吐出完整回复。"""
        turn = self.complete(messages, tools)
        if turn.text:
            yield Chunk(turn.text)
        if turn.tool_calls:
            yield ToolCallsEvent(turn.tool_calls)

    # ---- 能力声明 ----
    def supports_streaming(self) -> bool:
        return type(self).stream is not BaseProvider.stream

    def supports_tools(self) -> bool:
        return True

    def health_check(self) -> bool:
        return True

    def describe(self) -> dict[str, Any]:
        return {"name": self.name}


def parse_arguments(raw: str) -> dict[str, Any]:
    """宽容地解析模型给出的参数 JSON。"""
    if not raw or not raw.strip():
        return {}
    try:
        data = json.loads(raw)
        return data if isinstance(data, dict) else {"value": data}
    except json.JSONDecodeError:
        return {}
