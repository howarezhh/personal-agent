
import time
import asyncio
from datetime import datetime
from typing import AsyncGenerator, Optional, Dict, Any
from backend.agents.base.base_agent import BaseAgent
from backend.agents.base.agent_input import AgentInput
from backend.agents.base.agent_output import AgentOutput
from backend.agents.base.stream_chunk import StreamChunk
from backend.agents.tool.tool_selector import ToolSelector
from backend.agents.tool.result_interpreter import ResultInterpreter
from backend.tools.tool_registry import get_tool_registry
from backend.database.repositories.agent_execution_repository import get_agent_execution_repository
from backend.models.agent_execution import AgentExecutionCreate, AgentExecutionUpdate
from backend.core.config_manager import get_config_manager
from backend.tools.tool_initializer import ensure_tools_initialized


class ToolAgent(BaseAgent):
    def __init__(self):
        super().__init__(
            agent_name="tool_agent",
            agent_type="tool"
        )

        # 初始化组件
        self.tool_selector = ToolSelector()
        self.result_interpreter = ResultInterpreter()
        self.tool_registry = get_tool_registry()
        if self.tool_registry.get_tool_count() == 0:
            ensure_tools_initialized(strict=False)
            self.logger.info("工具注册表为空，已触发自动初始化")
        self.execution_repo = get_agent_execution_repository()
        self.config_manager = get_config_manager()

        # 加载配置
        self.tool_config = self.config_manager.get_agent_config("tool_agent")
        self.tool_timeout = self.tool_config.get("tool_timeout", 30)
        self.max_retries = self.tool_config.get("max_retries", 2)
        self.retry_delay = self.tool_config.get("retry_delay", 1.0)

        # 性能统计
        self._performance_stats = {
            "total_calls": 0,
            "successful_calls": 0,
            "failed_calls": 0,
            "total_execution_time_ms": 0,
            "retry_count": 0
        }

        self.logger.info(
            f"Tool agent initialized with timeout={self.tool_timeout}s, "
            f"max_retries={self.max_retries}"
        )

    @staticmethod
    def _safe_preview(value: Any, max_length: int = 120) -> str:
        text = str(value).replace("\n", "\\n")
        if len(text) <= max_length:
            return text
        return f"{text[:max_length]}..."

    def _summarize_payload(self, payload: Any) -> str:
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
        candidate_tools = None

        if hasattr(agent_input, "available_tools") and getattr(agent_input, "available_tools"):
            candidate_tools = list(getattr(agent_input, "available_tools"))
        elif agent_input.metadata:
            candidate_tools = (
                agent_input.metadata.get("available_tools")
                or agent_input.metadata.get("suggested_tools")
            )

        if not candidate_tools:
            candidate_tools = self.tool_config.get("available_tools")

        if not candidate_tools:
            return None

        valid_tools = [
            tool_name for tool_name in candidate_tools
            if self.tool_registry.is_tool_available(tool_name)
        ]

        if not valid_tools:
            self.logger.warning(f"候选工具均不可用，忽略限制: {candidate_tools}")
            return None

        self.logger.info(f"本次工具选择限制为: {valid_tools}")
        return valid_tools

    async def execute(self, agent_input: AgentInput) -> AgentOutput:
        try:
            # 1. 选择工具
            self.logger.info(f"Selecting tool for question: {agent_input.content}")

            # 获取对话历史（如果有）
            conversation_history = ""
            if hasattr(agent_input, 'conversation_history') and agent_input.conversation_history:
                conversation_history = self._format_conversation_history(agent_input.conversation_history)

            available_tools = self._resolve_available_tools(agent_input)

            selection = await self.tool_selector.select_tool(
                agent_input.content,
                available_tools=available_tools,
                conversation_history=conversation_history
            )

            self.logger.info(
                "[TOOL] execute_selection="
                f"{self._summarize_payload(selection)}"
            )

            tool_name = selection.get("tool_name")
            tool_params = selection.get("tool_params", {})

            if not tool_name:
                # 不需要工具
                self.logger.info("[TOOL] execute_no_tool_needed=true")
                return self._create_output(
                    content="不需要使用工具",
                    status="success",
                    no_tool_needed=True,
                    reasoning=selection.get("reasoning", "")
                )

            # 2. 获取工具实例
            tool = self.tool_registry.get_tool(tool_name)
            if not tool:
                return self._create_output(
                    content=f"工具 '{tool_name}' 不存在",
                    status="failed",
                    error_message=f"工具 '{tool_name}' 不存在"
                )

            # 3. 执行工具
            self.logger.info(f"Executing tool: {tool_name} with params: {tool_params}")
            start_time = time.time()

            # 使用带重试和超时的执行方法
            tool_result = await self._execute_tool_with_retry(tool, tool_name, tool_params)

            self.logger.info(
                "[TOOL] execute_tool_result="
                f"{self._summarize_payload(tool_result)}"
            )

            execution_time_ms = int((time.time() - start_time) * 1000)

            # 更新性能统计
            self._update_performance_stats(tool_result.get("success", False), execution_time_ms)

            # 4. 解释结果
            interpreted_result = self.result_interpreter.interpret(tool_name, tool_result)

            # 5. 一次性保存完整执行记录（优化后的方法）
            execution = self.execution_repo.create_execution_with_result(
                conversation_id=agent_input.conversation_id,
                message_id=agent_input.message_id,
                agent_name=self.agent_name,
                agent_type=self.agent_type,
                input_data={
                    "content": agent_input.content,
                    "tool_name": tool_name,
                    "tool_params": tool_params
                },
                output_data={
                    "tool_result": tool_result,
                    "interpreted_result": interpreted_result,
                    "execution_time_ms": execution_time_ms
                },
                status="success" if tool_result.get("success") else "failed",
                execution_time_ms=execution_time_ms,
                metadata=self._get_current_performance_stats()
            )

            # 6. 创建输出
            output = self._create_output(
                content=interpreted_result.get("formatted_text", ""),
                status="success" if tool_result.get("success") else "failed",
                execution_id=execution.execution_id,
                tool_name=tool_name,
                tool_params=tool_params,
                tool_result=tool_result,
                interpreted_result=interpreted_result,
                execution_time_ms=execution_time_ms
            )

            self.logger.info(
                "[TOOL] execute_output="
                f"status={output.status}, payload={self._summarize_payload(output.metadata)}"
            )

            return output

        except Exception as e:
            self.logger.error(f"Tool agent execution failed: {str(e)}", exc_info=True)

            # 保存失败记录
            execution_create = AgentExecutionCreate(
                conversation_id=agent_input.conversation_id,
                message_id=agent_input.message_id,
                agent_name=self.agent_name,
                agent_type=self.agent_type,
                input_data={"content": agent_input.content}
            )
            execution = self.execution_repo.create_execution(execution_create)

            # 更新执行记录为失败状态
            execution_update = AgentExecutionUpdate(
                output_data={},
                status="failed",
                error_message=str(e)
            )
            self.execution_repo.update_execution(execution.execution_id, execution_update)

            return self._create_output(
                content="",
                status="failed",
                error_message=str(e),
                execution_id=execution.execution_id
            )

    async def execute_stream(self, agent_input: AgentInput) -> AsyncGenerator[StreamChunk, None]:
        try:
            history_list = []
            if hasattr(agent_input, "conversation_history") and agent_input.conversation_history:
                history_list = agent_input.conversation_history
            elif agent_input.metadata:
                history_list = agent_input.metadata.get("conversation_history", []) or []

            self.logger.info(
                "[TOOL] stream_start: "
                f"conversation_id={agent_input.conversation_id}, "
                f"message_id={agent_input.message_id}, "
                f"question_len={len(agent_input.content or '')}, "
                f"history_count={len(history_list)}"
            )

            yield StreamChunk.create_thinking("正在选择合适的工具...")

            conversation_history = self._format_conversation_history(history_list) if history_list else ""
            available_tools = self._resolve_available_tools(agent_input)
            selection = await self.tool_selector.select_tool(
                agent_input.content,
                available_tools=available_tools,
                conversation_history=conversation_history
            )

            tool_name = selection.get("tool_name")
            tool_params = selection.get("tool_params", {})
            reasoning = selection.get("reasoning", "")

            self.logger.info(
                "[TOOL] tool_selection_done: "
                f"tool_name={tool_name}, selection={self._summarize_payload(selection)}"
            )

            if not tool_name:
                no_tool_payload = {
                    "no_tool_needed": True,
                    "reasoning": reasoning,
                    "route_action": selection.get("route_action")
                }
                self.logger.info(
                    "[TOOL] no_tool_needed_result="
                    f"{self._summarize_payload(no_tool_payload)}"
                )
                yield StreamChunk.create_result(no_tool_payload)
                return

            tool_call_start_payload = {
                "tool_name": tool_name,
                "tool_params": tool_params,
                "status": "starting"
            }
            self.logger.info(
                "[TOOL] tool_call_start_payload="
                f"{self._summarize_payload(tool_call_start_payload)}"
            )
            yield StreamChunk.create_tool_call(
                tool_name=tool_name,
                tool_input=tool_params,
                status="starting"
            )

            tool = self.tool_registry.get_tool(tool_name)
            if not tool:
                self.logger.error(f"[TOOL] tool_not_found: {tool_name}")
                yield StreamChunk.create_error(f"工具 '{tool_name}' 不存在")
                return

            self.logger.info(f"Executing tool: {tool_name} with params: {tool_params}")
            yield StreamChunk.create_thinking(f"正在执行工具 {tool_name}...")

            start_time = time.time()
            tool_result = await self._execute_tool_with_retry(tool, tool_name, tool_params)
            execution_time_ms = int((time.time() - start_time) * 1000)

            self.logger.info(
                "[TOOL] tool_call_done: "
                f"tool_name={tool_name}, execution_time_ms={execution_time_ms}, "
                f"result={self._summarize_payload(tool_result)}"
            )

            self._update_performance_stats(tool_result.get("success", False), execution_time_ms)

            tool_call_end_payload = {
                "tool_name": tool_name,
                "tool_params": tool_params,
                "tool_result": tool_result,
                "execution_time_ms": execution_time_ms,
                "status": "completed" if tool_result.get("success") else "failed"
            }
            self.logger.info(
                "[TOOL] tool_call_end_payload="
                f"{self._summarize_payload(tool_call_end_payload)}"
            )
            yield StreamChunk.create_tool_call(
                tool_name=tool_name,
                tool_input=tool_params,
                tool_result=tool_result,
                execution_time_ms=execution_time_ms,
                status="completed" if tool_result.get("success") else "failed"
            )

            interpreted_result = self.result_interpreter.interpret(tool_name, tool_result)
            self.logger.info(
                "[TOOL] interpreted_result="
                f"{self._summarize_payload(interpreted_result)}"
            )

            execution = self.execution_repo.create_execution_with_result(
                conversation_id=agent_input.conversation_id,
                message_id=agent_input.message_id,
                agent_name=self.agent_name,
                agent_type=self.agent_type,
                input_data={
                    "content": agent_input.content,
                    "tool_name": tool_name,
                    "tool_params": tool_params
                },
                output_data={
                    "tool_result": tool_result,
                    "interpreted_result": interpreted_result,
                    "execution_time_ms": execution_time_ms
                },
                status="success" if tool_result.get("success") else "failed",
                execution_time_ms=execution_time_ms,
                metadata=self._get_current_performance_stats()
            )

            result_payload = {
                "execution_id": execution.execution_id,
                "tool_name": tool_name,
                "tool_result": tool_result,
                "interpreted_result": interpreted_result,
                "execution_time_ms": execution_time_ms
            }
            self.logger.info(
                "[TOOL] stream_result_payload="
                f"{self._summarize_payload(result_payload)}"
            )
            yield StreamChunk.create_result(result_payload)

        except Exception as e:
            self.logger.error(f"Tool agent stream execution failed: {str(e)}", exc_info=True)

            execution_create = AgentExecutionCreate(
                conversation_id=agent_input.conversation_id,
                message_id=agent_input.message_id,
                agent_name=self.agent_name,
                agent_type=self.agent_type,
                input_data={"content": agent_input.content}
            )
            execution = self.execution_repo.create_execution(execution_create)

            execution_update = AgentExecutionUpdate(
                output_data={},
                status="failed",
                error_message=str(e)
            )
            self.execution_repo.update_execution(execution.execution_id, execution_update)

            yield StreamChunk.create_error(str(e))

    def _format_conversation_history(self, history: list) -> str:
        if not history:
            return ""

        formatted = []
        for msg in history[-5:]:  # 只取最近5条
            role = msg.get('role', 'unknown')
            content = msg.get('content', '')
            formatted.append(f"{role}: {content}")

        return "\n".join(formatted)

    async def _execute_tool_with_retry(
        self,
        tool: Any,
        tool_name: str,
        tool_params: Dict[str, Any]
    ) -> Dict[str, Any]:
        last_error = None

        for attempt in range(self.max_retries + 1):
            try:
                self.logger.info(
                    "[TOOL] execute_attempt_start: "
                    f"tool_name={tool_name}, attempt={attempt + 1}/{self.max_retries + 1}, "
                    f"params={self._summarize_payload(tool_params)}"
                )

                tool_result = await tool.safe_execute(timeout=self.tool_timeout, **tool_params)

                self.logger.info(
                    "[TOOL] execute_attempt_result: "
                    f"tool_name={tool_name}, attempt={attempt + 1}, "
                    f"result={self._summarize_payload(tool_result)}"
                )

                # 如果成功，直接返回
                if tool_result.get("success", False):
                    if attempt > 0:
                        self.logger.info(
                            f"Tool {tool_name} succeeded on attempt {attempt + 1}"
                        )
                    return tool_result

                # 如果失败但不是最后一次尝试，记录并重试
                if attempt < self.max_retries:
                    self.logger.warning(
                        f"Tool {tool_name} failed on attempt {attempt + 1}, retrying..."
                    )
                    self._performance_stats["retry_count"] += 1
                    await asyncio.sleep(self.retry_delay)
                    continue

                # 最后一次尝试失败，返回失败结果
                return tool_result

            except asyncio.TimeoutError:
                last_error = f"工具执行超时（超过 {self.tool_timeout} 秒）"
                self.logger.error(
                    f"Tool {tool_name} timeout on attempt {attempt + 1}: {last_error}"
                )

                if attempt < self.max_retries:
                    self._performance_stats["retry_count"] += 1
                    await asyncio.sleep(self.retry_delay)
                    continue

            except Exception as e:
                last_error = str(e)
                self.logger.error(
                    f"Tool {tool_name} error on attempt {attempt + 1}: {last_error}",
                    exc_info=True
                )

                if attempt < self.max_retries:
                    self._performance_stats["retry_count"] += 1
                    await asyncio.sleep(self.retry_delay)
                    continue

        # 所有重试都失败，返回错误结果
        failed_result = {
            "success": False,
            "error": last_error or "工具执行失败",
            "error_code": "TOOL_EXECUTION_ERROR",
            "error_type": "execution_error",
            "data": {},
            "metadata": {"tool_name": tool_name},
        }
        self.logger.error(
            "[TOOL] execute_all_attempts_failed: "
            f"tool_name={tool_name}, result={self._summarize_payload(failed_result)}"
        )
        return failed_result

    def _update_performance_stats(self, success: bool, execution_time_ms: int) -> None:
        self._performance_stats["total_calls"] += 1
        self._performance_stats["total_execution_time_ms"] += execution_time_ms

        if success:
            self._performance_stats["successful_calls"] += 1
        else:
            self._performance_stats["failed_calls"] += 1

        # 计算平均执行时间
        avg_time = (
            self._performance_stats["total_execution_time_ms"] /
            self._performance_stats["total_calls"]
        )

        # 计算成功率
        success_rate = (
            self._performance_stats["successful_calls"] /
            self._performance_stats["total_calls"] * 100
        )

        self.logger.info(
            f"Performance stats - Total: {self._performance_stats['total_calls']}, "
            f"Success: {self._performance_stats['successful_calls']}, "
            f"Failed: {self._performance_stats['failed_calls']}, "
            f"Success Rate: {success_rate:.2f}%, "
            f"Avg Time: {avg_time:.2f}ms, "
            f"Retries: {self._performance_stats['retry_count']}"
        )

    def _get_current_performance_stats(self) -> Dict[str, Any]:
        total_calls = self._performance_stats["total_calls"]
        if total_calls == 0:
            return {
                "total_calls": 0,
                "success_rate": 0.0,
                "avg_execution_time_ms": 0.0,
                "retry_count": 0
            }

        return {
            "total_calls": total_calls,
            "successful_calls": self._performance_stats["successful_calls"],
            "failed_calls": self._performance_stats["failed_calls"],
            "success_rate": (
                self._performance_stats["successful_calls"] / total_calls * 100
            ),
            "avg_execution_time_ms": (
                self._performance_stats["total_execution_time_ms"] / total_calls
            ),
            "retry_count": self._performance_stats["retry_count"]
        }

    def get_performance_stats(self) -> Dict[str, Any]:
        return self._get_current_performance_stats()

    def reset_performance_stats(self) -> None:
        self._performance_stats = {
            "total_calls": 0,
            "successful_calls": 0,
            "failed_calls": 0,
            "total_execution_time_ms": 0,
            "retry_count": 0
        }
        self.logger.info("Performance stats reset")

    async def call_specific_tool(
        self,
        tool_name: str,
        tool_params: Dict[str, Any],
        agent_input: AgentInput
    ) -> AgentOutput:
        try:
            # 获取工具实例
            tool = self.tool_registry.get_tool(tool_name)
            if not tool:
                return self._create_output(
                    content=f"工具 '{tool_name}' 不存在",
                    status="failed",
                    error_message=f"工具 '{tool_name}' 不存在"
                )

            # 执行工具
            self.logger.info(f"Calling specific tool: {tool_name} with params: {tool_params}")
            start_time = time.time()

            # 使用带重试和超时的执行方法
            tool_result = await self._execute_tool_with_retry(tool, tool_name, tool_params)

            execution_time_ms = int((time.time() - start_time) * 1000)

            # 更新性能统计
            self._update_performance_stats(tool_result.get("success", False), execution_time_ms)

            # 解释结果
            interpreted_result = self.result_interpreter.interpret(tool_name, tool_result)

            # 一次性保存完整执行记录（优化后的方法）
            execution = self.execution_repo.create_execution_with_result(
                conversation_id=agent_input.conversation_id,
                message_id=agent_input.message_id,
                agent_name=self.agent_name,
                agent_type=self.agent_type,
                input_data={
                    "content": agent_input.content,
                    "tool_name": tool_name,
                    "tool_params": tool_params
                },
                output_data={
                    "tool_result": tool_result,
                    "interpreted_result": interpreted_result,
                    "execution_time_ms": execution_time_ms
                },
                status="success" if tool_result.get("success") else "failed",
                execution_time_ms=execution_time_ms,
                metadata=self._get_current_performance_stats()
            )

            # 创建输出
            output = self._create_output(
                content=interpreted_result.get("formatted_text", ""),
                status="success" if tool_result.get("success") else "failed",
                execution_id=execution.execution_id,
                tool_name=tool_name,
                tool_params=tool_params,
                tool_result=tool_result,
                interpreted_result=interpreted_result,
                execution_time_ms=execution_time_ms
            )

            return output

        except Exception as e:
            self.logger.error(f"Specific tool call failed: {str(e)}", exc_info=True)
            return self._create_output(
                content="",
                status="failed",
                error_message=str(e)
            )
