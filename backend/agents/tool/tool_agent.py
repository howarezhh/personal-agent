"""工具代理。

该模块负责在多 Agent 流程中承担“工具调用执行者”的角色，核心职责包括：
1. 根据用户问题和上下文决定是否需要调用工具。
2. 调用 `ToolSelector` 选择工具与参数。
3. 通过应用服务真正执行工具。
4. 将原始结果交给 `ResultInterpreter` 解释后，再封装为统一输出。
5. 记录性能指标、执行日志以及流式事件。
"""

import asyncio
import time
from typing import Any, AsyncGenerator, Dict, Optional

from backend.agents.base.agent_input import AgentInput
from backend.agents.base.agent_output import AgentOutput
from backend.agents.base.base_agent import BaseAgent
from backend.agents.base.stream_chunk import StreamChunk
from backend.agents.tool.result_interpreter import ResultInterpreter
from backend.agents.tool.tool_selector import ToolSelector
from backend.application.services.tool_application_service import ToolApplicationService
from backend.core.config_manager import get_config_manager
from backend.tools.tool_config import get_tool_config
from backend.tools.tool_initializer import ensure_tools_initialized
from backend.tools.tool_registry import get_tool_registry


class ToolAgent(BaseAgent):
    """工具调用代理。"""

    def __init__(self):
        """初始化工具代理。

        关键成员说明：
        - `tool_selector`：负责根据问题选择工具与参数。
        - `result_interpreter`：负责把工具原始结果转换为易读结果。
        - `tool_registry`：工具注册表，用于检查工具是否存在和可用。
        - `tool_service`：应用服务层入口，真正执行工具调用。
        - `config_manager` / `global_tool_config`：统一读取 Agent 配置和工具全局配置。
        - `_performance_stats`：本实例级别的调用统计信息。
        """
        super().__init__(agent_name="tool_agent", agent_type="tool")

        # 组件初始化：选择器负责“选什么工具”，解释器负责“如何解释结果”。
        self.tool_selector = ToolSelector()
        self.result_interpreter = ResultInterpreter()
        self.tool_registry = get_tool_registry()
        if self.tool_registry.get_tool_count() == 0:
            ensure_tools_initialized(strict=False)
            self.logger.info("工具注册表为空，已触发自动初始化")
        self.tool_service = ToolApplicationService()
        self.config_manager = get_config_manager()
        self.global_tool_config = get_tool_config()

        # 配置加载：避免在业务代码中散落硬编码。
        self.tool_config = self.config_manager.get_agent_config("tool_agent")
        self.tool_timeout = self.tool_config.get("tool_timeout", 30)
        self.max_retries = self.tool_config.get("max_retries", 2)
        self.retry_delay = self.tool_config.get("retry_delay", 1.0)

        # `_performance_stats` 中每个字段含义：
        # - `total_calls`：总调用次数。
        # - `successful_calls`：成功次数。
        # - `failed_calls`：失败次数。
        # - `total_execution_time_ms`：累计执行耗时。
        # - `retry_count`：累计重试次数。
        self._performance_stats = {
            "total_calls": 0,
            "successful_calls": 0,
            "failed_calls": 0,
            "total_execution_time_ms": 0,
            "retry_count": 0,
        }

        self.logger.info(
            "Tool agent initialized with timeout=%ss, max_retries=%s",
            self.tool_timeout,
            self.max_retries,
        )

    @staticmethod
    def _safe_preview(value: Any, max_length: int = 120) -> str:
        """生成安全的日志预览字符串。"""
        text = str(value).replace("\n", "\\n")
        if len(text) <= max_length:
            return text
        return f"{text[:max_length]}..."

    def _summarize_payload(self, payload: Any) -> str:
        """将任意载荷压缩成简短日志摘要。"""
        if payload is None:
            return "None"

        if isinstance(payload, dict):
            keys = list(payload.keys())
            return f"dict(keys={keys[:8]}{'...' if len(keys) > 8 else ''})"

        if isinstance(payload, list):
            item_type = type(payload[0]).__name__ if payload else "empty"
            return f"list(len={len(payload)}, item_type={item_type})"

        if isinstance(payload, str):
            return f"str(len={len(payload)}, preview='{self._safe_preview(payload)}')"

        return f"{type(payload).__name__}({self._safe_preview(payload)})"

    def _resolve_available_tools(self, agent_input: AgentInput) -> Optional[list[str]]:
        """解析当前请求真正允许使用的工具列表。"""
        # `candidate_tools` 优先使用上游显式限制；为空时退回全局可见工具列表。
        candidate_tools = agent_input.get_available_tools()
        if candidate_tools is None:
            candidate_tools = self.global_tool_config.get_enabled_tool_names(expose_to_agent_only=True)

        if not candidate_tools:
            return []

        # `valid_tools` 是经过“允许暴露 + 当前可用”双重过滤后的最终候选集。
        valid_tools = [
            tool_name
            for tool_name in candidate_tools
            if self.global_tool_config.is_tool_exposed_to_agent(tool_name)
            and self.tool_registry.is_tool_available(tool_name)
        ]

        if not valid_tools:
            self.logger.warning("No eligible tools remain after restriction: %s", candidate_tools)
            return []

        self.logger.info("Eligible tools resolved: %s", valid_tools)
        return valid_tools

    def _format_retrieval_context_for_selection(self, retrieval_results: Any) -> str:
        """把检索结果格式化为简短上下文，供工具选择参考。"""
        if not isinstance(retrieval_results, list) or not retrieval_results:
            return ""

        lines: list[str] = []
        for index, item in enumerate(retrieval_results[:3], start=1):
            if not isinstance(item, dict):
                lines.append(f"{index}. {self._safe_preview(item, max_length=180)}")
                continue

            # `metadata` 用于优先抽取来源文件名、原始文件名等信息。
            metadata = item.get("metadata") if isinstance(item.get("metadata"), dict) else {}
            source_name = (
                metadata.get("source_name")
                or metadata.get("source")
                or metadata.get("original_filename")
                or metadata.get("file_name")
                or item.get("source_name")
                or f"result_{index}"
            )
            content = item.get("content") or item.get("text") or item.get("snippet") or ""
            score = item.get("score")
            score_suffix = f" (score={score})" if score is not None else ""
            lines.append(
                f"{index}. {source_name}{score_suffix}: {self._safe_preview(content, max_length=180)}"
            )

        return "\n".join(lines)

    def _build_tool_selection_context(self, history_list: list[Any], agent_input: AgentInput) -> str:
        """拼装工具选择阶段使用的上下文字符串。"""
        conversation_history = self._format_conversation_history(history_list) if history_list else ""
        retrieval_results = agent_input.get_retrieval_results()
        retrieval_context = self._format_retrieval_context_for_selection(retrieval_results)

        if not retrieval_context:
            return conversation_history

        if conversation_history:
            return f"{conversation_history}\n\nRecent retrieval context:\n{retrieval_context}"

        return f"Recent retrieval context:\n{retrieval_context}"

    @staticmethod
    def _no_tool_result(reasoning: str = "没有可用工具", route_action: str | None = None) -> dict[str, Any]:
        """构造统一的“无需调用工具”结果。"""
        return {
            "no_tool_needed": True,
            "reasoning": reasoning,
            "route_action": route_action,
        }

    async def _execute_tool_via_service(
        self,
        tool_name: str,
        tool_params: Dict[str, Any],
        agent_input: AgentInput,
    ) -> Dict[str, Any]:
        """通过应用服务执行工具，并透传链路上下文。"""
        return await self.tool_service.execute_tool(
            tool_name=tool_name,
            parameters=tool_params,
            user_id=agent_input.user_id,
            is_admin=False,
            conversation_id=agent_input.conversation_id,
            message_id=agent_input.message_id,
            metadata={
                "source": "tool_agent",
                "user_id": agent_input.user_id,
                "conversation_id": agent_input.conversation_id,
                "message_id": agent_input.message_id,
                "performance_stats": self._get_current_performance_stats(),
            },
        )

    async def execute(self, agent_input: AgentInput) -> AgentOutput:
        """执行非流式工具调用。"""
        try:
            explicit_tool_name = getattr(agent_input, "tool_name", None)
            if explicit_tool_name:
                explicit_tool_params = getattr(agent_input, "tool_params", None) or {}
                available_tools = self._resolve_available_tools(agent_input)
                if available_tools is not None and explicit_tool_name not in available_tools:
                    return self._create_output(
                        content="",
                        status="failed",
                        error_message=f"工具不可用: {explicit_tool_name}",
                    )
                return await self.call_specific_tool(explicit_tool_name, explicit_tool_params, agent_input)

            self.logger.info("Selecting tool for question: %s", agent_input.content)
            history_list = agent_input.get_conversation_history()
            conversation_history = self._build_tool_selection_context(history_list, agent_input)
            available_tools = self._resolve_available_tools(agent_input)

            if available_tools == []:
                self.logger.info("[TOOL] execute_no_available_tools=true")
                return self._create_output(
                    content="当前没有可供调用的工具。",
                    status="success",
                    no_tool_needed=True,
                    reasoning="当前请求范围内没有任何可用工具。",
                )

            selection = await self.tool_selector.select_tool(
                agent_input.content,
                available_tools=available_tools,
                conversation_history=conversation_history,
            )

            self.logger.info("[TOOL] execute_selection=%s", self._summarize_payload(selection))

            # `tool_name` 是被选中的工具名；`tool_params` 是最终执行参数。
            tool_name = selection.get("tool_name")
            tool_params = selection.get("tool_params", {})

            if not tool_name:
                self.logger.info("[TOOL] execute_no_tool_needed=true")
                return self._create_output(
                    content="当前问题无需调用工具。",
                    status="success",
                    no_tool_needed=True,
                    reasoning=selection.get("reasoning", ""),
                )

            self.logger.info("Executing tool: %s with params: %s", tool_name, tool_params)
            start_time = time.time()
            tool_result = await self._execute_tool_via_service(tool_name, tool_params, agent_input)

            self.logger.info("[TOOL] execute_tool_result=%s", self._summarize_payload(tool_result))

            execution_time_ms = int((time.time() - start_time) * 1000)
            self._update_performance_stats(tool_result.get("success", False), execution_time_ms)
            interpreted_result = self.result_interpreter.interpret(tool_name, tool_result)
            metadata = tool_result.get("metadata") if isinstance(tool_result.get("metadata"), dict) else {}

            output = self._create_output(
                content=interpreted_result.get("formatted_text", ""),
                status="success" if tool_result.get("success") else "failed",
                execution_id=metadata.get("execution_id"),
                tool_name=tool_name,
                tool_params=tool_params,
                tool_result=tool_result,
                interpreted_result=interpreted_result,
                tool_call_id=metadata.get("tool_call_id"),
                execution_time_ms=execution_time_ms,
            )

            self.logger.info(
                "[TOOL] execute_output=status=%s, payload=%s",
                output.status,
                self._summarize_payload(output.to_payload()),
            )

            return output

        except Exception as error:
            self.logger.error("Tool agent execution failed: %s", str(error), exc_info=True)
            return self._create_output(
                content="",
                status="failed",
                error_message=str(error),
            )

    async def execute_stream(self, agent_input: AgentInput) -> AsyncGenerator[StreamChunk, None]:
        """执行流式工具调用。"""
        try:
            history_list = agent_input.get_conversation_history()
            explicit_tool_name = getattr(agent_input, "tool_name", None)
            explicit_tool_params = getattr(agent_input, "tool_params", None) or {}

            self.logger.info(
                "[TOOL] stream_start: conversation_id=%s, message_id=%s, question_len=%s, history_count=%s",
                agent_input.conversation_id,
                agent_input.message_id,
                len(agent_input.content or ""),
                len(history_list),
            )

            yield StreamChunk.create_thinking("正在分析是否需要调用工具...")

            if explicit_tool_name:
                available_tools = self._resolve_available_tools(agent_input)
                if available_tools is not None and explicit_tool_name not in available_tools:
                    yield StreamChunk.create_error(f"工具不可用: {explicit_tool_name}")
                    return

                start_time = time.time()
                yield StreamChunk.create_tool_call(
                    tool_name=explicit_tool_name,
                    tool_input=explicit_tool_params,
                    status="starting",
                )
                tool_result = await self._execute_tool_via_service(explicit_tool_name, explicit_tool_params, agent_input)
                execution_time_ms = int((time.time() - start_time) * 1000)
                self._update_performance_stats(tool_result.get("success", False), execution_time_ms)
                interpreted_result = self.result_interpreter.interpret(explicit_tool_name, tool_result)
                yield StreamChunk.create_result(
                    {
                        "tool_name": explicit_tool_name,
                        "tool_params": explicit_tool_params,
                        "tool_result": tool_result,
                        "interpreted_result": interpreted_result,
                        "execution_time_ms": execution_time_ms,
                    }
                )
                return

            conversation_history = self._build_tool_selection_context(history_list, agent_input)
            available_tools = self._resolve_available_tools(agent_input)
            if available_tools == []:
                no_tool_payload = self._no_tool_result("当前请求范围内没有可用工具。")
                self.logger.info("[TOOL] no_available_tools_result=%s", self._summarize_payload(no_tool_payload))
                yield StreamChunk.create_result(no_tool_payload)
                return

            selection = await self.tool_selector.select_tool(
                agent_input.content,
                available_tools=available_tools,
                conversation_history=conversation_history,
            )

            tool_name = selection.get("tool_name")
            tool_params = selection.get("tool_params", {})
            reasoning = selection.get("reasoning", "")

            self.logger.info(
                "[TOOL] tool_selection_done: tool_name=%s, selection=%s",
                tool_name,
                self._summarize_payload(selection),
            )

            if not tool_name:
                no_tool_payload = self._no_tool_result(reasoning, selection.get("route_action"))
                self.logger.info("[TOOL] no_tool_needed_result=%s", self._summarize_payload(no_tool_payload))
                yield StreamChunk.create_result(no_tool_payload)
                return

            self.logger.info(
                "[TOOL] tool_call_start_payload=%s",
                self._summarize_payload({"tool_name": tool_name, "tool_params": tool_params, "status": "starting"}),
            )
            yield StreamChunk.create_tool_call(
                tool_name=tool_name,
                tool_input=tool_params,
                status="starting",
            )

            yield StreamChunk.create_thinking(f"正在调用工具 {tool_name}...")

            start_time = time.time()
            tool_result = await self._execute_tool_via_service(tool_name, tool_params, agent_input)
            execution_time_ms = int((time.time() - start_time) * 1000)
            self._update_performance_stats(tool_result.get("success", False), execution_time_ms)
            metadata = tool_result.get("metadata") if isinstance(tool_result.get("metadata"), dict) else {}

            self.logger.info(
                "[TOOL] tool_call_done: tool_name=%s, execution_time_ms=%s, result=%s",
                tool_name,
                execution_time_ms,
                self._summarize_payload(tool_result),
            )

            yield StreamChunk.create_tool_call(
                tool_name=tool_name,
                tool_input=tool_params,
                tool_result=tool_result,
                execution_time_ms=execution_time_ms,
                tool_call_id=metadata.get("tool_call_id"),
                execution_id=metadata.get("execution_id"),
                status="completed" if tool_result.get("success") else "failed",
            )

            interpreted_result = self.result_interpreter.interpret(tool_name, tool_result)
            result_payload = {
                "execution_id": metadata.get("execution_id"),
                "tool_call_id": metadata.get("tool_call_id"),
                "tool_name": tool_name,
                "tool_result": tool_result,
                "interpreted_result": interpreted_result,
                "execution_time_ms": execution_time_ms,
            }
            self.logger.info("[TOOL] stream_result_payload=%s", self._summarize_payload(result_payload))
            yield StreamChunk.create_result(result_payload)

        except Exception as error:
            self.logger.error("Tool agent stream execution failed: %s", str(error), exc_info=True)
            yield StreamChunk.create_error(str(error))

    def _format_conversation_history(self, history: list) -> str:
        """把最近会话历史压缩成简单文本。"""
        if not history:
            return ""

        formatted = []
        for msg in history[-5:]:
            # 只保留最近 5 条消息，控制提示词长度。
            role = msg.get("role", "unknown")
            content = msg.get("content", "")
            formatted.append(f"{role}: {content}")

        return "\n".join(formatted)

