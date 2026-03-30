# -*- coding: utf-8 -*-
"""基于 LangChain Prompt/Runnable 的统一模型交互层。

本模块只保留新的模型交互规范：
1. Prompt 统一使用 `PromptTemplate` / `ChatPromptTemplate`；
2. 模型调用统一通过本模块收敛；
3. 结构化输出与工具绑定在本层完成注入与解析；
4. 流式输出只向上暴露纯文本分片，不透传框架原生事件；
5. 仅保留当前统一模型交互入口，不再引入并行旧入口。
"""

from __future__ import annotations

import asyncio
import json
from copy import deepcopy
from dataclasses import dataclass
from typing import Any, AsyncGenerator, Dict, List, Optional, Sequence, TypeVar

from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import AIMessage, AIMessageChunk, BaseMessage, HumanMessage, SystemMessage, ToolMessage
from langchain_core.outputs import ChatGeneration, ChatGenerationChunk, ChatResult
from langchain_core.prompt_values import ChatPromptValue, PromptValue
from langchain_core.prompts import ChatPromptTemplate, PromptTemplate
from langchain_core.runnables import RunnableLambda
from langchain_core.utils.function_calling import convert_to_openai_tool
from pydantic import BaseModel
from pydantic import PrivateAttr
from zhipuai import ZhipuAI

from backend.core.config_manager import ConfigManager, get_config_manager
from backend.utils.logger import get_logger


logger = get_logger(__name__)

# StructuredOutputT 用于声明“结构化输出模型”的泛型类型边界。
# 这样调用 `with_structured_output()` 时，可以把返回值类型约束到具体的 Pydantic 模型。
StructuredOutputT = TypeVar("StructuredOutputT", bound=BaseModel)


class RuntimeBackedLangChainChatModel(BaseChatModel):
    """基于项目运行时封装的 LangChain 原生聊天模型。

    说明：
    - 该模型负责把 LangChain `BaseMessage` 转换为供应商兼容的消息结构；
    - 当上层通过 `bind_tools()` 绑定工具时，会把标准 OpenAI tool schema 透传给底层 provider；
    - 返回结果统一映射为 `AIMessage`，其中工具调用写入 `tool_calls` 字段。
    """

    _runtime: "LangChainModelRuntime" = PrivateAttr()
    _default_options: ModelCallOptions = PrivateAttr()

    def __init__(
        self,
        runtime: "LangChainModelRuntime",
        default_options: Optional[ModelCallOptions] = None,
        **kwargs: Any,
    ) -> None:
        super().__init__(**kwargs)
        self._runtime = runtime
        self._default_options = default_options or ModelCallOptions()

    @property
    def _llm_type(self) -> str:
        """返回 LangChain 所需的模型类型标识。"""
        return f"project_{self._runtime.provider}_chat_model"

    @property
    def _identifying_params(self) -> Dict[str, Any]:
        """返回模型识别参数，便于 LangChain 做缓存与调试。"""
        return {
            "provider": self._runtime.provider,
            "model_name": self._runtime.model_name,
            "model_type": self._runtime.model_type,
        }

    def bind_tools(self, tools: Sequence[Any], *, tool_choice: str | None = None, **kwargs: Any):
        """返回绑定了原生工具 schema 的 Runnable。"""
        formatted_tools = [convert_to_openai_tool(tool) for tool in tools]
        bind_kwargs = dict(kwargs)
        bind_kwargs["tools"] = formatted_tools
        if tool_choice is not None:
            bind_kwargs["tool_choice"] = tool_choice
        return self.bind(**bind_kwargs)

    def _generate(
        self,
        messages: List[BaseMessage],
        stop: Optional[List[str]] = None,
        run_manager: Any = None,
        **kwargs: Any,
    ) -> ChatResult:
        """执行一次非流式聊天调用，并返回 LangChain `ChatResult`。"""
        request_messages = self._runtime.serialize_langchain_messages(messages)
        request_options = ModelCallOptions(
            temperature=kwargs.pop("temperature", self._default_options.temperature),
            max_tokens=kwargs.pop("max_tokens", self._default_options.max_tokens),
            top_p=kwargs.pop("top_p", self._default_options.top_p),
            model=kwargs.pop("model", self._default_options.model),
            extra_kwargs=kwargs,
        )
        ai_message = self._runtime.invoke_langchain_chat(
            request_messages,
            request_options,
            stop=stop,
        )
        return ChatResult(generations=[ChatGeneration(message=ai_message)])

    async def _astream(
        self,
        messages: List[BaseMessage],
        stop: Optional[List[str]] = None,
        run_manager: Any = None,
        **kwargs: Any,
    ) -> AsyncGenerator[ChatGenerationChunk, None]:
        """执行一次流式聊天调用，并输出 LangChain `ChatGenerationChunk`。"""
        request_messages = self._runtime.serialize_langchain_messages(messages)
        request_options = ModelCallOptions(
            temperature=kwargs.pop("temperature", self._default_options.temperature),
            max_tokens=kwargs.pop("max_tokens", self._default_options.max_tokens),
            top_p=kwargs.pop("top_p", self._default_options.top_p),
            model=kwargs.pop("model", self._default_options.model),
            extra_kwargs=kwargs,
        )
        if stop:
            request_options = ModelCallOptions(
                temperature=request_options.temperature,
                max_tokens=request_options.max_tokens,
                top_p=request_options.top_p,
                model=request_options.model,
                extra_kwargs={**(request_options.extra_kwargs or {}), "stop": stop},
            )

        async for chunk in self._runtime.stream(request_messages, request_options):
            text = str(chunk or "")
            if not text:
                continue
            yield ChatGenerationChunk(message=AIMessageChunk(content=text), text=text)


@dataclass(frozen=True)
class ModelCallOptions:
    """模型调用参数对象。"""

    # temperature：采样随机性参数，越大结果越发散。
    temperature: Optional[float] = None
    # max_tokens：单次生成允许的最大 token 数。
    max_tokens: Optional[int] = None
    # top_p：核采样参数，用于控制候选 token 的累计概率范围。
    top_p: Optional[float] = None
    # model：允许按次覆盖默认模型名。
    model: Optional[str] = None
    # extra_kwargs：附加底层 SDK 参数，用于兼容特殊扩展能力。
    extra_kwargs: Optional[Dict[str, Any]] = None

    def to_model_kwargs(self) -> Dict[str, Any]:
        """转换为模型底层可消费的参数字典。"""
        # request_kwargs：最终下发给具体模型 SDK 的参数集合。
        request_kwargs: Dict[str, Any] = {}
        if self.temperature is not None:
            request_kwargs["temperature"] = self.temperature
        if self.max_tokens is not None:
            request_kwargs["max_tokens"] = self.max_tokens
        if self.top_p is not None:
            request_kwargs["top_p"] = self.top_p
        if self.model:
            request_kwargs["model"] = self.model
        if self.extra_kwargs:
            request_kwargs.update(self.extra_kwargs)
        return request_kwargs


class LangChainModelRuntime:
    """统一底层模型运行时。

    说明：
    - 该运行时负责读取统一配置并调用具体 Provider；
    - 当前优先支持项目默认的 `zhipu` Provider；
    - 若切换到其他 Provider，仍必须通过统一配置进入本层。
    """

    def __init__(
        self,
        config_manager: Optional[ConfigManager] = None,
        *,
        model_type: str = "primary",
    ) -> None:
        # config_manager：统一配置入口，避免在模型调用层直接散读环境变量。
        self.config_manager = config_manager or get_config_manager()
        # model_type：当前要读取的模型配置分组。
        self.model_type = model_type
        # model_config：从配置中心读取出的原始模型配置。
        self.model_config = self.config_manager.get_model_config(model_type)
        # provider：供应商名称，统一转小写以便后续分支判断。
        self.provider = str(self.model_config.get("provider") or "").lower()
        # model_name：默认模型名。
        self.model_name = str(self.model_config.get("model_name") or "")
        # api_key：访问模型接口所需凭证。
        self.api_key = str(self.model_config.get("api_key") or "")
        # timeout：请求超时时间配置。
        self.timeout = int(self.model_config.get("timeout") or 60)
        # retry_config：统一从配置中心的 `model.retry` 节点读取重试配置，
        # 避免模型配置内部再保留历史别名或并行字段。
        retry_config = self.config_manager.get_retry_config()
        # max_retries：最大重试次数配置。
        self.max_retries = int(retry_config.get("max_retries") or 3)
        # retry_delay：重试间隔秒数，统一使用规范字段 `retry_delay`。
        self.retry_delay = float(retry_config.get("retry_delay") or 1)

        # 关键初始化校验：若核心配置缺失，则尽早失败，避免请求过程中才暴露配置问题。
        if not self.provider:
            raise ValueError(f"模型配置缺少 provider: {model_type}")
        if not self.model_name:
            raise ValueError(f"模型配置缺少 model_name: {model_type}")
        if not self.api_key:
            raise ValueError(f"模型配置缺少 api_key: {model_type}")

        # 当前仓库默认主模型为智谱，因此直接优先初始化 zhipu 客户端。
        if self.provider == "zhipu":
            self.client = ZhipuAI(api_key=self.api_key)
        elif self.provider == "openai":
            try:
                from openai import OpenAI
            except Exception as error:  # pragma: no cover - 仅在切换 provider 时触发
                raise RuntimeError("当前环境未安装 openai 依赖，无法初始化 openai provider") from error
            self.client = OpenAI(api_key=self.api_key)
        else:
            raise ValueError(f"暂不支持的模型 provider: {self.provider}")

    async def invoke(self, messages: List[Dict[str, str]], options: ModelCallOptions) -> str:
        """执行非流式模型调用。"""
        # 按 provider 分发到底层具体实现，上层无需感知不同 SDK 的差异。
        if self.provider == "zhipu":
            return await self._invoke_zhipu(messages, options)
        if self.provider == "openai":  # pragma: no cover - 当前默认配置未覆盖
            return await self._invoke_openai(messages, options)
        raise ValueError(f"暂不支持的模型 provider: {self.provider}")

    def get_langchain_chat_model(
        self,
        *,
        options: Optional[ModelCallOptions] = None,
    ) -> RuntimeBackedLangChainChatModel:
        """返回基于当前运行时的 LangChain 原生聊天模型。"""
        return RuntimeBackedLangChainChatModel(runtime=self, default_options=options)

    def serialize_langchain_messages(self, messages: Sequence[BaseMessage]) -> List[Dict[str, Any]]:
        """将 LangChain `BaseMessage` 数组转换为 provider 兼容消息结构。"""
        serialized_messages: List[Dict[str, Any]] = []
        for message in messages:
            if isinstance(message, SystemMessage):
                serialized_messages.append({"role": "system", "content": str(message.content or "")})
                continue
            if isinstance(message, HumanMessage):
                serialized_messages.append({"role": "user", "content": str(message.content or "")})
                continue
            if isinstance(message, ToolMessage):
                serialized_messages.append(
                    {
                        "role": "tool",
                        "content": str(message.content or ""),
                        "tool_call_id": getattr(message, "tool_call_id", None),
                    }
                )
                continue
            if isinstance(message, AIMessage):
                serialized_message: Dict[str, Any] = {
                    "role": "assistant",
                    "content": str(message.content or ""),
                }
                if message.tool_calls:
                    serialized_message["tool_calls"] = [
                        {
                            "id": tool_call.get("id"),
                            "type": "function",
                            "function": {
                                "name": tool_call.get("name"),
                                "arguments": json.dumps(tool_call.get("args", {}), ensure_ascii=False),
                            },
                        }
                        for tool_call in message.tool_calls
                    ]
                serialized_messages.append(serialized_message)
                continue

            serialized_messages.append({"role": "user", "content": str(getattr(message, "content", ""))})
        return serialized_messages

    def invoke_langchain_chat(
        self,
        messages: List[Dict[str, Any]],
        options: ModelCallOptions,
        *,
        stop: Optional[List[str]] = None,
    ) -> AIMessage:
        """执行支持原生工具绑定的聊天调用，并映射为 `AIMessage`。"""
        if self.provider == "zhipu":
            return self._invoke_langchain_chat_zhipu(messages, options, stop=stop)
        if self.provider == "openai":  # pragma: no cover - 当前默认配置未覆盖
            return self._invoke_langchain_chat_openai(messages, options, stop=stop)
        raise ValueError(f"暂不支持的模型 provider: {self.provider}")

    def _build_chat_request_kwargs(
        self,
        messages: List[Dict[str, Any]],
        options: ModelCallOptions,
        *,
        stop: Optional[List[str]] = None,
    ) -> Dict[str, Any]:
        """构造原生聊天调用参数。"""
        request_kwargs: Dict[str, Any] = {
            "model": options.model or self.model_name,
            "messages": messages,
            "temperature": options.temperature if options.temperature is not None else self.model_config.get("temperature", 0.7),
            "max_tokens": options.max_tokens if options.max_tokens is not None else self.model_config.get("max_tokens", 2000),
            "top_p": options.top_p if options.top_p is not None else self.model_config.get("top_p", 0.9),
        }
        if stop:
            request_kwargs["stop"] = stop
        request_kwargs.update(options.extra_kwargs or {})
        return request_kwargs

    def _build_ai_message_from_response(self, response: Any) -> AIMessage:
        """将供应商响应映射为 LangChain `AIMessage`。"""
        if not getattr(response, "choices", None):
            return AIMessage(content="")

        raw_message = response.choices[0].message
        raw_tool_calls = getattr(raw_message, "tool_calls", None) or []
        normalized_tool_calls: List[Dict[str, Any]] = []
        additional_kwargs: Dict[str, Any] = {}
        for raw_tool_call in raw_tool_calls:
            function_payload = getattr(raw_tool_call, "function", None)
            raw_arguments = getattr(function_payload, "arguments", "{}") if function_payload else "{}"
            try:
                parsed_arguments = json.loads(raw_arguments) if isinstance(raw_arguments, str) else dict(raw_arguments or {})
            except Exception:
                parsed_arguments = {}
            normalized_tool_calls.append(
                {
                    "id": getattr(raw_tool_call, "id", None),
                    "type": "tool_call",
                    "name": getattr(function_payload, "name", None) if function_payload else None,
                    "args": parsed_arguments,
                }
            )
        if raw_tool_calls:
            additional_kwargs["tool_calls"] = [
                {
                    "id": getattr(raw_tool_call, "id", None),
                    "type": "function",
                    "function": {
                        "name": getattr(getattr(raw_tool_call, "function", None), "name", None),
                        "arguments": getattr(getattr(raw_tool_call, "function", None), "arguments", "{}"),
                    },
                }
                for raw_tool_call in raw_tool_calls
            ]

        response_metadata = {
            "model": getattr(response, "model", None),
            "finish_reason": getattr(response.choices[0], "finish_reason", None),
        }
        return AIMessage(
            content=str(getattr(raw_message, "content", "") or ""),
            tool_calls=normalized_tool_calls,
            additional_kwargs=additional_kwargs,
            response_metadata=response_metadata,
        )

    def _invoke_langchain_chat_zhipu(
        self,
        messages: List[Dict[str, Any]],
        options: ModelCallOptions,
        *,
        stop: Optional[List[str]] = None,
    ) -> AIMessage:
        """调用智谱原生工具绑定聊天接口。"""
        response = self.client.chat.completions.create(
            **self._build_chat_request_kwargs(messages, options, stop=stop)
        )
        return self._build_ai_message_from_response(response)

    def _invoke_langchain_chat_openai(
        self,
        messages: List[Dict[str, Any]],
        options: ModelCallOptions,
        *,
        stop: Optional[List[str]] = None,
    ) -> AIMessage:
        """调用 OpenAI 原生工具绑定聊天接口。"""
        response = self.client.chat.completions.create(
            **self._build_chat_request_kwargs(messages, options, stop=stop)
        )
        return self._build_ai_message_from_response(response)

    async def stream(self, messages: List[Dict[str, str]], options: ModelCallOptions) -> AsyncGenerator[str, None]:
        """执行流式模型调用，仅返回纯文本分片。"""
        # 统一把流式结果收敛为纯文本 chunk，不向上层暴露供应商原生事件结构。
        if self.provider == "zhipu":
            async for chunk in self._stream_zhipu(messages, options):
                yield chunk
            return
        if self.provider == "openai":  # pragma: no cover - 当前默认配置未覆盖
            async for chunk in self._stream_openai(messages, options):
                yield chunk
            return
        raise ValueError(f"暂不支持的模型 provider: {self.provider}")

    async def _invoke_zhipu(self, messages: List[Dict[str, str]], options: ModelCallOptions) -> str:
        """调用智谱非流式接口。"""
        # request_kwargs：本次请求最终传递给智谱 SDK 的参数。
        request_kwargs = {
            "model": options.model or self.model_name,
            "messages": messages,
            "temperature": options.temperature if options.temperature is not None else self.model_config.get("temperature", 0.7),
            "max_tokens": options.max_tokens if options.max_tokens is not None else self.model_config.get("max_tokens", 2000),
            "top_p": options.top_p if options.top_p is not None else self.model_config.get("top_p", 0.9),
        }
        request_kwargs.update(options.extra_kwargs or {})

        # 核心逻辑：阻塞式 SDK 调用放到线程池执行，避免卡住事件循环。
        response = await asyncio.to_thread(self.client.chat.completions.create, **request_kwargs)
        return str(response.choices[0].message.content or "") if response.choices else ""

    async def _stream_zhipu(self, messages: List[Dict[str, str]], options: ModelCallOptions) -> AsyncGenerator[str, None]:
        """调用智谱流式接口，并把 SDK 分片映射为纯文本。"""
        # request_kwargs：流式请求参数，必须显式开启 `stream=True`。
        request_kwargs = {
            "model": options.model or self.model_name,
            "messages": messages,
            "temperature": options.temperature if options.temperature is not None else self.model_config.get("temperature", 0.7),
            "max_tokens": options.max_tokens if options.max_tokens is not None else self.model_config.get("max_tokens", 2000),
            "top_p": options.top_p if options.top_p is not None else self.model_config.get("top_p", 0.9),
            "stream": True,
        }
        request_kwargs.update(options.extra_kwargs or {})

        # loop：当前事件循环，用于从工作线程向异步上下文安全投递数据。
        loop = asyncio.get_running_loop()
        # queue：线程和协程之间的通信队列。
        queue: asyncio.Queue[Any] = asyncio.Queue()
        # sentinel：流式结束哨兵，用于通知消费循环退出。
        sentinel = object()

        def _worker() -> None:
            # 核心逻辑：在后台线程中同步遍历 SDK 流式响应，再把文本分片回传到异步队列。
            try:
                response = self.client.chat.completions.create(**request_kwargs)
                for chunk in response:
                    if not chunk.choices:
                        continue
                    delta = chunk.choices[0].delta
                    content = getattr(delta, "content", None)
                    if not content:
                        continue
                    asyncio.run_coroutine_threadsafe(queue.put(str(content)), loop).result()
            except Exception as error:  # pragma: no cover - 真实 SDK 异常路径
                # 线程中的异常也通过队列回传，保证外层统一在异步消费端处理。
                asyncio.run_coroutine_threadsafe(queue.put(error), loop).result()
            finally:
                # 无论成功还是失败，都必须发送结束标记，避免消费者永久等待。
                asyncio.run_coroutine_threadsafe(queue.put(sentinel), loop).result()

        # 启动后台线程执行阻塞式流读取。
        asyncio.create_task(asyncio.to_thread(_worker))

        while True:
            item = await queue.get()
            if item is sentinel:
                break
            if isinstance(item, Exception):
                raise item
            yield str(item)

    async def _invoke_openai(self, messages: List[Dict[str, str]], options: ModelCallOptions) -> str:
        """调用 OpenAI 非流式接口。"""
        # 与智谱分支保持一致的参数构造方式，便于 provider 横向替换。
        request_kwargs = {
            "model": options.model or self.model_name,
            "messages": messages,
            "temperature": options.temperature if options.temperature is not None else self.model_config.get("temperature", 0.7),
            "max_tokens": options.max_tokens if options.max_tokens is not None else self.model_config.get("max_tokens", 2000),
            "top_p": options.top_p if options.top_p is not None else self.model_config.get("top_p", 0.9),
        }
        request_kwargs.update(options.extra_kwargs or {})
        response = await asyncio.to_thread(self.client.chat.completions.create, **request_kwargs)
        return str(response.choices[0].message.content or "") if response.choices else ""

    async def _stream_openai(self, messages: List[Dict[str, str]], options: ModelCallOptions) -> AsyncGenerator[str, None]:
        """调用 OpenAI 流式接口，并映射为纯文本。"""
        # 同样只向上层输出纯文本，不透出 OpenAI SDK 的 chunk 结构。
        request_kwargs = {
            "model": options.model or self.model_name,
            "messages": messages,
            "temperature": options.temperature if options.temperature is not None else self.model_config.get("temperature", 0.7),
            "max_tokens": options.max_tokens if options.max_tokens is not None else self.model_config.get("max_tokens", 2000),
            "top_p": options.top_p if options.top_p is not None else self.model_config.get("top_p", 0.9),
            "stream": True,
        }
        request_kwargs.update(options.extra_kwargs or {})

        loop = asyncio.get_running_loop()
        queue: asyncio.Queue[Any] = asyncio.Queue()
        sentinel = object()

        def _worker() -> None:
            try:
                response = self.client.chat.completions.create(**request_kwargs)
                for chunk in response:
                    if not chunk.choices:
                        continue
                    delta = chunk.choices[0].delta
                    content = getattr(delta, "content", None)
                    if not content:
                        continue
                    asyncio.run_coroutine_threadsafe(queue.put(str(content)), loop).result()
            except Exception as error:  # pragma: no cover - 真实 SDK 异常路径
                asyncio.run_coroutine_threadsafe(queue.put(error), loop).result()
            finally:
                asyncio.run_coroutine_threadsafe(queue.put(sentinel), loop).result()

        asyncio.create_task(asyncio.to_thread(_worker))

        while True:
            item = await queue.get()
            if item is sentinel:
                break
            if isinstance(item, Exception):
                raise item
            yield str(item)


class LangChainModelManager:
    """统一模型交互入口。"""

    def __init__(
        self,
        runtime: Optional[LangChainModelRuntime] = None,
        *,
        structured_output_schema: type[BaseModel] | None = None,
        bound_tools: Optional[List[Any]] = None,
    ) -> None:
        # runtime：底层模型运行时，负责屏蔽不同 provider 的调用细节。
        self.runtime = runtime or LangChainModelRuntime()
        # structured_output_schema：结构化输出约束；存在时表示需要把文本结果解析成 Pydantic 模型。
        self.structured_output_schema = structured_output_schema
        # bound_tools：当前实例绑定的工具定义列表。
        self.bound_tools = bound_tools or []

    def with_structured_output(self, output_schema: type[StructuredOutputT]) -> "LangChainModelManager":
        """返回绑定了结构化输出约束的新实例。"""
        # 关键设计：返回新实例而不是原地修改，避免同一个 manager 被多处复用时互相污染状态。
        return LangChainModelManager(
            runtime=self.runtime,
            structured_output_schema=output_schema,
            bound_tools=self.bound_tools,
        )

    def bind_tools(self, tools: Sequence[Any]) -> "LangChainModelManager":
        """返回绑定了 LangChain 原生工具的新实例。"""
        return LangChainModelManager(
            runtime=self.runtime,
            structured_output_schema=self.structured_output_schema,
            bound_tools=list(tools),
        )

    async def invoke_prompt_template(
        self,
        prompt_template: PromptTemplate,
        prompt_variables: Dict[str, Any],
        *,
        system_prompt: Optional[str] = None,
        temperature: Optional[float] = None,
        max_tokens: Optional[int] = None,
        top_p: Optional[float] = None,
        model: Optional[str] = None,
        **kwargs: Any,
    ) -> str | BaseModel:
        """执行 `PromptTemplate` 调用。"""
        # 先执行模板变量渲染，拿到 PromptValue。
        prompt_value = RunnableLambda(lambda variables: prompt_template.invoke(variables)).invoke(prompt_variables)
        # 再转换成项目内部统一 messages 结构，方便后续统一走同一条调用链。
        messages = self._build_prompt_messages(self._prompt_value_to_text(prompt_value), system_prompt=system_prompt)
        return await self._invoke_with_messages(messages, temperature, max_tokens, top_p, model, **kwargs)

    async def stream_prompt_template(
        self,
        prompt_template: PromptTemplate,
        prompt_variables: Dict[str, Any],
        *,
        system_prompt: Optional[str] = None,
        temperature: Optional[float] = None,
        max_tokens: Optional[int] = None,
        top_p: Optional[float] = None,
        model: Optional[str] = None,
        **kwargs: Any,
    ) -> AsyncGenerator[str, None]:
        """流式执行 `PromptTemplate` 调用。"""
        # 当前结构化输出和工具绑定仅支持非流式，因此先做能力保护。
        self._ensure_streaming_supported()
        prompt_value = RunnableLambda(lambda variables: prompt_template.invoke(variables)).invoke(prompt_variables)
        messages = self._build_prompt_messages(self._prompt_value_to_text(prompt_value), system_prompt=system_prompt)
        async for chunk in self._stream_with_messages(messages, temperature, max_tokens, top_p, model, **kwargs):
            yield chunk

    async def invoke_chat_prompt_template(
        self,
        prompt_template: ChatPromptTemplate,
        prompt_variables: Dict[str, Any],
        *,
        temperature: Optional[float] = None,
        max_tokens: Optional[int] = None,
        top_p: Optional[float] = None,
        model: Optional[str] = None,
        **kwargs: Any,
    ) -> str | BaseModel:
        """执行 `ChatPromptTemplate` 调用。"""
        # ChatPromptTemplate 渲染后可以直接转换成多角色消息数组。
        prompt_value = RunnableLambda(lambda variables: prompt_template.invoke(variables)).invoke(prompt_variables)
        messages = self._prompt_value_to_api_messages(prompt_value)
        return await self._invoke_with_messages(messages, temperature, max_tokens, top_p, model, **kwargs)

    async def stream_chat_prompt_template(
        self,
        prompt_template: ChatPromptTemplate,
        prompt_variables: Dict[str, Any],
        *,
        temperature: Optional[float] = None,
        max_tokens: Optional[int] = None,
        top_p: Optional[float] = None,
        model: Optional[str] = None,
        **kwargs: Any,
    ) -> AsyncGenerator[str, None]:
        """流式执行 `ChatPromptTemplate` 调用。"""
        # 流式执行前先确认当前配置组合允许使用流式。
        self._ensure_streaming_supported()
        prompt_value = RunnableLambda(lambda variables: prompt_template.invoke(variables)).invoke(prompt_variables)
        messages = self._prompt_value_to_api_messages(prompt_value)
        async for chunk in self._stream_with_messages(messages, temperature, max_tokens, top_p, model, **kwargs):
            yield chunk

    async def invoke_messages(
        self,
        messages: Sequence[Dict[str, Any]],
        *,
        temperature: Optional[float] = None,
        max_tokens: Optional[int] = None,
        top_p: Optional[float] = None,
        model: Optional[str] = None,
        **kwargs: Any,
    ) -> str | BaseModel:
        """执行项目内部消息数组调用。"""
        # 这里必须直接保留内部消息结构，不能先回退成 ChatPromptTemplate。
        # 否则 assistant.tool_calls / tool.tool_call_id 等协议字段会在模板重建阶段丢失，
        # 从而破坏标准 LangChain tool loop 的第二轮及后续轮次。
        return await self._invoke_with_messages(
            messages,
            temperature,
            max_tokens,
            top_p,
            model,
            **kwargs,
        )

    async def stream_messages(
        self,
        messages: Sequence[Dict[str, Any]],
        *,
        temperature: Optional[float] = None,
        max_tokens: Optional[int] = None,
        top_p: Optional[float] = None,
        model: Optional[str] = None,
        **kwargs: Any,
    ) -> AsyncGenerator[str, None]:
        """流式执行项目内部消息数组调用。"""
        async for chunk in self._stream_with_messages(
            messages,
            temperature,
            max_tokens,
            top_p,
            model,
            **kwargs,
        ):
            yield chunk

    async def _invoke_with_messages(
        self,
        messages: Sequence[Dict[str, str]],
        temperature: Optional[float],
        max_tokens: Optional[int],
        top_p: Optional[float],
        model: Optional[str],
        **kwargs: Any,
    ) -> str | BaseModel:
        """执行统一消息调用，并在需要时解析结构化结果。"""
        options = self._build_options(
            temperature=temperature,
            max_tokens=max_tokens,
            top_p=top_p,
            model=model,
            extra_kwargs=kwargs,
        )
        chat_model = self.runtime.get_langchain_chat_model(options=options)
        langchain_messages = self._api_messages_to_langchain_messages(messages)

        if self.bound_tools and self.structured_output_schema is not None:
            raise ValueError("请分别使用标准 LangChain 的 bind_tools() 或 with_structured_output() 链路")

        if self.structured_output_schema is not None:
            try:
                structured_runnable = chat_model.with_structured_output(self.structured_output_schema)
                return await structured_runnable.ainvoke(langchain_messages)
            except Exception as error:
                logger.warning(
                    "Native structured output failed; fallback to JSON parsing. provider=%s model=%s error=%s",
                    getattr(self.runtime, "provider", "unknown"),
                    getattr(self.runtime, "model_name", "unknown"),
                    error,
                )
                return await self._invoke_structured_output_fallback(
                    chat_model=chat_model,
                    langchain_messages=langchain_messages,
                )

        if self.bound_tools:
            bound_runnable = chat_model.bind_tools(self.bound_tools)
            return await bound_runnable.ainvoke(langchain_messages)

        ai_message = await chat_model.ainvoke(langchain_messages)
        return str(getattr(ai_message, "content", "") or "")

    async def _invoke_structured_output_fallback(
        self,
        *,
        chat_model: BaseChatModel,
        langchain_messages: Sequence[BaseMessage],
    ) -> BaseModel:
        """在原生 structured output 不兼容时，回退到文本 JSON + 本地解析。"""
        if self.structured_output_schema is None:
            raise ValueError("structured_output_schema 未配置，无法执行结构化回退")

        schema_json = json.dumps(self.structured_output_schema.model_json_schema(), ensure_ascii=False)
        fallback_instruction = (
            "请严格返回单个 JSON 对象，不要输出任何解释、Markdown 或代码块。"
            "返回结果必须满足以下 JSON Schema："
            f"{schema_json}"
        )
        fallback_messages = [
            SystemMessage(content=fallback_instruction),
            *list(langchain_messages),
        ]
        ai_message = await chat_model.ainvoke(fallback_messages)
        response_text = self._stringify_ai_content(getattr(ai_message, "content", ""))
        return self._parse_structured_output_text(response_text)

    def _parse_structured_output_text(self, response_text: str) -> BaseModel:
        """把模型文本结果解析为结构化输出模型。"""
        if self.structured_output_schema is None:
            raise ValueError("structured_output_schema 未配置，无法解析结构化结果")

        normalized_text = response_text.strip()
        candidate_payloads = [normalized_text]

        fenced_payload = self._extract_fenced_json(normalized_text)
        if fenced_payload:
            candidate_payloads.append(fenced_payload)

        json_object_payload = self._extract_json_object(normalized_text)
        if json_object_payload:
            candidate_payloads.append(json_object_payload)

        parse_errors: list[str] = []
        for payload in candidate_payloads:
            if not payload:
                continue
            try:
                return self.structured_output_schema.model_validate_json(payload)
            except Exception as error:
                parse_errors.append(str(error))

        raise ValueError(
            "结构化输出解析失败: "
            f"response={response_text!r}, errors={parse_errors}"
        )

    @staticmethod
    def _stringify_ai_content(content: Any) -> str:
        """把不同形态的 AIMessage content 统一折叠为字符串。"""
        if isinstance(content, str):
            return content
        if isinstance(content, list):
            fragments: List[str] = []
            for item in content:
                if isinstance(item, str):
                    fragments.append(item)
                    continue
                if isinstance(item, dict):
                    text_value = item.get("text")
                    if isinstance(text_value, str):
                        fragments.append(text_value)
            return "".join(fragments)
        return str(content or "")

    @staticmethod
    def _extract_fenced_json(response_text: str) -> str | None:
        """提取 ```json ... ``` 或 ``` ... ``` 包裹的 JSON。"""
        stripped = response_text.strip()
        if not stripped.startswith("```"):
            return None

        lines = stripped.splitlines()
        if len(lines) < 3:
            return None
        if not lines[-1].strip().startswith("```"):
            return None
        return "\n".join(lines[1:-1]).strip()

    @staticmethod
    def _extract_json_object(response_text: str) -> str | None:
        """从文本中提取最外层 JSON 对象。"""
        start = response_text.find("{")
        end = response_text.rfind("}")
        if start == -1 or end == -1 or end <= start:
            return None
        return response_text[start : end + 1].strip()

    async def _stream_with_messages(
        self,
        messages: Sequence[Dict[str, str]],
        temperature: Optional[float],
        max_tokens: Optional[int],
        top_p: Optional[float],
        model: Optional[str],
        **kwargs: Any,
    ) -> AsyncGenerator[str, None]:
        """执行统一流式消息调用。"""
        # 中文说明：流式链路必须与非流式链路保持一致的能力边界，
        # 禁止在已绑定 tool / structured output 时悄悄退化成普通文本流。
        self._ensure_streaming_supported()
        options = self._build_options(
            temperature=temperature,
            max_tokens=max_tokens,
            top_p=top_p,
            model=model,
            extra_kwargs=kwargs,
        )
        chat_model = self.runtime.get_langchain_chat_model(options=options)
        langchain_messages = self._api_messages_to_langchain_messages(messages)
        async for chunk in chat_model.astream(langchain_messages):
            content = getattr(chunk, "content", None)
            if isinstance(content, str) and content:
                yield content

    def _ensure_streaming_supported(self) -> None:
        """结构化输出与工具绑定阶段不直接暴露流式接口。"""
        # 限制原因：
        # 1. 结构化输出需要等待完整 JSON 后才能解析；
        # 2. 工具绑定当前是一次性决策模式，未设计流式增量协议。
        if self.structured_output_schema is not None or self.bound_tools:
            raise ValueError("当前结构化输出/工具绑定链路仅支持非流式调用")

    def _api_messages_to_langchain_messages(self, messages: Sequence[Dict[str, Any]]) -> List[BaseMessage]:
        """把项目内部消息结构映射为 LangChain `BaseMessage`。"""
        langchain_messages: List[BaseMessage] = []
        for message in messages:
            role = self._normalize_role(message.get("role"))
            content = str(message.get("content", ""))
            if role == "system":
                langchain_messages.append(SystemMessage(content=content))
            elif role == "assistant":
                raw_tool_calls = message.get("tool_calls")
                if isinstance(raw_tool_calls, list) and raw_tool_calls:
                    normalized_tool_calls = []
                    for tool_call in raw_tool_calls:
                        if not isinstance(tool_call, dict):
                            continue
                        normalized_tool_calls.append(
                            {
                                "id": tool_call.get("id"),
                                "type": "tool_call",
                                "name": tool_call.get("name"),
                                "args": tool_call.get("args") if isinstance(tool_call.get("args"), dict) else {},
                            }
                        )
                    langchain_messages.append(AIMessage(content=content, tool_calls=normalized_tool_calls))
                else:
                    langchain_messages.append(AIMessage(content=content))
            elif role == "tool":
                tool_call_id = str(message.get("tool_call_id") or "")
                if not tool_call_id:
                    raise ValueError("tool 角色消息缺少 tool_call_id")
                tool_name = message.get("name")
                status = "error" if str(message.get("status") or "success") == "error" else "success"
                langchain_messages.append(
                    ToolMessage(
                        content=content,
                        tool_call_id=tool_call_id,
                        name=str(tool_name) if tool_name else None,
                        status=status,
                    )
                )
            else:
                langchain_messages.append(HumanMessage(content=content))
        return langchain_messages

    def _build_options(
        self,
        *,
        temperature: Optional[float],
        max_tokens: Optional[int],
        top_p: Optional[float],
        model: Optional[str],
        extra_kwargs: Optional[Dict[str, Any]],
    ) -> ModelCallOptions:
        """构造统一模型参数对象。"""
        # 深拷贝额外参数，避免调用方后续修改原始字典影响已生成的配置对象。
        return ModelCallOptions(
            temperature=temperature,
            max_tokens=max_tokens,
            top_p=top_p,
            model=model,
            extra_kwargs=deepcopy(extra_kwargs or {}),
        )

    def _build_prompt_messages(self, prompt_text: str, *, system_prompt: Optional[str] = None) -> List[Dict[str, str]]:
        """把普通 Prompt 文本转换为项目内部消息数组。"""
        # messages：项目内部统一消息结构，统一使用 role/content 两个核心字段。
        messages: List[Dict[str, str]] = []
        if system_prompt:
            messages.append({"role": "system", "content": system_prompt})
        messages.append({"role": "user", "content": prompt_text})
        return messages

    def _build_chat_prompt_template(self, messages: Sequence[Dict[str, Any]]) -> tuple[ChatPromptTemplate, Dict[str, str]]:
        """把项目内部消息数组包装为 `ChatPromptTemplate`。"""
        # template_messages：ChatPromptTemplate 需要的模板消息定义。
        template_messages: List[tuple[str, str]] = []
        # prompt_variables：每条消息内容对应的模板变量字典。
        prompt_variables: Dict[str, str] = {}
        for index, message in enumerate(messages):
            # variable_name：为每条消息生成唯一变量名，避免覆盖。
            variable_name = f"message_{index}"
            role = self._normalize_role(message.get("role"))
            prompt_variables[variable_name] = str(message.get("content", ""))
            template_messages.append((role, "{" + variable_name + "}"))
        return ChatPromptTemplate.from_messages(template_messages), prompt_variables

    def _prompt_value_to_text(self, prompt_value: PromptValue) -> str:
        """从 `PromptValue` 提取字符串内容。"""
        # 优先走标准接口 `to_string()`，保证与 LangChain 官方对象行为兼容。
        if hasattr(prompt_value, "to_string"):
            return str(prompt_value.to_string())
        return str(prompt_value)

    def _prompt_value_to_api_messages(self, prompt_value: ChatPromptValue | PromptValue) -> List[Dict[str, str]]:
        """把 `ChatPromptValue` 映射为项目内部消息数组。"""
        # prompt_messages：LangChain 原生消息对象列表。
        prompt_messages = prompt_value.to_messages() if hasattr(prompt_value, "to_messages") else []
        # api_messages：转换后的内部消息数组。
        api_messages: List[Dict[str, str]] = []
        for message in prompt_messages:
            role = self._normalize_role(getattr(message, "type", "user"))
            api_messages.append({"role": role, "content": str(getattr(message, "content", ""))})
        return api_messages

    def _normalize_role(self, role: Any) -> str:
        """统一不同消息角色到项目内部角色集合。"""
        # normalized_role：统一转小写并处理别名，收敛成项目内部固定角色集。
        normalized_role = str(role or "user").lower()
        if normalized_role in {"human", "user"}:
            return "user"
        if normalized_role in {"assistant", "ai"}:
            return "assistant"
        if normalized_role == "system":
            return "system"
        if normalized_role == "tool":
            return "tool"
        return "user"


_langchain_model_manager: Optional[LangChainModelManager] = None


def get_langchain_model_manager() -> LangChainModelManager:
    """获取基于 LangChain Runnable 的模型交互管理器单例。"""
    global _langchain_model_manager
    # 懒加载单例：首次使用时才初始化，减少无意义的启动开销。
    if _langchain_model_manager is None:
        _langchain_model_manager = LangChainModelManager()
    return _langchain_model_manager


__all__ = [
    "LangChainModelManager",
    "LangChainModelRuntime",
    "ModelCallOptions",
    "get_langchain_model_manager",
]

