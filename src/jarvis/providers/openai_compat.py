"""OpenAI 兼容提供商：DeepSeek / Kimi / 通义 / OpenAI / 自建网关通用。"""

from __future__ import annotations

import httpx

from ..config import settings
from .base import BaseProvider, ProviderError


class OpenAICompatProvider(BaseProvider):
    """通过 /chat/completions 接口与任何 OpenAI 兼容服务对话。"""

    name = "openai_compat"
    timeout = 60.0

    def __init__(self, api_key: str | None = None, base_url: str | None = None,
                 model: str | None = None) -> None:
        self.api_key = api_key or settings.api_key
        self.base_url = (base_url or settings.base_url).rstrip("/")
        self.model = model or settings.model
        if not self.api_key:
            raise ProviderError(
                "缺少 API Key：请在 .env 中设置 JARVIS_API_KEY，"
                "或先用 JARVIS_PROVIDER=echo 运行。"
            )

    def chat(self, messages: list) -> str:
        payload = {"model": self.model, "messages": messages, "stream": False}
        headers = {"Authorization": f"Bearer {self.api_key}"}
        try:
            resp = httpx.post(
                f"{self.base_url}/chat/completions",
                json=payload,
                headers=headers,
                timeout=self.timeout,
            )
            resp.raise_for_status()
            data = resp.json()
            return data["choices"][0]["message"]["content"].strip()
        except httpx.HTTPStatusError as e:
            raise ProviderError(f"接口返回错误 {e.response.status_code}: {e.response.text[:200]}") from e
        except (httpx.HTTPError, KeyError, IndexError) as e:
            raise ProviderError(f"调用 LLM 失败: {e}") from e

    def describe(self) -> dict:
        return {"name": self.name, "base_url": self.base_url, "model": self.model}
