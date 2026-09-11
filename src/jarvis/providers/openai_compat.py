"""OpenAI 兼容提供商：DeepSeek / Kimi / 通义 / OpenAI / 自建网关通用。

同时实现了流式输出（SSE）与工具调用（function calling）：
  - complete(): POST /chat/completions (stream=false)
  - stream():   POST /chat/completions (stream=true)，逐块解析 data: {...}
"""

from __future__ import annotations

import json
from typing import Any, Iterator

import httpx

from ..config import settings
from .base import (
    AssistantTurn,
    BaseProvider,
    Chunk,
    Message,
    ProviderError,
    ToolCall,
    ToolCallsEvent,
    ToolSpec,
    parse_arguments,
)


class OpenAICompatProvider(BaseProvider):
    """通过 /chat/completions 接口与任何 OpenAI 兼容服务对话。"""

    name = "openai_compat"
    timeout = 120.0

    def __init__(
        self,
        api_key: str | None = None,
        base_url: str | None = None,
        model: str | None = None,
        tool_hints: dict[str, list[str]] | None = None,
    ) -> None:
        super().__init__(tool_hints=tool_hints)
        self.api_key = api_key or settings.api_key
        self.base_url = (base_url or settings.base_url).rstrip("/")
        self.model = model or settings.model
        if not self.api_key:
            raise ProviderError(
                "缺少 API Key：请在 .env 中设置 JARVIS_API_KEY，"
                "或先用 JARVIS_PROVIDER=echo 运行。"
            )

    # ---------- 内部工具 ----------

    def _payload(self, messages: list[Message], tools: list[ToolSpec] | None, stream: bool) -> dict[str, Any]:
        payload: dict[str, Any] = {"model": self.model, "messages": messages, "stream": stream}
        if tools:
            payload["tools"] = tools
            payload["tool_choice"] = "auto"
        return payload

    @property
    def _headers(self) -> dict[str, str]:
        return {"Authorization": f"Bearer {self.api_key}", "Content-Type": "application/json"}

    @property
    def _url(self) -> str:
        return f"{self.base_url}/chat/completions"

    @staticmethod
    def _raise(resp: httpx.Response) -> None:
        raise ProviderError(
            f"接口返回错误 {resp.status_code}: {resp.text[:300]}"
        )

    # ---------- 非流式 ----------

    def complete(self, messages: list[Message], tools: list[ToolSpec] | None = None) -> AssistantTurn:
        try:
            resp = httpx.post(
                self._url,
                json=self._payload(messages, tools, stream=False),
                headers=self._headers,
                timeout=self.timeout,
            )
            if resp.status_code >= 400:
                self._raise(resp)
            message = resp.json()["choices"][0]["message"]
        except ProviderError:
            raise
        except (httpx.HTTPError, KeyError, IndexError) as e:
            raise ProviderError(f"调用 LLM 失败: {e}") from e

        calls = [
            ToolCall(
                id=tc.get("id", f"call_{i}"),
                name=(tc.get("function") or {}).get("name", ""),
                arguments=parse_arguments((tc.get("function") or {}).get("arguments", "")),
                raw_arguments=(tc.get("function") or {}).get("arguments", ""),
            )
            for i, tc in enumerate(message.get("tool_calls") or [])
        ]
        return AssistantTurn(text=(message.get("content") or "").strip(), tool_calls=calls)

    # ---------- 流式 ----------

    def stream(
        self, messages: list[Message], tools: list[ToolSpec] | None = None
    ) -> Iterator[Chunk | ToolCallsEvent]:
        # 工具调用在 SSE 里是分片下发的，需要按 index 累积后再解析
        acc: dict[int, dict[str, str]] = {}
        try:
            with httpx.stream(
                "POST",
                self._url,
                json=self._payload(messages, tools, stream=True),
                headers=self._headers,
                timeout=self.timeout,
            ) as resp:
                if resp.status_code >= 400:
                    resp.read()
                    self._raise(resp)
                for line in resp.iter_lines():
                    if not line:
                        continue
                    if line.startswith("data:"):
                        data = line[5:].strip()
                    elif line.startswith("{"):
                        data = line.strip()  # 少数兼容服务不带 data: 前缀
                    else:
                        continue
                    if data == "[DONE]":
                        break
                    try:
                        obj = json.loads(data)
                    except json.JSONDecodeError:
                        continue
                    choices = obj.get("choices") or []
                    if not choices:
                        continue
                    delta = choices[0].get("delta") or {}
                    if delta.get("content"):
                        yield Chunk(delta["content"])
                    for tc in delta.get("tool_calls") or []:
                        slot = acc.setdefault(
                            tc.get("index", 0), {"id": "", "name": "", "args": ""}
                        )
                        if tc.get("id"):
                            slot["id"] = tc["id"]
                        fn = tc.get("function") or {}
                        if fn.get("name"):
                            slot["name"] = fn["name"]
                        if fn.get("arguments"):
                            slot["args"] += fn["arguments"]
        except ProviderError:
            raise
        except httpx.HTTPError as e:
            raise ProviderError(f"流式调用失败: {e}") from e

        if acc:
            calls = [
                ToolCall(
                    id=slot["id"] or f"call_{idx}",
                    name=slot["name"],
                    arguments=parse_arguments(slot["args"]),
                    raw_arguments=slot["args"],
                )
                for idx, slot in sorted(acc.items())
                if slot["name"]
            ]
            if calls:
                yield ToolCallsEvent(calls)

    def describe(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "base_url": self.base_url,
            "model": self.model,
            "streaming": True,
            "tools": True,
        }
