"""LLM 调用管理模块。

该模块对底层 `LLMClient` 做了一层轻量封装，主要目的有：
1. 统一普通生成与流式生成的调用入口；
2. 将单轮 prompt 自动包装成标准 messages 结构；
3. 通过单例函数复用同一个 LLM 管理器实例。
"""

from __future__ import annotations

from typing import AsyncGenerator, Dict, List, Optional

from backend.utils.llm_client import LLMClient, get_llm_client


class LLMManager:
    """大模型调用管理器。"""

    def __init__(self, client: Optional[LLMClient] = None):
        """初始化管理器。

        Args:
            client: 可选的底层 LLM 客户端；未传入时使用默认单例客户端。
        """
        self.client = client or get_llm_client()

    async def generate(
        self,
        prompt: str,
        *,
        system_prompt: Optional[str] = None,
        temperature: Optional[float] = None,
        max_tokens: Optional[int] = None,
        top_p: Optional[float] = None,
        model: Optional[str] = None,
        **kwargs,
    ) -> str:
        """执行一次非流式文本生成。

        该方法会把传入的系统提示词和用户提示词包装为聊天消息列表，
        再交给底层客户端的 `chat_completion` 统一处理。
        """
        messages: List[Dict[str, str]] = []
        if system_prompt:
            messages.append({"role": "system", "content": system_prompt})
        messages.append({"role": "user", "content": prompt})
        return await self.client.chat_completion(
            messages,
            temperature=temperature,
            max_tokens=max_tokens,
            top_p=top_p,
            model=model,
            **kwargs,
        )

    async def generate_stream(
        self,
        prompt: str,
        *,
        system_prompt: Optional[str] = None,
        temperature: Optional[float] = None,
        max_tokens: Optional[int] = None,
        top_p: Optional[float] = None,
        model: Optional[str] = None,
        **kwargs,
    ) -> AsyncGenerator[str, None]:
        """执行一次流式文本生成。

        与 `generate` 不同，该方法逐块产出模型返回内容，适用于 SSE、WebSocket
        或其他需要边生成边消费的场景。
        """
        messages: List[Dict[str, str]] = []
        if system_prompt:
            messages.append({"role": "system", "content": system_prompt})
        messages.append({"role": "user", "content": prompt})
        async for chunk in self.client.chat_completion_stream(
            messages,
            temperature=temperature,
            max_tokens=max_tokens,
            top_p=top_p,
            model=model,
            **kwargs,
        ):
            yield chunk


# 模块级单例缓存，供全局复用。
_llm_manager: Optional[LLMManager] = None


def get_llm_manager() -> LLMManager:
    """获取 `LLMManager` 单例。"""
    global _llm_manager
    if _llm_manager is None:
        _llm_manager = LLMManager()
    return _llm_manager
