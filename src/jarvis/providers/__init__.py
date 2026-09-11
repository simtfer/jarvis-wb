"""提供商注册表：按名字实例化对应的大脑后端。"""

from __future__ import annotations

from typing import Any

from .base import AssistantTurn, BaseProvider, Chunk, ProviderError, ToolCall, ToolCallsEvent
from .echo import EchoProvider
from .openai_compat import OpenAICompatProvider

_REGISTRY: dict[str, type[BaseProvider]] = {
    EchoProvider.name: EchoProvider,
    OpenAICompatProvider.name: OpenAICompatProvider,
}


def register(provider_cls: type[BaseProvider]) -> type[BaseProvider]:
    """注册新的提供商（第三方扩展入口）。"""
    _REGISTRY[provider_cls.name] = provider_cls
    return provider_cls


def create_provider(name: str, **kwargs: Any) -> BaseProvider:
    """按名字创建提供商实例。"""
    cls = _REGISTRY.get(name)
    if cls is None:
        raise ProviderError(f"未知提供商 '{name}'，可选: {', '.join(_REGISTRY)}")
    return cls(**kwargs)


def available_providers() -> list[str]:
    return list(_REGISTRY)


__all__ = [
    "AssistantTurn",
    "BaseProvider",
    "Chunk",
    "ProviderError",
    "ToolCall",
    "ToolCallsEvent",
    "available_providers",
    "create_provider",
    "register",
]
