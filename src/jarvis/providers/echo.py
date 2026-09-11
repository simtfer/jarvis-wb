"""离线演示提供商：不需要 API Key，用于框架开发与测试。"""

from __future__ import annotations

import random
import time

from .base import BaseProvider

_REPLIES = [
    "收到，先生。目前我运行在离线演示模式，接入真实 LLM 后即可满血服役。",
    "在线待命中，先生。配置 .env 中的 JARVIS_PROVIDER=openai_compat 即可唤醒我的大脑。",
    "明白。框架运行正常——只是暂时借用了回声模式在说话。",
    "已记录，先生。等您为我接上 API Key，我的词汇量就不止这几句了。",
]


class EchoProvider(BaseProvider):
    """固定话术回声，保证无网络/无密钥时框架依然可跑通。"""

    name = "echo"

    def chat(self, messages: list) -> str:
        # 模拟一点思考延迟，让 TUI 体验接近真实
        time.sleep(0.2)
        user_text = next(
            (m["content"] for m in reversed(messages) if m["role"] == "user"), ""
        )
        if not user_text.strip():
            return "先生，您好像什么都没说。"
        return random.choice(_REPLIES)
