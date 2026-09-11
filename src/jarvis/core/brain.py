"""贾维斯的大脑：把「提供商(LLM) + 记忆 + 本地工具」组装成一个完整的 Agent Loop。

一次 think() 的流程：
    用户输入 → 流式请求模型
        ├─ 模型只是说话 → 文本流给界面，写入记忆，结束
        └─ 模型要调工具 → 本地执行 → 结果回填消息链 → 再次请求模型
                          （最多 max_tool_rounds 轮，防止模型无限循环）

防卡死设计：
  - 同一轮里 (工具名 + 参数) 重复出现时直接熔断，不再重复执行、也不再请求模型；
  - 工具返回"拒绝/不可用"类结果时，写进记忆的文本会附上"不要重试"的提示，
    避免真实模型被拒绝后反复重试同一个工具，把一次对话拖成好几轮请求；
  - 通过 on_status 把"第 N 轮"进度抛给界面，任何等待都不再是黑盒。
"""

from __future__ import annotations

import json
from typing import Any, Callable

from ..config import settings
from ..ltm import get_ltm
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

# 回调：文本增量 / 工具执行完毕（调用本身 + 返回结果）/ 进度状态
TextCallback = Callable[[str], None]
ToolCallback = Callable[[ToolCall, str], None]
StatusCallback = Callable[[str], None]

# 工具结果是"拒绝/不可用"类的标志词——命中就给记忆补一句"别重试"
_REFUSAL_MARKERS = (
    "默认关闭",
    "不在白名单",
    "危险黑名单",
    "拒绝执行",
    "没有名为",
    "执行失败：",
    "请告诉我要执行什么",
)
_NO_RETRY_HINT = "（该工具本次不可用或已被拒绝，不要重复调用它，请直接用现有信息回答用户。）"


def _looks_refused(result: str) -> bool:
    return any(marker in result for marker in _REFUSAL_MARKERS)


def _with_retry_guard(result: str) -> str:
    """写给模型看的版本：拒绝类结果额外附上"不要重试"。"""
    return result + "\n" + _NO_RETRY_HINT if _looks_refused(result) else result


def _call_key(call: ToolCall) -> str:
    """工具调用的指纹：同名同参视为同一次调用。"""
    try:
        args = json.dumps(call.arguments, sort_keys=True, ensure_ascii=False, default=str)
    except (TypeError, ValueError):
        args = repr(call.arguments)
    return f"{call.name}|{args}"


class Brain:
    """封装一次对话所需的一切：模型调用、上下文维护、工具编排。"""

    def __init__(
        self,
        provider: BaseProvider | None = None,
        memory: ConversationMemory | None = None,
    ) -> None:
        cfg = settings.load()
        self.provider = provider or create_provider(
            cfg.provider,
            tool_hints=tool_hints(),
            request_timeout=cfg.request_timeout,
        )
        self.memory = memory or ConversationMemory()
        self.max_tool_rounds = cfg.max_tool_rounds
        self.tools_enabled = cfg.tools_enabled
        self.stream = cfg.stream
        self.ltm = get_ltm()
        self.auto_recall = cfg.auto_recall
        self.recall_top_k = cfg.recall_top_k
        # 每轮 think() 开头计算一次，供本轮所有模型请求复用
        self._recall_suffix = ""

    # ---------- 主流程 ----------

    def think(
        self,
        user_text: str,
        on_text: TextCallback | None = None,
        on_tool: ToolCallback | None = None,
        on_status: StatusCallback | None = None,
    ) -> str:
        """处理一句用户输入：流式产出文本、按需调用本地工具，返回最终回复。"""
        self.memory.add("user", user_text)
        tools = tool_specs() if self.tools_enabled else None
        self._recall_suffix = self._build_recall_suffix(user_text)

        text = ""
        calls: list[ToolCall] = []
        executed: dict[str, str] = {}  # 本轮已执行过的调用指纹 → 结果

        for round_no in range(1, self.max_tool_rounds + 2):
            if on_status:
                on_status(f"第 {round_no} 轮 · 等待模型响应…")
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

            # 熔断：同一轮里重复要同一个工具 + 同样参数 → 多半是死循环，直接收口
            repeated = next((c for c in calls if _call_key(c) in executed), None)
            if repeated is not None:
                answer = executed[_call_key(repeated)]
                for call in calls:
                    self.memory.add_tool(call.id, call.name, answer)
                self.memory.add("assistant", answer)
                if on_status:
                    on_status(f"检测到重复调用 {repeated.name}（同参数），已熔断：直接采用已有结果")
                if on_text and answer:
                    on_text(answer)  # 答案不走模型，直接交给界面
                return answer

            for call in calls:
                key = _call_key(call)
                if key in executed:  # 同一批次的多个调用里出现重复
                    result = executed[key]
                else:
                    result = invoke_tool(call.name, call.arguments)
                    executed[key] = result
                # 记忆里放"带禁重试提示"的版本，界面显示原始结果
                self.memory.add_tool(call.id, call.name, _with_retry_guard(result))
                if on_tool:
                    on_tool(call, result)

        notice = text or "抱歉先生，工具调用的层数已达上限。"
        self.memory.add("assistant", notice)
        return notice

    def _build_recall_suffix(self, user_text: str) -> str:
        """自动召回：把与本次输入相关的长期记忆注入 system prompt。"""
        if not self.auto_recall or not len(self.ltm):
            return ""
        hits = self.ltm.recall(user_text, limit=self.recall_top_k)
        if not hits:
            return ""
        lines = "\n".join(f"- {item.text}" for item, _ in hits)
        return f"\n\n[长期记忆参考]\n{lines}"

    def _run_once(
        self, tools: list[dict[str, Any]] | None, on_text: TextCallback | None
    ) -> tuple[str, list[ToolCall]]:
        """跑一轮模型请求，收集文本与工具调用请求。"""
        buffer: list[str] = []
        calls: list[ToolCall] = []

        messages = self.memory.messages()
        if self._recall_suffix:
            # 只改本轮请求里的 system 消息，不写入记忆
            messages[0] = {**messages[0], "content": messages[0]["content"] + self._recall_suffix}

        for event in self.provider.stream(messages, tools=tools):
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
