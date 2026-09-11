"""配置中心：从环境变量 / .env 读取设置。"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

from dotenv import load_dotenv

# 项目根目录（src/jarvis 的上两级）
PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent


@dataclass
class Settings:
    """全局配置项，全部可被环境变量覆盖。"""

    provider: str = "echo"
    api_key: str = ""
    base_url: str = "https://api.deepseek.com/v1"
    model: str = "deepseek-chat"
    max_turns: int = 20
    system_prompt: str = (
        "你是贾维斯（JARVIS），非常先生的私人 AI 助手。"
        "风格：沉稳、高效、略带英式幽默，像钢铁侠电影中的贾维斯一样。"
        "回答简洁准确，需要时主动提出建议。"
    )
    # 已加载标志，避免重复加载 .env
    _loaded: bool = field(default=False, repr=False)

    def load(self) -> "Settings":
        """加载 .env 并用环境变量覆盖默认值。"""
        if self._loaded:
            return self
        load_dotenv(PROJECT_ROOT / ".env")
        env = os.environ
        self.provider = env.get("JARVIS_PROVIDER", self.provider).strip().lower()
        self.api_key = env.get("JARVIS_API_KEY", self.api_key).strip()
        self.base_url = env.get("JARVIS_BASE_URL", self.base_url).strip()
        self.model = env.get("JARVIS_MODEL", self.model).strip()
        self.max_turns = int(env.get("JARVIS_MAX_TURNS", self.max_turns))
        self._loaded = True
        return self


settings = Settings()
