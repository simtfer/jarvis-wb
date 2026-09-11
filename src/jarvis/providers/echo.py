"""离线演示提供商：不需要 API Key，用于框架开发与测试。

虽然是"回声"，但为了能在离线状态下完整验证**流式输出**与**工具调用**链路，
它会：
  1. 逐字吐出文本（模拟流式生成）；
  2. 当用户话里命中某个工具的关键词时，真的发起一次工具调用；
  3. 拿到工具结果后，把结果组织成一句自然语言回复。
"""

from __future__ import annotations

import ast
import random
import re
import time
from typing import Any, Iterator

from .base import (
    AssistantTurn,
    BaseProvider,
    Chunk,
    Message,
    ToolCall,
    ToolCallsEvent,
    ToolSpec,
)

_REPLIES = [
    "收到，先生。目前我运行在离线演示模式，接入真实 LLM 后即可满血服役。",
    "在线待命中，先生。配置 .env 中的 JARVIS_PROVIDER=openai_compat 即可唤醒我的大脑。",
    "明白。框架运行正常——只是暂时借用了回声模式在说话。",
    "已记录，先生。等您为我接上 API Key，我的词汇量就不止这几句了。",
]

# 从文本里抠出一个数学表达式（给 calculate 工具演示用）
_CANDIDATE_RE = re.compile(r"[A-Za-z0-9_(][A-Za-z0-9_\s.+\-*/%(),]*")
_MATH_RE = re.compile(r"[0-9][0-9\s.+\-*/()%]*[0-9)]|[0-9]")


def _is_expression(candidate: str) -> bool:
    try:
        ast.parse(candidate, mode="eval")
    except SyntaxError:
        return False
    return True


def _best_expression(text: str) -> str:
    """从整句话里剥出最像数学表达式的片段（先右裁、再左裁，直到能解析）。"""
    for match in _CANDIDATE_RE.finditer(text):
        candidate = match.group(0).strip()
        probe = candidate
        while probe:
            if _is_expression(probe):
                return probe
            probe = probe[:-1].strip()
        probe = candidate
        while probe:
            if _is_expression(probe):
                return probe
            probe = probe[1:].strip()
    return text.strip()


class EchoProvider(BaseProvider):
    """固定话术回声，保证无网络/无密钥时框架依然可跑通。"""

    name = "echo"

    def __init__(
        self,
        api_key: str | None = None,
        base_url: str | None = None,
        model: str | None = None,
        tool_hints: dict[str, list[str]] | None = None,
        request_timeout: float | None = None,
        delay: float = 0.015,
    ) -> None:
        super().__init__(tool_hints=tool_hints, request_timeout=request_timeout)
        self.delay = delay

    # ---------- 内部：组装本轮回复 ----------

    def _compose(self, messages: list[Message], tools: list[ToolSpec] | None) -> AssistantTurn:
        last = messages[-1] if messages else {}

        # 刚拿到工具结果 → 把结果说成人话
        if last.get("role") == "tool":
            name = last.get("name", "本地技能")
            content = (last.get("content") or "").strip()
            return AssistantTurn(text=f"根据{name}的结果——{content}")

        # 只看最近一条用户消息——拼接历史会把上一轮的问题混进本轮
        user_text = next(
            (m.get("content") or "" for m in reversed(messages) if m.get("role") == "user"), ""
        )
        if not user_text.strip():
            return AssistantTurn(text="先生，您好像什么都没说。")

        call = self._pick_tool(user_text, tools)
        if call is not None:
            return AssistantTurn(text="稍等，先生，我调用一下本地技能。", tool_calls=[call])
        return AssistantTurn(text=random.choice(_REPLIES))

    def _pick_tool(self, text: str, tools: list[ToolSpec] | None) -> ToolCall | None:
        """离线演示：命中关键词就假装是模型决定调用工具。"""
        for spec in tools or []:
            fn = spec.get("function") or {}
            name = fn.get("name", "")
            hints = self.tool_hints.get(name, [])
            if name and hints and any(h.lower() in text.lower() for h in hints):
                return ToolCall(
                    id=f"call_{name}",
                    name=name,
                    arguments=self._guess_arguments(fn, text),
                    raw_arguments="",
                )
        return None

    @staticmethod
    def _guess_arguments(fn: dict[str, Any], text: str) -> dict[str, Any]:
        """按参数名做点简单的启发式填参，够演示工具调用即可。"""
        props = ((fn.get("parameters") or {}).get("properties")) or {}
        args: dict[str, Any] = {}
        for key, schema in props.items():
            lower = key.lower()
            if schema.get("type") == "array":
                args[key] = []
            elif "expr" in lower or schema.get("type") == "number":
                m = _MATH_RE.search(text)
                args[key] = _best_expression(text) if m else text
            elif lower in ("query", "text", "question", "keyword", "name", "topic"):
                args[key] = text
            else:
                args[key] = text
        return args

    # ---------- 接口实现 ----------

    def complete(self, messages: list[Message], tools: list[ToolSpec] | None = None) -> AssistantTurn:
        time.sleep(0.15)  # 模拟一点思考延迟，让 TUI 体验接近真实
        return self._compose(messages, tools)

    def stream(
        self, messages: list[Message], tools: list[ToolSpec] | None = None
    ) -> Iterator[Chunk | ToolCallsEvent]:
        turn = self._compose(messages, tools)
        for piece in self._split(turn.text):
            if self.delay:
                time.sleep(self.delay)
            yield Chunk(piece)
        if turn.tool_calls:
            yield ToolCallsEvent(turn.tool_calls)

    @staticmethod
    def _split(text: str, size: int = 2) -> Iterator[str]:
        for i in range(0, len(text), size):
            yield text[i : i + size]

    def describe(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "model": "echo（离线演示）",
            "streaming": True,
            "tools": True,
        }
