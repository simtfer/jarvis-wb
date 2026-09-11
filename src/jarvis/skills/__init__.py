"""技能注册表：自动发现并挂载所有技能。"""

from __future__ import annotations

from .base import Skill
from .time_skill import TimeSkill

_REGISTRY: dict[str, Skill] = {}


def register(skill: Skill) -> None:
    _REGISTRY[skill.name] = skill


def load_builtin_skills() -> None:
    """挂载内置技能。新增技能后在这里加一行即可（后续可改为自动发现）。"""
    register(TimeSkill())


def dispatch(text: str) -> str | None:
    """尝试用本地技能处理输入；没有技能命中则返回 None，交给大脑。"""
    for skill in _REGISTRY.values():
        m = skill.match(text)
        if m:
            return skill.run(text, m)
    return None


def list_skills() -> list[Skill]:
    return list(_REGISTRY.values())
