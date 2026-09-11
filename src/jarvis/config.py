"""配置中心：从环境变量 / .env 读取设置。"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

from dotenv import load_dotenv

# 项目根目录（src/jarvis 的上两级）
PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent

_TRUE = {"1", "true", "yes", "y", "on"}


def _env_bool(env: dict[str, str], key: str, default: bool) -> bool:
    raw = env.get(key)
    if raw is None:
        return default
    return raw.strip().lower() in _TRUE


@dataclass
class Settings:
    """全局配置项，全部可被环境变量覆盖。"""

    provider: str = "echo"
    api_key: str = ""
    base_url: str = "https://api.deepseek.com/v1"
    model: str = "deepseek-chat"
    max_turns: int = 20
    # 流式输出（逐字显示）
    stream: bool = True
    # 是否把本地技能作为工具交给 LLM 调用
    tools_enabled: bool = True
    # 单次对话内最多允许几轮工具调用（防止模型无限循环）
    max_tool_rounds: int = 4
    # 正则快速路径：命中即本地执行，不经过 LLM（TUI 里可用 /local 临时开关）
    local_skills: bool = True
    # 长期记忆数据目录（memory.json 所在位置）
    data_dir: Path = PROJECT_ROOT / "data"
    # 每轮对话前自动召回相关长期记忆，注入 system prompt
    auto_recall: bool = True
    # 自动召回最多注入几条
    recall_top_k: int = 3
    system_prompt: str = (
        "你是贾维斯（JARVIS），非常先生的私人 AI 助手。"
        "风格：沉稳、高效、略带英式幽默，像钢铁侠电影中的贾维斯一样。"
        "回答简洁准确，需要时主动提出建议。"
        "你可以调用本地工具获取实时信息（时间、计算、系统状态），"
        "需要时直接调用，不要凭空猜测。"
    )
    # 已加载标志，避免重复加载 .env
    _loaded: bool = field(default=False, repr=False)

    def load(self) -> "Settings":
        """加载 .env 并用环境变量覆盖默认值（幂等）。"""
        if self._loaded:
            return self
        self.reload()
        return self

    def reload(self) -> "Settings":
        """强制重新读取 .env / 环境变量（已存在的进程环境变量优先）。"""
        load_dotenv(PROJECT_ROOT / ".env", override=False)
        env = os.environ
        self.provider = env.get("JARVIS_PROVIDER", self.provider).strip().lower()
        self.api_key = env.get("JARVIS_API_KEY", self.api_key).strip()
        self.base_url = env.get("JARVIS_BASE_URL", self.base_url).strip()
        self.model = env.get("JARVIS_MODEL", self.model).strip()
        self.max_turns = int(env.get("JARVIS_MAX_TURNS", self.max_turns))
        self.stream = _env_bool(env, "JARVIS_STREAM", self.stream)
        self.tools_enabled = _env_bool(env, "JARVIS_TOOLS", self.tools_enabled)
        self.local_skills = _env_bool(env, "JARVIS_LOCAL_SKILLS", self.local_skills)
        self.max_tool_rounds = int(env.get("JARVIS_MAX_TOOL_ROUNDS", self.max_tool_rounds))
        if env.get("JARVIS_DATA_DIR"):
            self.data_dir = Path(env["JARVIS_DATA_DIR"].strip())
        self.auto_recall = _env_bool(env, "JARVIS_AUTO_RECALL", self.auto_recall)
        self.recall_top_k = int(env.get("JARVIS_RECALL_TOP_K", self.recall_top_k))
        self._loaded = True
        return self


settings = Settings()
