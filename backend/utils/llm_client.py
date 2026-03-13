"""
LLM客户端封装模块
封装智谱AI API调用，支持流式和非流式调用
"""

import os
from typing import List, Dict, Any, Optional, AsyncGenerator
import asyncio
from zhipuai import ZhipuAI
from zhipuai.core._errors import (
    ZhipuAIError,
    APIConnectionError,
    APITimeoutError,
    APIStatusError,
    APIReachLimitError,
    APIServerFlowExceedError
)
from backend.core.config_manager import get_config_manager
from backend.utils.logger import get_logger


logger = get_logger(__name__)


class LLMClient:
    """
    LLM客户端封装类

    功能：
    1. 封装智谱AI API调用
    2. 支持流式和非流式调用
    3. 错误处理和重试
    4. 从ConfigManager读取配置
    """

    def __init__(self):
        """初始化LLM客户端"""
        self.config_manager = get_config_manager()

        # 获取模型配置
        self.model_config = self.config_manager.get_model_config("primary")

        # 获取API密钥（已经从环境变量读取，由 config_manager 处理）
        self.api_key = self.model_config.get("api_key")

        if not self.api_key:
            logger.warning("未找到智谱AI接口密钥配置，请在 .env 文件中设置 ZHIPU_API_KEY")

        # 初始化智谱AI客户端
        self.client = ZhipuAI(api_key=self.api_key) if self.api_key else None

        # 模型名称
        self.model_name = self.model_config.get("model_name", "glm-4")

        # 默认参数
        self.default_temperature = self.model_config.get("temperature", 0.7)
        self.default_max_tokens = self.model_config.get("max_tokens", 2000)
        self.default_top_p = self.model_config.get("top_p", 0.9)

        # 重试配置
        self.max_retries = self.model_config.get("max_retries", 3)
        self.retry_delay = self.model_config.get("retry_delay_seconds", 1)

        logger.info(f"大语言模型客户端初始化完成: 模型={self.model_name}")

    async def chat_completion(
        self,
        messages: List[Dict[str, str]],
        temperature: Optional[float] = None,
        max_tokens: Optional[int] = None,
        top_p: Optional[float] = None,
        model: Optional[str] = None,
        **kwargs
    ) -> str:
        """
        非流式聊天补全

        Args:
            messages: 消息列表，格式为[{"role": "system", "content": "..."}, ...]
            temperature: 温度参数（0-1）
            max_tokens: 最大token数
            top_p: top_p参数
            model: 模型名称（可选，默认使用配置中的模型）
            **kwargs: 其他参数

        Returns:
            生成的文本内容

        Raises:
            Exception: API调用失败
        """
        if not self.client:
            raise Exception("大语言模型客户端未初始化，请检查接口密钥")

        # 使用默认值
        temperature = temperature if temperature is not None else self.default_temperature
        max_tokens = max_tokens if max_tokens is not None else self.default_max_tokens
        top_p = top_p if top_p is not None else self.default_top_p
        model = model or self.model_name

        # 重试逻辑
        for attempt in range(self.max_retries):
            try:
                logger.debug(f"调用大语言模型接口 (尝试 {attempt + 1}/{self.max_retries})")

                # 调用智谱AI API
                response = self.client.chat.completions.create(
                    model=model,
                    messages=messages,
                    temperature=temperature,
                    max_tokens=max_tokens,
                    top_p=top_p,
                    **kwargs
                )

                # 提取生成的内容
                content = response.choices[0].message.content

                logger.info(f"大语言模型接口调用成功，生成 {len(content)} 个字符")
                return content

            except (APIConnectionError, APITimeoutError, APIStatusError, APIReachLimitError, APIServerFlowExceedError) as e:
                # API 相关错误
                logger.error(f"大语言模型接口调用失败 (尝试 {attempt + 1}/{self.max_retries}): {type(e).__name__}: {str(e)}")

                # 如果是最后一次尝试，抛出异常
                if attempt == self.max_retries - 1:
                    raise Exception(f"大语言模型接口调用失败，已重试{self.max_retries}次: {type(e).__name__}: {str(e)}")

                # 等待后重试
                await asyncio.sleep(self.retry_delay)

            except Exception as e:
                # 其他未预期的错误，直接抛出不重试
                logger.error(f"大语言模型接口调用遇到未预期错误: {type(e).__name__}: {str(e)}", exc_info=True)
                raise Exception(f"大语言模型接口调用失败: {type(e).__name__}: {str(e)}")

    async def chat_completion_stream(
        self,
        messages: List[Dict[str, str]],
        temperature: Optional[float] = None,
        max_tokens: Optional[int] = None,
        top_p: Optional[float] = None,
        model: Optional[str] = None,
        **kwargs
    ) -> AsyncGenerator[str, None]:
        """
        流式聊天补全

        Args:
            messages: 消息列表，格式为[{"role": "system", "content": "..."}, ...]
            temperature: 温度参数（0-1）
            max_tokens: 最大token数
            top_p: top_p参数
            model: 模型名称（可选，默认使用配置中的模型）
            **kwargs: 其他参数

        Yields:
            生成的文本片段

        Raises:
            Exception: API调用失败
        """
        if not self.client:
            raise Exception("大语言模型客户端未初始化，请检查接口密钥")

        # 使用默认值
        temperature = temperature if temperature is not None else self.default_temperature
        max_tokens = max_tokens if max_tokens is not None else self.default_max_tokens
        top_p = top_p if top_p is not None else self.default_top_p
        model = model or self.model_name

        # 重试逻辑
        for attempt in range(self.max_retries):
            try:
                logger.debug(f"调用大语言模型流式接口 (尝试 {attempt + 1}/{self.max_retries})")

                # 调用智谱AI API（流式）
                response = self.client.chat.completions.create(
                    model=model,
                    messages=messages,
                    temperature=temperature,
                    max_tokens=max_tokens,
                    top_p=top_p,
                    stream=True,
                    **kwargs
                )

                # 逐块返回内容
                total_chars = 0
                for chunk in response:
                    if chunk.choices and len(chunk.choices) > 0:
                        delta = chunk.choices[0].delta
                        if hasattr(delta, 'content') and delta.content:
                            content = delta.content
                            total_chars += len(content)
                            yield content

                logger.info(f"大语言模型流式接口调用完成，生成 {total_chars} 个字符")
                return

            except (APIConnectionError, APITimeoutError, APIStatusError, APIReachLimitError, APIServerFlowExceedError) as e:
                # API 相关错误
                logger.error(f"大语言模型流式接口调用失败 (尝试 {attempt + 1}/{self.max_retries}): {type(e).__name__}: {str(e)}")

                # 如果是最后一次尝试，抛出异常
                if attempt == self.max_retries - 1:
                    raise Exception(f"大语言模型流式接口调用失败，已重试{self.max_retries}次: {type(e).__name__}: {str(e)}")

                # 等待后重试
                await asyncio.sleep(self.retry_delay)

            except Exception as e:
                # 其他未预期的错误，直接抛出不重试
                logger.error(f"大语言模型流式接口调用遇到未预期错误: {type(e).__name__}: {str(e)}", exc_info=True)
                raise Exception(f"大语言模型流式接口调用失败: {type(e).__name__}: {str(e)}")

    async def generate_text(
        self,
        prompt: str,
        system_prompt: Optional[str] = None,
        temperature: Optional[float] = None,
        max_tokens: Optional[int] = None,
        **kwargs
    ) -> str:
        """
        简单文本生成（便捷方法）

        Args:
            prompt: 用户提示词
            system_prompt: 系统提示词（可选）
            temperature: 温度参数
            max_tokens: 最大token数
            **kwargs: 其他参数

        Returns:
            生成的文本内容
        """
        messages = []

        # 添加系统提示词
        if system_prompt:
            messages.append({"role": "system", "content": system_prompt})

        # 添加用户提示词
        messages.append({"role": "user", "content": prompt})

        return await self.chat_completion(
            messages=messages,
            temperature=temperature,
            max_tokens=max_tokens,
            **kwargs
        )

    async def generate_text_stream(
        self,
        prompt: str,
        system_prompt: Optional[str] = None,
        temperature: Optional[float] = None,
        max_tokens: Optional[int] = None,
        **kwargs
    ) -> AsyncGenerator[str, None]:
        """
        简单文本生成（流式，便捷方法）

        Args:
            prompt: 用户提示词
            system_prompt: 系统提示词（可选）
            temperature: 温度参数
            max_tokens: 最大token数
            **kwargs: 其他参数

        Yields:
            生成的文本片段
        """
        messages = []

        # 添加系统提示词
        if system_prompt:
            messages.append({"role": "system", "content": system_prompt})

        # 添加用户提示词
        messages.append({"role": "user", "content": prompt})

        async for chunk in self.chat_completion_stream(
            messages=messages,
            temperature=temperature,
            max_tokens=max_tokens,
            **kwargs
        ):
            yield chunk

    def get_model_info(self) -> Dict[str, Any]:
        """
        获取模型信息

        Returns:
            模型信息字典
        """
        return {
            "model_name": self.model_name,
            "temperature": self.default_temperature,
            "max_tokens": self.default_max_tokens,
            "top_p": self.default_top_p,
            "provider": self.model_config.get("provider", "zhipuai"),
        }

    def is_available(self) -> bool:
        """
        检查LLM客户端是否可用

        Returns:
            是否可用
        """
        return self.client is not None and self.api_key is not None


# 全局LLM客户端实例
_llm_client: Optional[LLMClient] = None


def get_llm_client() -> LLMClient:
    """
    获取全局LLM客户端实例（单例模式）

    Returns:
        LLMClient实例
    """
    global _llm_client

    if _llm_client is None:
        _llm_client = LLMClient()

    return _llm_client


# 便捷函数
async def chat(messages: List[Dict[str, str]], **kwargs) -> str:
    """
    聊天补全（便捷函数）

    Args:
        messages: 消息列表
        **kwargs: 其他参数

    Returns:
        生成的文本内容
    """
    return await get_llm_client().chat_completion(messages, **kwargs)


async def chat_stream(messages: List[Dict[str, str]], **kwargs) -> AsyncGenerator[str, None]:
    """
    流式聊天补全（便捷函数）

    Args:
        messages: 消息列表
        **kwargs: 其他参数

    Yields:
        生成的文本片段
    """
    async for chunk in get_llm_client().chat_completion_stream(messages, **kwargs):
        yield chunk
