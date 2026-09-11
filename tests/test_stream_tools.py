"""流式输出 + 工具调用（Agent Loop）测试，全部离线可跑。"""

import os
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

os.environ["JARVIS_PROVIDER"] = "echo"

from jarvis.core import Brain
from jarvis.core.memory import ConversationMemory
from jarvis.providers import create_provider
from jarvis.providers.base import (
    AssistantTurn,
    BaseProvider,
    Chunk,
    ToolCall,
    ToolCallsEvent,
)
from jarvis.skills import invoke_tool, tool_hints
from jarvis.skills.calc_skill import safe_eval


class ScriptedProvider(BaseProvider):
    """按剧本回话的假提供商：验证 Agent Loop 而不依赖网络。"""

    name = "scripted"

    def __init__(self, turns: list[AssistantTurn]) -> None:
        super().__init__()
        self.turns = list(turns)
        self.seen: list[list[dict]] = []

    def complete(self, messages, tools=None) -> AssistantTurn:
        self.seen.append([dict(m) for m in messages])
        return self.turns.pop(0) if self.turns else AssistantTurn(text="")

    def stream(self, messages, tools=None):
        turn = self.complete(messages, tools)
        for i in range(0, len(turn.text), 4):
            yield Chunk(turn.text[i : i + 4])
        if turn.tool_calls:
            yield ToolCallsEvent(turn.tool_calls)


# ---------- 流式 ----------

def test_echo_streams_in_multiple_chunks():
    echo = create_provider("echo", delay=0.0)
    chunks = [
        ev.text for ev in echo.stream([{"role": "user", "content": "你好"}]) if isinstance(ev, Chunk)
    ]
    assert len(chunks) > 3
    assert "".join(chunks).strip()


def test_non_stream_mode_emits_once():
    from jarvis.config import settings

    echo = create_provider("echo", delay=0.0)
    brain = Brain(provider=echo)
    brain.stream = False
    received: list[str] = []
    brain.think("你好", on_text=received.append)
    assert len(received) == 1  # 非流式：一次性给全文


# ---------- 工具调用 ----------

def test_agent_loop_executes_tool_then_answers():
    provider = ScriptedProvider(
        [
            AssistantTurn(
                text="稍等，先生。",
                tool_calls=[
                    ToolCall(
                        id="c1",
                        name="calculate",
                        arguments={"expression": "12*8"},
                        raw_arguments='{"expression": "12*8"}',
                    )
                ],
            ),
            AssistantTurn(text="答案是 96。"),
        ]
    )
    brain = Brain(provider=provider)
    chunks: list[str] = []
    tool_events: list[tuple[str, str]] = []

    reply = brain.think(
        "12*8 是多少", on_text=chunks.append, on_tool=lambda c, r: tool_events.append((c.name, r))
    )

    assert reply == "答案是 96。"
    assert tool_events and tool_events[0][0] == "calculate" and "96" in tool_events[0][1]
    assert "".join(chunks).count("答案是") == 1  # 两轮流式文本不会互相污染

    roles = [m["role"] for m in brain.memory.messages()]
    assert roles == ["system", "user", "assistant", "tool", "assistant"]
    msgs = brain.memory.messages()
    assert msgs[2]["tool_calls"][0]["function"]["name"] == "calculate"
    assert msgs[3]["tool_call_id"] == "c1"


def test_echo_provider_can_trigger_tool_offline():
    """离线演示模式也走完整的工具调用链路。"""
    echo = create_provider("echo", tool_hints=tool_hints(), delay=0.0)
    brain = Brain(provider=echo)
    seen: list[tuple[str, str]] = []

    reply = brain.think("帮我算一下 12*8 是多少", on_tool=lambda c, r: seen.append((c.name, r)))

    assert seen and seen[0][0] == "calculate"
    assert "96" in reply
    assert any(m["role"] == "tool" for m in brain.memory.messages())


def test_echo_arg_extraction_uses_latest_message_only():
    """回归：连续两问不能被历史问题污染参数。"""
    echo = create_provider("echo", tool_hints=tool_hints(), delay=0.0)
    brain = Brain(provider=echo)
    results: list[str] = []

    brain.think("算一下 12*8", on_tool=lambda c, r: results.append(r))
    brain.think("算一下 7+5", on_tool=lambda c, r: results.append(r))

    assert results[0].strip() == "12*8 = 96"
    assert results[1].strip() == "7+5 = 12"


def test_tool_round_limit_stops_loop():
    from jarvis.config import settings

    # 模型每轮都要调工具，必须被 max_tool_rounds 截断，不能无限循环
    provider = ScriptedProvider(
        [AssistantTurn(text="", tool_calls=[ToolCall(id=f"c{i}", name="get_time")]) for i in range(9)]
    )
    settings.load()
    original = settings.max_tool_rounds
    settings.max_tool_rounds = 2
    try:
        brain = Brain(provider=provider)
        brain.think("几点")
        assert len(provider.turns) > 0  # 剧本没被跑完，说明提前收手
    finally:
        settings.max_tool_rounds = original


def test_unknown_tool_is_reported_not_raised():
    out = invoke_tool("nope", {})
    assert "没有名为 nope 的工具" in out
    assert "算不出来" in invoke_tool("calculate", {"expression": "1/0"})


# ---------- 记忆 ----------

def test_memory_trims_by_whole_turn_keeping_tool_chain():
    mem = ConversationMemory(max_turns=1)
    mem.add("user", "第一轮")
    mem.add_assistant("", tool_calls=[ToolCall(id="c1", name="calculate")])
    mem.add_tool("c1", "calculate", "1+1 = 2")
    mem.add("assistant", "结果是 2")
    mem.add("user", "第二轮")

    roles = [m["role"] for m in mem.messages()]
    assert roles == ["system", "user"]
    assert len(mem) == 1


def test_memory_keeps_tool_chain_when_trimming_older_turns():
    mem = ConversationMemory(max_turns=2)
    mem.add("user", "第一轮")
    mem.add_assistant("好的")
    mem.add("user", "第二轮")
    mem.add_assistant("", tool_calls=[ToolCall(id="c1", name="get_time")])
    mem.add_tool("c1", "get_time", "现在是 09:00")
    mem.add("assistant", "现在九点")

    roles = [m["role"] for m in mem.messages()]
    assert roles == ["system", "user", "assistant", "user", "assistant", "tool", "assistant"]


# ---------- 计算技能的安全性 ----------

def test_calculator_results():
    assert "= 15" in invoke_tool("calculate", {"expression": "(12+8)*3/sqrt(16)"})
    assert "= 96" in invoke_tool("calculate", {"expression": "12×8"})
    assert "= 1024" in invoke_tool("calculate", {"expression": "2**10"})


@pytest.mark.parametrize(
    "evil",
    [
        "__import__('os').system('calc')",
        "open('secret.txt')",
        "1;2",
        "9**9**9",
        "x + 1",
    ],
)
def test_calculator_rejects_non_math(evil):
    with pytest.raises(ValueError):
        safe_eval(evil)
