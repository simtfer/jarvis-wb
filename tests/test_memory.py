"""长期记忆测试：持久化、检索、工具化存取、自动召回注入。全部离线。"""

import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

os.environ["JARVIS_PROVIDER"] = "echo"

import pytest

from jarvis import ltm as ltm_mod
from jarvis.config import settings
from jarvis.ltm import LongTermMemory, get_ltm, reset_ltm
from jarvis.providers.base import AssistantTurn, BaseProvider
from jarvis.skills import invoke_tool


@pytest.fixture()
def fresh_ltm(tmp_path, monkeypatch):
    """每个用例独享一个临时记忆库，并让进程单例指向它。"""
    monkeypatch.setattr(settings, "data_dir", tmp_path)
    reset_ltm()
    yield get_ltm()
    reset_ltm()


# ---------- 存储 ----------

def test_persistence_round_trip(tmp_path):
    path = tmp_path / "memory.json"
    store = LongTermMemory(path=path)
    item = store.remember("主人的名字是非常", tags=["身份"])
    assert len(store) == 1

    reopened = LongTermMemory(path=path)
    assert len(reopened) == 1
    assert reopened.all()[0].text == "主人的名字是非常"
    assert reopened.all()[0].id == item.id
    assert reopened.all()[0].tags == ["身份"]


def test_remember_dedupes_identical_text(fresh_ltm):
    fresh_ltm.remember("项目使用 uv 管理依赖")
    fresh_ltm.remember("项目使用 uv 管理依赖")
    assert len(fresh_ltm) == 1


def test_remember_rejects_empty(fresh_ltm):
    with pytest.raises(ValueError):
        fresh_ltm.remember("   ")


def test_corrupt_file_backs_up_and_recovers(tmp_path):
    path = tmp_path / "memory.json"
    path.write_text("{不是合法 JSON", encoding="utf-8")
    store = LongTermMemory(path=path)
    assert len(store) == 0
    assert path.with_suffix(".json.bak").exists()
    store.remember("重建后的第一条")
    assert len(store) == 1


# ---------- 检索 ----------

def test_recall_finds_relevant_and_skips_irrelevant(fresh_ltm):
    fresh_ltm.remember("主人的名字是非常", tags=["身份"])
    fresh_ltm.remember("贾维斯项目用 Python + uv 开发", tags=["项目"])
    fresh_ltm.remember("主人偏好深色主题的终端", tags=["偏好"])

    hits = fresh_ltm.recall("主人叫什么名字")
    assert hits, "应该召回身份记忆"
    assert "非常" in hits[0][0].text

    assert fresh_ltm.recall("今天晚饭吃什么") == []


def test_recall_respects_limit_and_counts_hits(fresh_ltm):
    for i in range(8):
        fresh_ltm.remember(f"笔记 {i} 关于 Python 的点点滴滴")
    hits = fresh_ltm.recall("python", limit=3)
    assert len(hits) == 3


def test_forget_by_id_prefix_and_keyword(fresh_ltm):
    a = fresh_ltm.remember("临时事项甲")
    fresh_ltm.remember("要长期保留的资料")
    assert fresh_ltm.forget(a.id[:6]) == 1
    assert fresh_ltm.forget("资料") == 1
    assert len(fresh_ltm) == 0
    assert fresh_ltm.forget("不存在") == 0


# ---------- 工具化 ----------

def test_memory_tools_roundtrip(fresh_ltm):
    saved = invoke_tool("save_memory", {"content": "主人喜欢喝美式咖啡", "tags": ["偏好"]})
    assert "已记住" in saved

    found = invoke_tool("recall_memory", {"query": "主人喜欢喝什么咖啡"})
    assert "美式" in found

    assert "没有" in invoke_tool("recall_memory", {"query": "量子纠缠的最新进展"})


def test_forget_tool(fresh_ltm):
    invoke_tool("save_memory", {"content": "这条要被忘掉"})
    out = invoke_tool("forget_memory", {"ident": "忘掉"})
    assert "已删除 1 条" in out
    assert len(fresh_ltm) == 0


# ---------- 自动召回注入 ----------

class MiniScriptedProvider(BaseProvider):
    """只记录收到的消息、按剧本回话的最小假提供商。"""

    name = "mini_scripted"

    def __init__(self, replies):
        super().__init__()
        self.replies = list(replies)
        self.seen = []

    def complete(self, messages, tools=None):
        self.seen.append([dict(m) for m in messages])
        return AssistantTurn(text=self.replies.pop(0) if self.replies else "")


def test_brain_injects_recalled_memory_into_system_prompt(fresh_ltm):
    from jarvis.core import Brain

    fresh_ltm.remember("主人的名字是非常", tags=["身份"])
    provider = MiniScriptedProvider(["您好，非常先生。"])
    brain = Brain(provider=provider)

    reply = brain.think("我叫什么名字？")

    assert reply == "您好，非常先生。"
    system_content = provider.seen[0][0]["content"]
    assert "[长期记忆参考]" in system_content
    assert "主人的名字是非常" in system_content
    # 召回只进本轮请求，不写入会话记忆
    assert all(
        "[长期记忆参考]" not in (m.get("content") or "") for m in brain.memory.messages()
    )


def test_brain_skips_recall_when_disabled(fresh_ltm, monkeypatch):
    from jarvis.core import Brain

    fresh_ltm.remember("主人的名字是非常")
    monkeypatch.setattr(settings, "auto_recall", False)
    provider = MiniScriptedProvider(["好的。"])
    brain = Brain(provider=provider)
    brain.think("我叫什么名字？")
    assert "[长期记忆参考]" not in provider.seen[0][0]["content"]
