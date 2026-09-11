"""冒烟测试：不依赖网络与 API Key。"""

import os
import sys
from pathlib import Path

# 保证以源码方式可导入
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

os.environ["JARVIS_PROVIDER"] = "echo"

from jarvis.config import settings
from jarvis.core import Brain
from jarvis.providers import create_provider
from jarvis.skills import dispatch


def test_echo_brain_conversation():
    settings.load()
    brain = Brain()
    reply = brain.think("贾维斯，在吗")
    assert reply
    assert len(brain.memory) == 2  # user + assistant
    brain.reset()
    assert len(brain.memory) == 0


def test_time_skill_hits_before_brain():
    hit = dispatch("现在几点了")
    assert hit is not None and "现在是" in hit
    assert dispatch("今天天气如何") is None


def test_provider_registry():
    provider = create_provider("echo")
    out = provider.chat([{"role": "user", "content": "hi"}])
    assert isinstance(out, str) and out


def test_registry_exposes_tools():
    from jarvis.skills import list_skills, tool_specs

    names = {s.name for s in list_skills()}
    assert {"get_time", "calculate", "system_info"} <= names
    specs = tool_specs()
    assert all(spec["type"] == "function" for spec in specs)
    calc = next(s for s in specs if s["function"]["name"] == "calculate")
    assert "expression" in calc["function"]["parameters"]["properties"]
