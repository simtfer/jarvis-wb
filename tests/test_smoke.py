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
from jarvis.skills import dispatch, load_builtin_skills


def test_echo_brain_conversation():
    settings.load()
    brain = Brain()
    reply = brain.think("贾维斯，在吗")
    assert reply
    assert len(brain.memory) == 2  # user + assistant
    brain.reset()
    assert len(brain.memory) == 0


def test_time_skill_hits_before_brain():
    load_builtin_skills()
    hit = dispatch("现在几点了")
    assert hit is not None and "现在是" in hit
    assert dispatch("今天天气如何") is None


def test_provider_registry():
    provider = create_provider("echo")
    out = provider.chat([{"role": "user", "content": "hi"}])
    assert isinstance(out, str) and out
