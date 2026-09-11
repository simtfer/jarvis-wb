"""长期记忆技能：让模型能把重要信息存进 / 从长期记忆里取出来。

注意：Skill.invoke() 会把参数里的 "text" 键当作原始输入弹出，所以工具参数避免命名为 "text"。
"""

from __future__ import annotations

from typing import Any

from ..ltm import get_ltm
from .base import Skill

_MAX_TEXT = 500


def _clean_tags(tags: Any) -> list[str]:
    if tags is None:
        return []
    if isinstance(tags, str):
        tags = [tags]
    if not isinstance(tags, (list, tuple)):
        return []
    return [str(t).strip() for t in tags if str(t).strip()][:8]


class SaveMemorySkill(Skill):
    name = "save_memory"
    description = (
        "把值得长期记住的信息存入贾维斯的长期记忆：用户偏好、身份事实、约定、项目背景等。"
        "只在用户明确要求记住、或信息明显长期有价值时使用；不要存临时性内容。"
    )
    keywords = ["记住", "记一下", "remember", "长期记忆"]
    patterns: list[str] = []  # 快速路径由 TUI 的 /remember 命令承担
    parameters: dict[str, Any] = {
        "content": {
            "type": "string",
            "description": "要记住的内容，一句话，尽量自包含（如：主人的名字是非常）",
        },
        "tags": {
            "type": "array",
            "items": {"type": "string"},
            "description": "可选标签，如 [\"偏好\", \"身份\"]",
        },
    }
    required = ["content"]

    def run(self, text: str = "", content: str = "", tags: Any = None, **kwargs: Any) -> str:
        body = (content or text or "").strip()[:_MAX_TEXT]
        if not body:
            return "要记住的内容是空的，先生。"
        item = get_ltm().remember(body, tags=_clean_tags(tags))
        tag_str = "、".join(item.tags) or "无"
        return f"已记住（#{item.id[:8]}，标签：{tag_str}）：{item.text}"


class RecallMemorySkill(Skill):
    name = "recall_memory"
    description = "从长期记忆里检索与问题相关的历史信息。当用户问'还记得…吗'或需要旧信息时使用。"
    keywords = ["记得", "之前", "回忆", "recall", "记忆"]
    patterns: list[str] = []
    parameters: dict[str, Any] = {
        "query": {"type": "string", "description": "检索关键词或一句话问题"}
    }
    required = ["query"]

    def run(self, text: str = "", query: str = "", **kwargs: Any) -> str:
        hits = get_ltm().recall(query or text)
        if not hits:
            return "长期记忆里没有相关内容，先生。"
        lines = [
            f"[#{item.id[:8]}] {item.text}（标签：{'、'.join(item.tags) or '无'}）"
            for item, _ in hits
        ]
        return "找到这些相关记忆：\n" + "\n".join(lines)


class ForgetMemorySkill(Skill):
    name = "forget_memory"
    description = "按记忆编号前缀或内容关键词，从长期记忆里删除条目。仅在用户明确要求忘记时使用。"
    keywords = ["忘记", "忘掉", "删除记忆", "forget"]
    patterns: list[str] = []
    parameters: dict[str, Any] = {
        "ident": {"type": "string", "description": "记忆编号前缀（如 a1b2c3d4）或内容关键词"}
    }
    required = ["ident"]

    def run(self, text: str = "", ident: str = "", **kwargs: Any) -> str:
        removed = get_ltm().forget(ident or text)
        if not removed:
            return f"没有匹配「{ident}」的记忆，先生。"
        return f"已删除 {removed} 条记忆。"
