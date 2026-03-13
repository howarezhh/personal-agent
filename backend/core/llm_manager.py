"""兼容层：保留旧的 llm_manager 导入路径。"""

from __future__ import annotations

from typing import Any, AsyncGenerator, Dict, List, Optional

from backend.utils.llm_client import LLMClient, get_llm_client


class LLMManager:
    def __init__(self, client: Optional[LLMClient] = None):
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


_llm_manager: Optional[LLMManager] = None


def get_llm_manager() -> LLMManager:
    global _llm_manager
    if _llm_manager is None:
        _llm_manager = LLMManager()
    return _llm_manager
