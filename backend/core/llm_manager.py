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
import re
from copy import deepcopy
from dataclasses import dataclass
from typing import Any, AsyncGenerator, Dict, List, Optional, Sequence, TypeVar

from langchain_core.prompt_values import ChatPromptValue, PromptValue
from langchain_core.prompts import ChatPromptTemplate, PromptTemplate
from langchain_core.runnables import RunnableLambda
from pydantic import BaseModel, Field, ValidationError
from zhipuai import ZhipuAI

from backend.core.config_manager import ConfigManager, get_config_manager
from backend.utils.logger import get_logger


logger = get_logger(__name__)

# StructuredOutputT 用于声明“结构化输出模型”的泛型类型边界。
# 这样调用 `with_structured_output()` 时，可以把返回值类型约束到具体的 Pydantic 模型。
StructuredOutputT = TypeVar("StructuredOutputT", bound=BaseModel)


class ToolBindingInstruction(BaseModel):
    """工具绑定阶段使用的统一工具描述。"""

    # name：工具名称，是模型选择工具时使用的唯一标识。
    name: str
    # description：工具用途说明，帮助模型理解什么时候应该使用该工具。
    description: str = ""
    # input_schema：工具输入参数的 Schema 定义，用于约束模型生成的调用参数结构。
    input_schema: Dict[str, Any] = Field(default_factory=dict)


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

        response = await asyncio.to_thread(self.client.chat.completions.create, **request_kwargs)
        for chunk in response:  # pragma: no cover - 当前默认配置未覆盖
            if not chunk.choices:
                continue
            delta = chunk.choices[0].delta
            content = getattr(delta, "content", None)
            if content:
                yield str(content)


class LangChainModelManager:
    """统一模型交互入口。"""

    def __init__(
        self,
        runtime: Optional[LangChainModelRuntime] = None,
        *,
        structured_output_schema: type[BaseModel] | None = None,
        bound_tools: Optional[List[ToolBindingInstruction]] = None,
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

    def bind_tools(self, tools: Sequence[Dict[str, Any] | ToolBindingInstruction]) -> "LangChainModelManager":
        """返回绑定了工具描述的新实例。"""
        # 先做工具定义归一化，兼容多种历史字段命名。
        normalized_tools = [self._normalize_tool_definition(tool) for tool in tools]
        return LangChainModelManager(
            runtime=self.runtime,
            structured_output_schema=self.structured_output_schema,
            bound_tools=normalized_tools,
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
        # 项目内部原生消息结构先包装成 ChatPromptTemplate，再复用统一调用逻辑。
        prompt_template, prompt_variables = self._build_chat_prompt_template(messages)
        return await self.invoke_chat_prompt_template(
            prompt_template,
            prompt_variables,
            temperature=temperature,
            max_tokens=max_tokens,
            top_p=top_p,
            model=model,
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
        # 非流式与流式共用同一套消息模板转换逻辑，减少重复代码。
        prompt_template, prompt_variables = self._build_chat_prompt_template(messages)
        async for chunk in self.stream_chat_prompt_template(
            prompt_template,
            prompt_variables,
            temperature=temperature,
            max_tokens=max_tokens,
            top_p=top_p,
            model=model,
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
        # decorated_messages：附加系统约束后的最终消息数组。
        decorated_messages = self._decorate_messages(messages)
        # options：统一调用参数对象。
        options = self._build_options(
            temperature=temperature,
            max_tokens=max_tokens,
            top_p=top_p,
            model=model,
            extra_kwargs=kwargs,
        )
        # 先拿到底层模型返回的原始文本结果。
        raw_text = await self.runtime.invoke(decorated_messages, options)
        if self.structured_output_schema is None:
            return raw_text
        # 若声明了结构化输出，则由本层负责做 JSON 提取和 Schema 校验。
        return self._parse_structured_output(raw_text)

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
        # 流式路径同样先注入系统约束，再交给运行时逐片返回文本。
        decorated_messages = self._decorate_messages(messages)
        options = self._build_options(
            temperature=temperature,
            max_tokens=max_tokens,
            top_p=top_p,
            model=model,
            extra_kwargs=kwargs,
        )
        async for chunk in self.runtime.stream(decorated_messages, options):
            yield chunk

    def _ensure_streaming_supported(self) -> None:
        """结构化输出与工具绑定阶段不直接暴露流式接口。"""
        # 限制原因：
        # 1. 结构化输出需要等待完整 JSON 后才能解析；
        # 2. 工具绑定当前是一次性决策模式，未设计流式增量协议。
        if self.structured_output_schema is not None or self.bound_tools:
            raise ValueError("当前结构化输出/工具绑定链路仅支持非流式调用")

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

    def _decorate_messages(self, messages: Sequence[Dict[str, str]]) -> List[Dict[str, str]]:
        """在消息数组前附加结构化输出与工具绑定指令。"""
        # 先复制输入，避免对调用方传入的数据产生副作用。
        decorated_messages = [dict(message) for message in messages]
        # instruction_parts：所有附加系统约束说明。
        instruction_parts: List[str] = []
        if self.bound_tools:
            instruction_parts.append(self._build_tool_binding_instruction())
        if self.structured_output_schema is not None:
            instruction_parts.append(self._build_structured_output_instruction(self.structured_output_schema))
        if instruction_parts:
            # 关键逻辑：统一在最前面插入一条 system 消息，保证约束优先级最高。
            decorated_messages.insert(0, {"role": "system", "content": "\n\n".join(instruction_parts)})
        return decorated_messages

    def _build_structured_output_instruction(self, output_schema: type[BaseModel]) -> str:
        """构造结构化输出约束说明。"""
        # ensure_ascii=False：保留中文字符，保证注入给模型的 Schema 文本可直接阅读。
        schema_json = json.dumps(output_schema.model_json_schema(), ensure_ascii=False, indent=2)
        return (
            "请严格返回 JSON 对象，不要输出额外解释、Markdown 代码块或前后缀文本。\n"
            f"输出 JSON 必须满足以下 Schema：\n{schema_json}"
        )

    def _build_tool_binding_instruction(self) -> str:
        """构造工具绑定说明。"""
        # 将工具列表序列化为 JSON 文本，便于模型按统一结构理解每个工具的名称与参数。
        tools_json = json.dumps([tool.model_dump() for tool in self.bound_tools], ensure_ascii=False, indent=2)
        return (
            "你当前处于工具绑定决策模式。\n"
            "你只能在给定工具集合中选择最合适的工具，或者明确返回不调用工具。\n"
            f"可用工具定义如下：\n{tools_json}"
        )

    def _parse_structured_output(self, raw_text: str) -> BaseModel:
        """把模型原始文本解析为结构化对象。"""
        if self.structured_output_schema is None:
            raise ValueError("未配置结构化输出 Schema")

        # 第一步：尽量从模型结果文本中提取出 JSON 主体。
        json_payload = self._extract_json_payload(raw_text)
        try:
            # 第二步：把 JSON 文本解析成 Python 对象。
            parsed_payload = json.loads(json_payload)
        except json.JSONDecodeError as error:
            logger.error("结构化输出 JSON 解析失败: %s; raw=%s", error, raw_text)
            raise ValueError(f"结构化输出 JSON 解析失败: {error}") from error

        try:
            # 第三步：使用目标 Pydantic Schema 做严格校验，保证输出契约稳定。
            return self.structured_output_schema.model_validate(parsed_payload)
        except ValidationError as error:
            logger.error("结构化输出 Schema 校验失败: %s; payload=%s", error, parsed_payload)
            raise ValueError(f"结构化输出 Schema 校验失败: {error}") from error

    def _extract_json_payload(self, raw_text: str) -> str:
        """尽量从模型结果中提取 JSON 片段。"""
        if not isinstance(raw_text, str):
            raise ValueError("结构化输出原文不是字符串")

        # 优先提取 ```json ... ``` 代码块，这是最常见的模型输出格式。
        fenced_match = re.search(r"```json\s*(.*?)\s*```", raw_text, flags=re.DOTALL | re.IGNORECASE)
        if fenced_match:
            return fenced_match.group(1).strip()

        # 其次兼容没有显式 json 标识的普通代码块。
        generic_fenced_match = re.search(r"```\s*(.*?)\s*```", raw_text, flags=re.DOTALL)
        if generic_fenced_match:
            return generic_fenced_match.group(1).strip()

        # 最后尝试直接提取大括号包裹的 JSON 对象文本作为兜底。
        json_match = re.search(r"\{.*\}", raw_text, flags=re.DOTALL)
        if json_match:
            return json_match.group(0).strip()

        raise ValueError("未从模型输出中提取到 JSON 对象")

    def _normalize_tool_definition(self, tool: Dict[str, Any] | ToolBindingInstruction) -> ToolBindingInstruction:
        """把不同形态的工具描述统一为绑定指令对象。"""
        if isinstance(tool, ToolBindingInstruction):
            return tool
        if not isinstance(tool, dict):
            raise TypeError("工具绑定定义必须是 dict 或 ToolBindingInstruction")

        # 兼容不同来源工具定义的字段差异。
        input_schema = tool.get("input_schema") or tool.get("parameters") or tool.get("args_schema") or {}
        return ToolBindingInstruction(
            name=str(tool.get("name") or tool.get("tool_name") or ""),
            description=str(tool.get("description") or ""),
            input_schema=deepcopy(input_schema if isinstance(input_schema, dict) else {}),
        )

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
    "ToolBindingInstruction",
    "get_langchain_model_manager",
]
