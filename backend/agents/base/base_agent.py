# -*- coding: utf-8 -*-
"""所有 Agent 的抽象基类。

本模块为各类 Agent 提供统一基础能力：
- 配置读取；
- Prompt 读取；
- 结构化日志；
- 输入校验；
- 统一错误处理；
- 非流式与流式执行的安全包装。

子类只需要关注自身核心业务逻辑：
- `execute`：返回一次性完整结果；
- `execute_stream`：按块输出流式结果。
"""

from abc import ABC, abstractmethod
from copy import deepcopy
from dataclasses import fields
from typing import Optional, Dict, Any, AsyncGenerator
import time

from backend.contracts.errors import ErrorCode
from backend.core.config_manager import ConfigManager, get_config_manager
from backend.core.prompt_manager import PromptManager, get_prompt_manager
from backend.utils.error_utils import build_error_metadata, sanitize_error_message
from backend.utils.logger import get_logger
from backend.agents.base.agent_input import AgentInput
from backend.agents.base.agent_output import (
    AgentOutput,
    ExecutionStatus,
    FileProcessorAgentOutput,
    GenerationAgentOutput,
    RetrievalAgentOutput,
    ToolAgentOutput,
)
from backend.agents.base.stream_chunk import StreamChunk


class BaseAgent(ABC):
    """多 Agent 体系的统一抽象基类。"""

    # `OUTPUT_CLASS_BY_TYPE`：Agent 类型到输出模型的映射表。
    # 这样基类就能按 `agent_type` 自动构造对应输出对象，避免子类重复判断。
    OUTPUT_CLASS_BY_TYPE = {
        "retrieval": RetrievalAgentOutput,
        "generation": GenerationAgentOutput,
        "tool": ToolAgentOutput,
        "file_processor": FileProcessorAgentOutput,
    }

    def __init__(
        self,
        agent_name: str,
        agent_type: str,
        config_manager: Optional[ConfigManager] = None,
        prompt_manager: Optional[PromptManager] = None,
    ):
        """初始化 Agent 运行所需的基础依赖。

        关键逻辑：
        - 若外部未注入配置中心，则使用全局单例；
        - 若外部未注入 PromptManager，则使用全局单例；
        - 预读取当前 Agent 对应配置，避免业务代码散读配置；
        - 初始化专属 logger，便于按 Agent 维度排障。
        """
        # `agent_name`：Agent 的实例名称，主要用于日志与调试展示。
        self.agent_name = agent_name
        # `agent_type`：Agent 类型名称，通常决定 prompt 与配置命名空间。
        self.agent_type = agent_type
        # `config_manager`：统一配置访问入口。
        self.config_manager = config_manager or get_config_manager()
        # `prompt_manager`：统一 Prompt 访问入口。
        self.prompt_manager = prompt_manager or get_prompt_manager()
        # `logger`：当前 Agent 专属日志器，方便按模块检索日志。
        self.logger = get_logger(f"agent.{agent_name}")
        # `config`：当前 Agent 的配置片段缓存，减少重复查询。
        self.config = self.config_manager.get_agent_config(agent_type)
        # `llm`：预留给子类注入具体模型客户端，基类不绑定具体实现。
        self.llm = None
        self.logger.info(f"Initialized {agent_name} ({agent_type})")

    @abstractmethod
    async def execute(self, agent_input: AgentInput) -> AgentOutput:
        """执行非流式任务。

        子类必须实现该方法，并返回标准 `AgentOutput`。
        """
        raise NotImplementedError

    @abstractmethod
    async def execute_stream(self, agent_input: AgentInput) -> AsyncGenerator[StreamChunk, None]:
        """执行流式任务。

        子类必须实现该方法，并持续产出 `StreamChunk`。
        """
        raise NotImplementedError

    def _safe_error_message(self, error: Any, fallback: str = "execution failed") -> str:
        """对错误信息进行安全清洗。

        这样可以减少直接向外暴露内部异常栈或敏感实现细节的风险。
        """
        return sanitize_error_message(error, fallback=fallback)

    def _build_error_metadata(
        self,
        *,
        error_code: str = ErrorCode.SYSTEM_INTERNAL_ERROR.value,
        error_type: str = "execution_error",
        metadata: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """构造统一错误元数据。

        关键逻辑：
        - 保证错误码与错误类型字段稳定；
        - 允许合并额外 metadata；
        - 便于前端、日志和测试统一消费错误结构。
        """
        return build_error_metadata(
            error_code=error_code,
            error_type=error_type,
            metadata=metadata,
        )

    def _create_output(
        self,
        content: str,
        status: ExecutionStatus = "success",
        error_message: Optional[str] = None,
        execution_time_ms: int = 0,
        execution_id: Optional[str] = None,
        metadata: Optional[Dict[str, Any]] = None,
        **extra_fields: Any,
    ) -> AgentOutput:
        """创建标准输出对象。

        关键逻辑：
        - 根据 `agent_type` 选择合适的输出 dataclass；
        - 能映射到输出字段的值直接写入对象；
        - 无法识别的扩展字段自动下沉到 metadata，减少字段漂移；
        - 若状态为失败，则统一补齐错误结构和安全错误信息。
        """
        output_cls = self.OUTPUT_CLASS_BY_TYPE.get(self.agent_type, AgentOutput)
        output_field_names = {field_info.name for field_info in fields(output_cls)}
        normalized_metadata: Dict[str, Any] = deepcopy(metadata) if metadata else {}
        normalized_error_message = error_message

        output_kwargs: Dict[str, Any] = {}
        for key, value in extra_fields.items():
            if key in output_field_names:
                output_kwargs[key] = deepcopy(value)
            else:
                normalized_metadata[key] = deepcopy(value)

        if status == "failed" or error_message is not None:
            normalized_error_message = self._safe_error_message(error_message, fallback="execution failed")
            normalized_metadata = self._build_error_metadata(
                error_code=normalized_metadata.get("error_code", ErrorCode.SYSTEM_INTERNAL_ERROR.value),
                error_type=normalized_metadata.get("error_type", "execution_error"),
                metadata=normalized_metadata,
            )

        output = output_cls(
            agent_name=self.agent_name,
            agent_type=self.agent_type,
            content=content,
            status=status,
            error_message=normalized_error_message,
            execution_time_ms=execution_time_ms,
            metadata=normalized_metadata or None,
            **output_kwargs,
        )

        # 若上游已经分配 `execution_id`，则优先保留，便于全链路跟踪。
        if execution_id is not None:
            output.execution_id = execution_id
        return output

    def _create_error_output(
        self,
        *,
        error: Any,
        fallback: str = "execution failed",
        execution_time_ms: int = 0,
        execution_id: Optional[str] = None,
        error_code: str = ErrorCode.SYSTEM_INTERNAL_ERROR.value,
        error_type: str = "execution_error",
        **metadata: Any,
    ) -> AgentOutput:
        """创建标准失败输出对象。"""
        return self._create_output(
            content="",
            status="failed",
            error_message=self._safe_error_message(error, fallback=fallback),
            execution_time_ms=execution_time_ms,
            execution_id=execution_id,
            **self._build_error_metadata(
                error_code=error_code,
                error_type=error_type,
                metadata=metadata,
            ),
        )

    def _create_error_chunk(
        self,
        *,
        error: Any,
        fallback: str = "execution failed",
        error_code: str = ErrorCode.SYSTEM_INTERNAL_ERROR.value,
        error_type: str = "execution_error",
        **metadata: Any,
    ) -> StreamChunk:
        """创建失败用的流式错误块。"""
        return StreamChunk.create_error(
            self._safe_error_message(error, fallback=fallback),
            **self._build_error_metadata(
                error_code=error_code,
                error_type=error_type,
                metadata=metadata,
            ),
        )

    def _log_execution_start(self, agent_input: AgentInput):
        """记录执行开始日志。"""
        self.logger.info(
            f"Starting execution for conversation {agent_input.conversation_id}",
            extra=self._build_log_context(agent_input),
        )

    def _build_log_context(self, agent_input: AgentInput, **extra: Any) -> Dict[str, Any]:
        """构造结构化日志上下文。

        关键逻辑：
        - 统一抽取常用链路字段；
        - 与调用方额外上下文合并；
        - 自动丢弃值为 `None` 的字段，减少日志噪音。
        """
        context = {
            "user_id": agent_input.user_id,
            "conversation_id": agent_input.conversation_id,
            "message_id": agent_input.message_id,
            "request_id": agent_input.get_request_id(),
            "execution_id": agent_input.get_execution_id(),
            "knowledge_base_id": agent_input.get_knowledge_base_id(),
            "document_id": agent_input.get_document_id(),
            "agent_name": self.agent_name,
            "agent_type": self.agent_type,
        }
        context.update(extra)
        return {key: value for key, value in context.items() if value is not None}

    def _log_execution_end(
        self,
        agent_input: AgentInput,
        agent_output: AgentOutput,
        execution_time_ms: int,
    ):
        """记录执行结束日志。

        关键逻辑：
        - 成功时记为 `info`；
        - 失败时记为 `error`；
        - 这样便于日志平台按级别聚合异常。
        """
        log_level = "info" if agent_output.is_success() else "error"
        log_method = getattr(self.logger, log_level)
        log_method(
            f"Completed execution for conversation {agent_input.conversation_id} "
            f"with status {agent_output.status} in {execution_time_ms}ms",
            extra=self._build_log_context(
                agent_input,
                execution_id=agent_output.execution_id,
                status=agent_output.status,
                execution_time_ms=execution_time_ms,
            ),
        )

    def _log_error(self, error: Exception, agent_input: AgentInput):
        """记录异常日志。"""
        safe_error = self._safe_error_message(error, fallback="execution failed")
        self.logger.error(
            f"Error during execution: {safe_error}",
            exc_info=True,
            extra=self._build_log_context(
                agent_input,
                error_type=type(error).__name__,
                error_message=safe_error,
            ),
        )

    def _validate_input(self, agent_input: AgentInput) -> tuple[bool, Optional[str]]:
        """调用输入对象自带的基础校验逻辑。"""
        return agent_input.validate()

    def _get_config_value(self, key: str, default: Any = None) -> Any:
        """从当前 Agent 配置中读取单个字段。"""
        return self.config.get(key, default)

    def _get_prompt(self, prompt_key: str, **kwargs) -> str:
        """获取当前 Agent 命名空间下的 Prompt。

        关键逻辑：
        - 自动补齐 `agent_type` 前缀；
        - 若提供模板变量，则执行格式化；
        - 若未提供变量，则直接返回原始 Prompt 文本。
        """
        full_key = f"{self.agent_type}.{prompt_key}"
        if kwargs:
            return self.prompt_manager.render_prompt(full_key, **kwargs)
        return self.prompt_manager.get_prompt(full_key, "")

    def _build_chat_prompt_call(
        self,
        user_content: str,
        conversation_history: Optional[list] = None,
        *,
        user_prompt_key: str | None = None,
        system_prompt_key: str | None = None,
        user_prompt_default: str = "{question}",
        **kwargs,
    ):
        """统一构造 `ChatPromptTemplate` 调用参数。

        关键点：
        - 默认按 Agent 类型解析 system/user Prompt 键
        - 对话历史直接保留为真实聊天消息
        - 具体 Prompt 加载与兼容逻辑统一下沉到 PromptManager
        """
        resolved_user_prompt_key = user_prompt_key or f"{self.agent_type}.{self.agent_type}_user_prompt"
        resolved_system_prompt_key = system_prompt_key or f"{self.agent_type}.{self.agent_type}_system_prompt"
        return self.prompt_manager.build_chat_prompt_call(
            user_prompt_key=resolved_user_prompt_key,
            user_variables={"question": user_content, **kwargs},
            conversation_history=conversation_history,
            system_prompt_key=resolved_system_prompt_key,
            user_prompt_default=user_prompt_default,
        )

    async def safe_execute(self, agent_input: AgentInput) -> AgentOutput:
        """带保护壳的非流式执行入口。

        关键逻辑：
        1. 先做输入校验；
        2. 记录开始日志；
        3. 调用子类 `execute`；
        4. 自动补齐执行耗时；
        5. 统一捕获异常并转换为标准错误输出。
        """
        start_time = time.time()
        try:
            is_valid, error_message = self._validate_input(agent_input)
            if not is_valid:
                return self._create_error_output(
                    error=f"input validation failed: {error_message}",
                    fallback="input validation failed",
                    execution_time_ms=0,
                    error_code=ErrorCode.VALIDATION_ERROR.value,
                    error_type="validation_error",
                )

            self._log_execution_start(agent_input)
            output = await self.execute(agent_input)
            execution_time_ms = int((time.time() - start_time) * 1000)
            output.execution_time_ms = execution_time_ms
            self._log_execution_end(agent_input, output, execution_time_ms)
            return output
        except Exception as error:
            self._log_error(error, agent_input)
            execution_time_ms = int((time.time() - start_time) * 1000)
            return self._create_error_output(
                error=error,
                fallback="execution failed",
                execution_time_ms=execution_time_ms,
            )

    async def safe_execute_stream(
        self,
        agent_input: AgentInput,
    ) -> AsyncGenerator[StreamChunk, None]:
        """带保护壳的流式执行入口。

        关键逻辑：
        - 与 `safe_execute` 一样先做校验；
        - 如果输入非法，不抛异常，而是返回统一错误分块；
        - 如果子类在流式迭代中抛错，也会被兜底转换为错误分块。
        """
        try:
            is_valid, error_message = self._validate_input(agent_input)
            if not is_valid:
                yield self._create_error_chunk(
                    error=f"input validation failed: {error_message}",
                    fallback="input validation failed",
                    error_code=ErrorCode.VALIDATION_ERROR.value,
                    error_type="validation_error",
                )
                return

            self._log_execution_start(agent_input)
            async for chunk in self.execute_stream(agent_input):
                yield chunk
        except Exception as error:
            self._log_error(error, agent_input)
            yield self._create_error_chunk(error=error, fallback="execution failed")

    def get_agent_info(self) -> Dict[str, Any]:
        """返回 Agent 的基础信息，用于调试、注册表展示或健康检查。"""
        return {
            "agent_name": self.agent_name,
            "agent_type": self.agent_type,
            "config": self.config,
        }

    def __repr__(self) -> str:
        """返回简洁对象表示。"""
        return f"{self.__class__.__name__}(name='{self.agent_name}', type='{self.agent_type}')"
