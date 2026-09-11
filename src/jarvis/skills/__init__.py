"""技能注册表：集中管理所有本地技能，并对外提供两种入口。

  - dispatch(text)                 正则快速路径：命中即本地执行，零延迟
  - tool_specs() / invoke_tool()   工具路径：交给 LLM 决定何时调用
"""

from __future__ import annotations

from typing import Any

from .base import Skill
from .calc_skill import CalcSkill
from .memory_skill import ForgetMemorySkill, RecallMemorySkill, SaveMemorySkill
from .system_skill import SystemInfoSkill
from .time_skill import TimeSkill

_REGISTRY: dict[str, Skill] = {}
_LOADED = False


def register(skill: Skill) -> Skill:
    """挂载一个技能实例。"""
    _REGISTRY[skill.name] = skill
    return skill


def load_builtin_skills() -> None:
    """挂载内置技能（幂等；导入本模块时会自动执行一次）。"""
    global _LOADED
    if _LOADED:
        return
    for skill in (
        TimeSkill(),
        CalcSkill(),
        SystemInfoSkill(),
        SaveMemorySkill(),
        RecallMemorySkill(),
        ForgetMemorySkill(),
    ):
        register(skill)
    _LOADED = True


# ---------- 快速路径 ----------

def dispatch(text: str) -> str | None:
    """尝试用本地技能处理输入；没有技能命中则返回 None，交给大脑。"""
    for skill in _REGISTRY.values():
        match = skill.match(text)
        if match:
            return skill.run(match.group(0))
    return None


# ---------- 工具路径 ----------

def tool_specs() -> list[dict[str, Any]]:
    """所有技能的工具描述，供 LLM 挑选调用。"""
    return [skill.tool_spec() for skill in _REGISTRY.values()]


def tool_hints() -> dict[str, list[str]]:
    """{工具名: 关键词}，仅供离线演示提供商模拟工具调用。"""
    return {skill.name: list(skill.keywords) for skill in _REGISTRY.values()}


def invoke_tool(name: str, arguments: dict[str, Any] | None = None) -> str:
    """按名字执行工具，异常统一转成可读文本（不打断对话）。"""
    skill = _REGISTRY.get(name)
    if skill is None:
        return f"没有名为 {name} 的工具，先生。可用工具：{', '.join(_REGISTRY)}"
    try:
        return skill.invoke(arguments)
    except Exception as e:  # noqa: BLE001 —— 工具出错不该炸掉整个对话
        return f"工具 {name} 执行失败：{type(e).__name__}: {e}"


def get_skill(name: str) -> Skill | None:
    return _REGISTRY.get(name)


def list_skills() -> list[Skill]:
    return list(_REGISTRY.values())


load_builtin_skills()
