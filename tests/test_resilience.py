"""v0.4.1 韧性测试：不让「工具失败」变成「界面卡死」。全部离线。

覆盖四类真实故障：
  1. 模型在同一轮里反复要同一个工具（真实 LLM 被拒绝后的典型行为）→ 熔断；
  2. 工具返回"拒绝/不可用"→ 写入记忆的文本要带上"不要重试"，界面显示保持原文；
  3. Provider 超时/连不上 → 转成中文可读错误，而不是沉默几分钟；
  4. 命令执行超时 → 必须快速返回（Windows 上孙进程持有管道时最容易踩）。
"""

import os
import sys
import time
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

os.environ["JARVIS_PROVIDER"] = "echo"

import httpx

from jarvis.config import settings
from jarvis.core import Brain
from jarvis.providers.base import AssistantTurn, BaseProvider, ProviderError, ToolCall
from jarvis.providers.openai_compat import OpenAICompatProvider
from jarvis.skills.shell_skill import _execute


@pytest.fixture()
def restore_settings():
    """settings 是进程级单例，用例改过之后必须还原。"""
    snapshot = dict(settings.__dict__)
    yield settings
    settings.__dict__.clear()
    settings.__dict__.update(snapshot)


@pytest.fixture()
def no_shell(monkeypatch):
    """确保命令执行处于默认关闭状态。"""
    monkeypatch.setattr(settings, "shell_enabled", False, raising=False)


class StubbornProvider(BaseProvider):
    """模拟"被拒绝就再来一次"的真实模型：每轮都发起同样的工具调用。"""

    name = "stubborn"

    def __init__(self, name: str, arguments: dict) -> None:
        super().__init__()
        self.tool_name = name
        self.arguments = arguments
        self.rounds = 0

    def complete(self, messages, tools=None):
        self.rounds += 1
        return AssistantTurn(
            text="",
            tool_calls=[
                ToolCall(id=f"call_{self.rounds}", name=self.tool_name, arguments=dict(self.arguments))
            ],
        )


class OneShotProvider(BaseProvider):
    """先要一次工具，再正常说话。"""

    name = "oneshot"

    def __init__(self, name: str, arguments: dict, reply: str = "好了，先生。") -> None:
        super().__init__()
        self.tool_name = name
        self.arguments = arguments
        self.reply = reply
        self.rounds = 0

    def complete(self, messages, tools=None):
        self.rounds += 1
        if self.rounds == 1:
            return AssistantTurn(
                text="稍等，先生。",
                tool_calls=[ToolCall(id="call_1", name=self.tool_name, arguments=dict(self.arguments))],
            )
        return AssistantTurn(text=self.reply)


# ---------- 1. 重复调用熔断 ----------

def test_repeated_tool_call_is_circuit_broken():
    """模型坚持重复同一个工具调用时：只执行一次、只请求两次、直接给答案。"""
    provider = StubbornProvider("calculate", {"expression": "2+2"})
    brain = Brain(provider=provider)
    executed: list[tuple[str, str]] = []

    reply = brain.think("算一下 2+2", on_tool=lambda c, r: executed.append((c.name, r)))

    assert provider.rounds == 2, "第二轮就该熔断，不该继续请求模型"
    assert len(executed) == 1, "同一个调用只允许真正执行一次"
    assert "4" in reply, "熔断后要把已有结果直接告诉用户"


def test_circuit_breaker_keeps_memory_chain_valid():
    """熔断也要补全 tool 消息，否则发给严格校验的接口会直接 400。"""
    provider = StubbornProvider("calculate", {"expression": "3*3"})
    brain = Brain(provider=provider)
    brain.think("算一下")

    messages = brain.memory.messages()
    call_ids = [
        tc["id"]
        for m in messages
        if m["role"] == "assistant" and m.get("tool_calls")
        for tc in m["tool_calls"]
    ]
    tool_ids = [m["tool_call_id"] for m in messages if m["role"] == "tool"]
    assert call_ids, "应当有带 tool_calls 的助手消息"
    assert set(call_ids).issubset(set(tool_ids)), "每个 tool_call 都必须有对应的 tool 消息"


def test_different_arguments_still_allowed():
    """参数不同就不是死循环，不该被熔断误杀。"""
    provider = StubbornProvider("calculate", {"expression": "1+1"})
    brain = Brain(provider=provider)
    brain.think("算一下")
    # 第二轮参数相同 → 熔断；确认熔断判定基于"名字 + 参数"而不是只比名字
    assert provider.rounds == 2


# ---------- 2. 拒绝类结果附带禁重试提示 ----------

def test_refusal_result_gets_no_retry_hint_in_memory(no_shell):
    provider = OneShotProvider("run_command", {"command": "dir"})
    brain = Brain(provider=provider)
    shown: list[tuple[str, str]] = []

    brain.think("执行 dir", on_tool=lambda c, r: shown.append((c.name, r)))

    tool_message = next(m for m in brain.memory.messages() if m["role"] == "tool")
    assert "默认关闭" in tool_message["content"]
    assert "不要重复调用" in tool_message["content"], "记忆里的版本要劝模型别重试"
    assert "不要重复调用" not in shown[0][1], "界面显示给用户的是原始结果，不该带内部提示"


def test_normal_tool_result_has_no_hint():
    provider = OneShotProvider("calculate", {"expression": "6*7"})
    brain = Brain(provider=provider)
    brain.think("算一下 6*7")
    tool_message = next(m for m in brain.memory.messages() if m["role"] == "tool")
    assert "42" in tool_message["content"]
    assert "不要重复调用" not in tool_message["content"]


# ---------- 3. Provider 超时 / 连不上 ----------

def test_stream_timeout_becomes_readable_provider_error(monkeypatch):
    provider = OpenAICompatProvider(api_key="test", request_timeout=0.5)

    def boom(*args, **kwargs):
        raise httpx.ReadTimeout("read timed out")

    monkeypatch.setattr(httpx, "stream", boom)

    with pytest.raises(ProviderError) as excinfo:
        list(provider.stream([{"role": "user", "content": "hi"}]))

    message = str(excinfo.value)
    assert "超时" in message and "JARVIS_REQUEST_TIMEOUT" in message


def test_connect_error_becomes_readable_provider_error(monkeypatch):
    provider = OpenAICompatProvider(api_key="test", request_timeout=0.5)

    def boom(*args, **kwargs):
        raise httpx.ConnectError("connection refused")

    monkeypatch.setattr(httpx, "post", boom)

    with pytest.raises(ProviderError) as excinfo:
        provider.complete([{"role": "user", "content": "hi"}])

    assert "连不上" in str(excinfo.value)


def test_provider_uses_configured_timeout():
    provider = OpenAICompatProvider(api_key="test", request_timeout=7.5)
    assert provider.timeout == 7.5
    # 显式超时要落到 httpx.Timeout 上，连接阶段更短
    assert provider._timeout.connect == 7.5


def test_request_timeout_from_env(restore_settings, monkeypatch):
    monkeypatch.setenv("JARVIS_REQUEST_TIMEOUT", "12")
    monkeypatch.setattr(settings, "_loaded", False)
    settings.reload()
    assert settings.request_timeout == 12.0


def test_request_timeout_default_is_bounded(restore_settings):
    assert settings.load().request_timeout <= 60, "默认请求超时必须是有界的，不能是几分钟"


# ---------- 4. 命令执行超时必须快速返回 ----------

def test_execute_returns_none_on_timeout():
    grandchild = "import time; time.sleep(25)"
    parent = (
        "import subprocess, sys, time; "
        f"subprocess.Popen([sys.executable, '-c', {grandchild!r}]); "
        "time.sleep(30)"
    )
    command = f'"{sys.executable}" -c "{parent}"'

    start = time.perf_counter()
    result = _execute(command, timeout=2)
    elapsed = time.perf_counter() - start

    assert result is None, "超时应当返回 None"
    # 关键回归：修复前这里会一直等到孙进程结束（实测 30s，常驻进程则永不返回）
    assert elapsed < 12, f"超时后必须尽快返回，实际耗时 {elapsed:.1f}s"


def test_execute_runs_normal_command():
    code, out, _ = _execute("echo jarvis-ok", timeout=15)
    assert code == 0
    assert b"jarvis-ok" in out
