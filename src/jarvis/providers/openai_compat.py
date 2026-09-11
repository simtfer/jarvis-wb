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
    # 兜底的默认超时（秒）；实际值取构造参数或配置项 JARVIS_REQUEST_TIMEOUT
    default_timeout = 45.0

    def __init__(
        self,
        api_key: str | None = None,
        base_url: str | None = None,
        model: str | None = None,
        tool_hints: dict[str, list[str]] | None = None,
        request_timeout: float | None = None,
    ) -> None:
        super().__init__(tool_hints=tool_hints, request_timeout=request_timeout)
        cfg = settings.load()
        self.api_key = api_key or cfg.api_key
        self.base_url = (base_url or cfg.base_url).rstrip("/")
        self.model = model or cfg.model
        # 超时必须有限：没有超时的流式请求会把界面无声挂住好几分钟
        self.timeout = float(request_timeout or cfg.request_timeout or self.default_timeout)
        if not self.api_key:
            raise ProviderError(
                "缺少 API Key：请在 .env 中设置 JARVIS_API_KEY，"
                "或先用 JARVIS_PROVIDER=echo 运行。"
            )

    # ---------- 内部工具 ----------

    @property
    def _timeout(self) -> httpx.Timeout:
        """连接阶段卡住多半是网络/代理问题，给短一点；读取阶段留给模型生成。"""
        return httpx.Timeout(self.timeout, connect=min(15.0, self.timeout))

    def _wrap_http_error(self, e: httpx.HTTPError) -> ProviderError:
        """把 httpx 的异常翻译成用户看得懂的话——否则界面只会沉默很久。"""
        if isinstance(e, httpx.TimeoutException):
            return ProviderError(
                f"请求超时（{self.timeout:.0f}s）：{self.base_url} 没有及时响应，已中止本轮。"
                "可调大 .env 里的 JARVIS_REQUEST_TIMEOUT，或换个更快的模型/网关。"
            )
        if isinstance(e, httpx.ConnectError):
            return ProviderError(
                f"连不上 {self.base_url}：{e}。检查网络/代理，或核对 JARVIS_BASE_URL。"
            )
        return ProviderError(f"调用 LLM 失败：{type(e).__name__}: {e}")

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
                timeout=self._timeout,
            )
            if resp.status_code >= 400:
                self._raise(resp)
            message = resp.json()["choices"][0]["message"]
        except ProviderError:
            raise
        except httpx.HTTPError as e:
            raise self._wrap_http_error(e) from e
        except (KeyError, IndexError, ValueError) as e:
            raise ProviderError(f"接口返回了意外的结构：{type(e).__name__}: {e}") from e

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
                timeout=self._timeout,
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
            raise self._wrap_http_error(e) from e

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
