"""
智能体基类
所有智能体的统一基类，定义通用接口和方法
"""

from abc import ABC, abstractmethod
from typing import Optional, Dict, Any, AsyncGenerator
import time
from datetime import datetime

from backend.core.config_manager import ConfigManager, get_config_manager
from backend.core.prompt_manager import PromptManager, get_prompt_manager
from backend.utils.logger import get_logger
from backend.agents.base.agent_input import AgentInput
from backend.agents.base.agent_output import AgentOutput, ExecutionStatus
from backend.agents.base.stream_chunk import StreamChunk


class BaseAgent(ABC):
    """
    智能体基类

    所有智能体必须继承此基类并实现抽象方法

    核心功能：
    1. 统一的配置管理
    2. 统一的提示词管理
    3. 统一的日志记录
    4. 统一的执行接口（非流式和流式）
    5. 统一的输出格式
    """

    def __init__(
        self,
        agent_name: str,
        agent_type: str,
        config_manager: Optional[ConfigManager] = None,
        prompt_manager: Optional[PromptManager] = None,
    ):
        """
        初始化智能体基类

        Args:
            agent_name: 智能体名称
            agent_type: 智能体类型（router/retrieval/generation/tool/file_processor）
            config_manager: 配置管理器实例
            prompt_manager: 提示词管理器实例
        """
        self.agent_name = agent_name
        self.agent_type = agent_type

        # 获取配置管理器和提示词管理器
        self.config_manager = config_manager or get_config_manager()
        self.prompt_manager = prompt_manager or get_prompt_manager()

        # 获取日志记录器
        self.logger = get_logger(f"agent.{agent_name}")

        # 加载智能体配置
        self.config = self.config_manager.get_agent_config(agent_type)

        # 初始化LLM（子类可以覆盖）
        self.llm = None

        self.logger.info(f"Initialized {agent_name} ({agent_type})")

    @abstractmethod
    async def execute(self, agent_input: AgentInput) -> AgentOutput:
        """
        执行智能体任务（非流式）

        子类必须实现此方法

        Args:
            agent_input: 智能体输入

        Returns:
            智能体输出
        """
        pass

    @abstractmethod
    async def execute_stream(self, agent_input: AgentInput) -> AsyncGenerator[StreamChunk, None]:
        """
        执行智能体任务（流式）

        子类必须实现此方法

        Args:
            agent_input: 智能体输入

        Yields:
            流式数据块
        """
        pass

    def _create_output(
        self,
        content: str,
        status: ExecutionStatus = "success",
        error_message: Optional[str] = None,
        execution_time_ms: int = 0,
        execution_id: Optional[str] = None,
        **metadata
    ) -> AgentOutput:
        """
        创建标准化的输出对象

        Args:
            content: 输出内容
            status: 执行状态（success/failed/partial）
            error_message: 错误信息
            execution_time_ms: 执行时间（毫秒）
            execution_id: 执行记录ID
            **metadata: 其他元数据

        Returns:
            AgentOutput对象
        """
        output = AgentOutput(
            agent_name=self.agent_name,
            agent_type=self.agent_type,
            content=content,
            status=status,
            error_message=error_message,
            execution_time_ms=execution_time_ms,
            metadata=metadata if metadata else None,
        )

        # 如果提供了execution_id，则设置到输出对象中
        if execution_id is not None:
            output.execution_id = execution_id

        return output

    def _log_execution_start(self, agent_input: AgentInput):
        """
        记录执行开始日志

        Args:
            agent_input: 智能体输入
        """
        self.logger.info(
            f"Starting execution for conversation {agent_input.conversation_id}",
            extra=self._build_log_context(agent_input)
        )

    def _build_log_context(self, agent_input: AgentInput, **extra: Any) -> Dict[str, Any]:
        metadata = agent_input.metadata or {}
        context = {
            "conversation_id": agent_input.conversation_id,
            "user_id": agent_input.user_id,
            "message_id": agent_input.message_id,
            "request_id": metadata.get("request_id"),
            "knowledge_base_id": metadata.get("knowledge_base_id"),
            "document_id": metadata.get("document_id"),
            "agent_name": self.agent_name,
            "agent_type": self.agent_type,
        }
        context.update(extra)
        return {key: value for key, value in context.items() if value is not None}

    def _log_execution_end(
        self,
        agent_input: AgentInput,
        agent_output: AgentOutput,
        execution_time_ms: int
    ):
        """
        记录执行结束日志

        Args:
            agent_input: 智能体输入
            agent_output: 智能体输出
            execution_time_ms: 执行时间（毫秒）
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
            )
        )

    def _log_error(self, error: Exception, agent_input: AgentInput):
        """
        记录错误日志

        Args:
            error: 异常对象
            agent_input: 智能体输入
        """
        self.logger.error(
            f"Error during execution: {str(error)}",
            exc_info=True,
            extra=self._build_log_context(
                agent_input,
                error_type=type(error).__name__,
                error_message=str(error),
            )
        )

    def _validate_input(self, agent_input: AgentInput) -> tuple[bool, Optional[str]]:
        """
        验证输入数据

        Args:
            agent_input: 智能体输入

        Returns:
            (是否有效, 错误信息)
        """
        return agent_input.validate()

    def _get_config_value(self, key: str, default: Any = None) -> Any:
        """
        获取配置值

        Args:
            key: 配置键
            default: 默认值

        Returns:
            配置值
        """
        return self.config.get(key, default)

    def _get_prompt(self, prompt_key: str, **kwargs) -> str:
        """
        获取并格式化提示词

        Args:
            prompt_key: 提示词键
            **kwargs: 变量字典

        Returns:
            格式化后的提示词
        """
        full_key = f"{self.agent_type}.{prompt_key}"
        if kwargs:
            return self.prompt_manager.format_prompt(full_key, **kwargs)
        return self.prompt_manager.get_prompt(full_key, "")

    def _build_messages(
        self,
        user_content: str,
        conversation_history: Optional[list] = None,
        **kwargs
    ) -> list:
        """
        构建LLM消息列表

        Args:
            user_content: 用户输入内容
            conversation_history: 对话历史
            **kwargs: 其他变量

        Returns:
            消息列表
        """
        return self.prompt_manager.build_messages(
            agent_type=self.agent_type,
            user_content=user_content,
            conversation_history=conversation_history,
            **kwargs
        )

    async def safe_execute(self, agent_input: AgentInput) -> AgentOutput:
        """
        安全执行（带错误处理）

        Args:
            agent_input: 智能体输入

        Returns:
            智能体输出
        """
        start_time = time.time()

        try:
            # 验证输入
            is_valid, error_message = self._validate_input(agent_input)
            if not is_valid:
                return self._create_output(
                    content="",
                    status="failed",
                    error_message=f"输入验证失败: {error_message}",
                    execution_time_ms=0,
                )

            # 记录开始日志
            self._log_execution_start(agent_input)

            # 执行任务
            output = await self.execute(agent_input)

            # 计算执行时间
            execution_time_ms = int((time.time() - start_time) * 1000)
            output.execution_time_ms = execution_time_ms

            # 记录结束日志
            self._log_execution_end(agent_input, output, execution_time_ms)

            return output

        except Exception as e:
            # 记录错误日志
            self._log_error(e, agent_input)

            # 返回错误输出
            execution_time_ms = int((time.time() - start_time) * 1000)
            return self._create_output(
                content="",
                status="failed",
                error_message=str(e),
                execution_time_ms=execution_time_ms,
            )

    async def safe_execute_stream(
        self,
        agent_input: AgentInput
    ) -> AsyncGenerator[StreamChunk, None]:
        """
        安全执行（流式，带错误处理）

        Args:
            agent_input: 智能体输入

        Yields:
            流式数据块
        """
        try:
            # 验证输入
            is_valid, error_message = self._validate_input(agent_input)
            if not is_valid:
                yield StreamChunk.create_error(f"输入验证失败: {error_message}")
                return

            # 记录开始日志
            self._log_execution_start(agent_input)

            # 执行流式任务
            async for chunk in self.execute_stream(agent_input):
                yield chunk

        except Exception as e:
            # 记录错误日志
            self._log_error(e, agent_input)

            # 返回错误数据块
            yield StreamChunk.create_error(str(e))

    def get_agent_info(self) -> Dict[str, Any]:
        """
        获取智能体信息

        Returns:
            智能体信息字典
        """
        return {
            "agent_name": self.agent_name,
            "agent_type": self.agent_type,
            "config": self.config,
        }

    def __repr__(self) -> str:
        return f"{self.__class__.__name__}(name='{self.agent_name}', type='{self.agent_type}')"
