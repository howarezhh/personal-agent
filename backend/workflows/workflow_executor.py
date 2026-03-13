"""
工作流执行器
负责执行Agent工作流，协调多个Agent的调用
"""

import json
from copy import deepcopy
from typing import Any, AsyncGenerator, Dict

from backend.agents.base.agent_input import AgentInput
from backend.agents.base.stream_chunk import StreamChunk
from backend.agents.generation.generation_agent import GenerationAgent
from backend.agents.registry.agent_registry import get_agent_registry
from backend.agents.retrieval.retrieval_agent import RetrievalAgent
from backend.agents.router.router_agent import RouterAgent
from backend.agents.tool.tool_agent import ToolAgent
from backend.utils.logger import get_logger
from backend.workflows.multi_agent_workflow import MultiAgentWorkflow, get_workflow_template


class WorkflowExecutor:
    """
    工作流执行器

    功能：
    1. 根据路由决策执行相应的Agent工作流
    2. 协调多个Agent之间的数据传递
    3. 处理流式输出
    4. 统一错误处理
    """

    def __init__(self):
        """初始化工作流执行器"""
        self.logger = get_logger(self.__class__.__name__)

        registry = get_agent_registry()
        self.router_agent = registry.create("router") or RouterAgent()
        self.generation_agent = registry.create("generation") or GenerationAgent()
        self.retrieval_agent = registry.create("retrieval") or RetrievalAgent()
        self.tool_agent = registry.create("tool") or ToolAgent()
        self.multi_agent_workflow = MultiAgentWorkflow()

    @staticmethod
    def _truncate_text(value: Any, max_length: int = 120) -> str:
        """截断日志中的长文本，避免日志刷屏。"""
        text = str(value).replace("\n", "\\n")
        if len(text) <= max_length:
            return text
        return f"{text[:max_length]}..."

    def _summarize_payload(self, payload: Any) -> str:
        """摘要化日志中的数据结构，便于追踪数据流。"""
        if payload is None:
            return "None"

        if isinstance(payload, dict):
            keys = list(payload.keys())
            key_preview = keys[:8]
            summary_parts = [f"dict(keys={key_preview}{'...' if len(keys) > 8 else ''})"]

            retrieval_results = payload.get("retrieval_results")
            if isinstance(retrieval_results, list):
                summary_parts.append(f"retrieval_results={len(retrieval_results)}")

            citations = payload.get("citations")
            if isinstance(citations, list):
                summary_parts.append(f"citations={len(citations)}")

            tool_result = payload.get("tool_result")
            if isinstance(tool_result, dict):
                summary_parts.append(f"tool_result_keys={list(tool_result.keys())[:6]}")

            return ", ".join(summary_parts)

        if isinstance(payload, list):
            item_type = type(payload[0]).__name__ if payload else "empty"
            return f"list(len={len(payload)}, item_type={item_type})"

        if isinstance(payload, str):
            return f"str(len={len(payload)}, preview='{self._truncate_text(payload)}')"

        try:
            json.dumps(payload)
            return f"{type(payload).__name__}({self._truncate_text(payload)})"
        except TypeError:
            return f"{type(payload).__name__}({self._truncate_text(repr(payload))})"

    def _safe_error_message(self, error: Any, fallback: str = "工作流执行失败") -> str:
        """收敛异常信息，避免日志和返回内容泄露敏感信息。"""
        if error is None:
            return fallback

        error_type = type(error).__name__
        message = self._truncate_text(error, max_length=160)
        return f"{error_type}: {message}" if message else fallback

    @staticmethod
    def _get_conversation_history(agent_input: AgentInput) -> list:
        """统一获取会话历史，兼容字段与metadata两种来源。"""
        if getattr(agent_input, "conversation_history", None):
            return agent_input.conversation_history or []
        if agent_input.metadata:
            return agent_input.metadata.get("conversation_history", []) or []
        return []

    def _ensure_metadata(self, agent_input: AgentInput) -> Dict[str, Any]:
        """统一保证 metadata 可用，并补齐会话历史。"""
        if agent_input.metadata is None:
            agent_input.metadata = {}

        if (
            "conversation_history" not in agent_input.metadata
            and getattr(agent_input, "conversation_history", None)
        ):
            agent_input.metadata["conversation_history"] = deepcopy(agent_input.conversation_history)

        return agent_input.metadata

    def _clone_agent_input(
        self,
        agent_input: AgentInput,
        metadata_updates: Dict[str, Any] | None = None,
    ) -> AgentInput:
        """复制输入，避免在工作流分支中污染原始请求对象。"""
        metadata = deepcopy(agent_input.metadata) if agent_input.metadata else {}
        conversation_history = deepcopy(agent_input.conversation_history)

        if conversation_history and "conversation_history" not in metadata:
            metadata["conversation_history"] = deepcopy(conversation_history)

        if metadata_updates:
            for key, value in metadata_updates.items():
                metadata[key] = deepcopy(value)

        return AgentInput(
            user_id=agent_input.user_id,
            conversation_id=agent_input.conversation_id,
            content=agent_input.content,
            message_id=agent_input.message_id,
            conversation_history=conversation_history,
            metadata=metadata,
        )

    def _is_knowledge_enabled(self, agent_input: AgentInput) -> bool:
        """知识库默认开启，仅在显式传入 false 时关闭。"""
        metadata = agent_input.metadata or {}
        return bool(metadata.get("enable_knowledge_base", True))

    def _is_valid_workflow_config(self, workflow_config: Any) -> bool:
        """校验多Agent工作流配置格式。"""
        return self.multi_agent_workflow._is_valid_workflow_config(workflow_config)

    def _get_default_multi_agent_workflow_config(self) -> Dict[str, Any]:
        """提供可靠的默认多Agent工作流配置。"""
        return {
            "steps": [
                {"name": "检索知识库", "agent_type": "retrieval"},
                {
                    "name": "生成回答",
                    "agent_type": "generation",
                    "config": {"use_previous_output": True},
                },
            ]
        }

    async def execute_workflow(
        self,
        agent_input: AgentInput,
    ) -> AsyncGenerator[StreamChunk, None]:
        """执行完整的Agent工作流。"""
        try:
            metadata = self._ensure_metadata(agent_input)
            history_messages = self._get_conversation_history(agent_input)
            knowledge_enabled = self._is_knowledge_enabled(agent_input)

            self.logger.info(
                "[FLOW] workflow_start: "
                f"conversation_id={agent_input.conversation_id}, "
                f"message_id={agent_input.message_id}, "
                f"question_len={len(agent_input.content or '')}, "
                f"history_count={len(history_messages)}, "
                f"knowledge_enabled={knowledge_enabled}"
            )

            self.logger.info("[FLOW][ROUTER] invoke router_agent.execute")
            yield StreamChunk.create_thinking("正在分析问题类型...")

            router_output = await self.router_agent.execute(agent_input)
            router_metadata = router_output.metadata or {}

            self.logger.info(
                "[FLOW][ROUTER] output_received: "
                f"status={router_output.status}, "
                f"metadata={self._summarize_payload(router_metadata)}"
            )

            if not router_output.is_success():
                error_msg = self._safe_error_message(
                    router_output.error_message,
                    fallback="路由分析失败",
                )
                self.logger.error(f"路由失败: {error_msg}")
                yield StreamChunk.create_error(error_msg)
                return

            decision = router_metadata.get("decision", {}) if isinstance(router_metadata, dict) else {}
            action = decision.get("action", "direct_answer")
            self.logger.info(
                f"[FLOW][ROUTER] decision: action={action}, payload={self._summarize_payload(decision)}"
            )

            if action == "direct_answer":
                self.logger.info("[FLOW] route_to=direct_answer")
                async for chunk in self._execute_direct_answer_workflow(agent_input):
                    yield chunk

            elif action == "retrieval":
                if knowledge_enabled:
                    self.logger.info("[FLOW] route_to=retrieval")
                    async for chunk in self._execute_retrieval_workflow(agent_input):
                        yield chunk
                else:
                    self.logger.info(
                        "[FLOW] route_to=retrieval blocked by config, fallback to direct_answer"
                    )
                    async for chunk in self._execute_direct_answer_workflow(agent_input):
                        yield chunk

            elif action == "tool_call":
                self.logger.info("[FLOW] route_to=tool_call")
                tool_input = agent_input
                suggested_tools = decision.get("suggested_tools", [])
                if suggested_tools:
                    tool_input = self._clone_agent_input(
                        agent_input,
                        metadata_updates={"available_tools": suggested_tools},
                    )
                    self.logger.info(
                        "[FLOW][TOOL] apply_router_suggested_tools: "
                        f"tools={suggested_tools}"
                    )
                async for chunk in self._execute_tool_call_workflow(tool_input):
                    yield chunk

            elif action == "multi_agent":
                self.logger.info("[FLOW] route_to=multi_agent")
                async for chunk in self._execute_multi_agent_workflow(agent_input, decision):
                    yield chunk

            else:
                self.logger.warning(f"未知动作: {action}，回退到直接回答")
                async for chunk in self._execute_direct_answer_workflow(agent_input):
                    yield chunk

        except Exception as error:
            safe_error = self._safe_error_message(error)
            self.logger.error(f"工作流执行失败: {safe_error}")
            yield StreamChunk.create_error(safe_error)

    async def _execute_direct_answer_workflow(
        self,
        agent_input: AgentInput,
    ) -> AsyncGenerator[StreamChunk, None]:
        """执行直接回答工作流。"""
        self.logger.info(
            "[FLOW][DIRECT] start generation_agent.execute_stream: "
            f"conversation_id={agent_input.conversation_id}, message_id={agent_input.message_id}"
        )
        yield StreamChunk.create_thinking("正在生成回答...")

        async for chunk in self.generation_agent.execute_stream(agent_input):
            yield chunk

    async def _execute_retrieval_workflow(
        self,
        agent_input: AgentInput,
    ) -> AsyncGenerator[StreamChunk, None]:
        """执行检索增强工作流。"""
        self.logger.info(
            "[FLOW][RETRIEVAL] start retrieval workflow: "
            f"conversation_id={agent_input.conversation_id}, message_id={agent_input.message_id}"
        )
        yield StreamChunk.create_thinking("正在检索知识库...")

        retrieval_results = []
        async for chunk in self.retrieval_agent.execute_stream(agent_input):
            if chunk.chunk_type == "thinking":
                self.logger.debug(
                    "[FLOW][RETRIEVAL] thinking_chunk="
                    f"{self._summarize_payload(chunk.content)}"
                )
                yield chunk
            elif chunk.chunk_type == "error":
                self.logger.error(
                    "[FLOW][RETRIEVAL] error_chunk="
                    f"{self._summarize_payload(chunk.content)}"
                )
                yield chunk
                return
            elif chunk.chunk_type == "result":
                result_payload = chunk.content if isinstance(chunk.content, dict) else {}
                self.logger.info(
                    "[FLOW][RETRIEVAL] result_chunk="
                    f"{self._summarize_payload(result_payload)}"
                )
                retrieval_results = result_payload.get("retrieval_results", []) or []
                total_results = result_payload.get("total_results", len(retrieval_results))
                yield StreamChunk.create_thinking(f"找到{total_results}条相关结果")

        if not retrieval_results:
            self.logger.info("[FLOW][RETRIEVAL] no retrieval results, fallback to generation")
            yield StreamChunk.create_thinking("未找到相关信息，使用通用知识回答...")
            async for chunk in self.generation_agent.execute_stream(agent_input):
                yield chunk
            return

        generation_input = self._clone_agent_input(
            agent_input,
            metadata_updates={
                "retrieval_results": retrieval_results,
                "conversation_history": self._get_conversation_history(agent_input),
            },
        )

        self.logger.info(
            "[FLOW][RETRIEVAL] handoff_to_generation_with_context: "
            f"retrieval_results={len(retrieval_results)}, "
            f"sample={self._summarize_payload(retrieval_results[0] if retrieval_results else {})}"
        )
        yield StreamChunk.create_thinking("正在生成回答...")
        async for chunk in self.generation_agent.generate_with_context_stream(
            generation_input,
            retrieval_results,
        ):
            yield chunk

    async def _execute_tool_call_workflow(
        self,
        agent_input: AgentInput,
    ) -> AsyncGenerator[StreamChunk, None]:
        """执行工具调用工作流。"""
        self.logger.info(
            "[FLOW][TOOL] start tool workflow: "
            f"conversation_id={agent_input.conversation_id}, message_id={agent_input.message_id}"
        )
        yield StreamChunk.create_thinking("正在选择合适的工具...")

        tool_result = None
        tool_name = None

        async for chunk in self.tool_agent.execute_stream(agent_input):
            if chunk.chunk_type == "thinking":
                self.logger.debug(
                    "[FLOW][TOOL] thinking_chunk="
                    f"{self._summarize_payload(chunk.content)}"
                )
                yield chunk
            elif chunk.chunk_type == "tool_call":
                tool_call_data = chunk.content if isinstance(chunk.content, dict) else (chunk.metadata or {})
                self.logger.info(
                    "[FLOW][TOOL] tool_call_chunk="
                    f"{self._summarize_payload(tool_call_data)}"
                )
                tool_name = tool_call_data.get("tool_name", tool_name)
                yield chunk
            elif chunk.chunk_type == "error":
                self.logger.error(
                    "[FLOW][TOOL] error_chunk="
                    f"{self._summarize_payload(chunk.content)}"
                )
                yield chunk
                return
            elif chunk.chunk_type == "result":
                result_payload = chunk.content if isinstance(chunk.content, dict) else {}
                self.logger.info(
                    "[FLOW][TOOL] result_chunk="
                    f"{self._summarize_payload(result_payload)}"
                )
                tool_result = result_payload

                if result_payload.get("no_tool_needed"):
                    route_action = result_payload.get("route_action")
                    if route_action == "retrieval" and self._is_knowledge_enabled(agent_input):
                        self.logger.info("[FLOW][TOOL] no_tool_needed=true, reroute_to=retrieval")
                        yield StreamChunk.create_thinking("检测到这是知识库问题，切换到检索流程...")
                        async for retrieval_chunk in self._execute_retrieval_workflow(agent_input):
                            yield retrieval_chunk
                    else:
                        self.logger.info("[FLOW][TOOL] no_tool_needed=true, fallback to generation")
                        yield StreamChunk.create_thinking("无需使用工具，直接回答...")
                        async for gen_chunk in self.generation_agent.execute_stream(agent_input):
                            yield gen_chunk
                    return

        if not tool_result:
            self.logger.warning("[FLOW][TOOL] tool_result_missing, fallback to generation")
            yield StreamChunk.create_thinking("工具调用未返回结果，使用通用知识回答...")
            async for chunk in self.generation_agent.execute_stream(agent_input):
                yield chunk
            return

        if not tool_result.get("tool_result", {}).get("success"):
            error_msg = self._safe_error_message(
                tool_result.get("tool_result", {}).get("error"),
                fallback="工具调用失败",
            )
            self.logger.warning(
                "[FLOW][TOOL] tool_result_failed, fallback to generation: "
                f"error={error_msg}, payload={self._summarize_payload(tool_result)}"
            )
            yield StreamChunk.create_thinking(f"工具调用失败: {error_msg}，使用通用知识回答...")
            async for chunk in self.generation_agent.execute_stream(agent_input):
                yield chunk
            return

        generation_input = self._clone_agent_input(
            agent_input,
            metadata_updates={
                "tool_result": tool_result,
                "tool_name": tool_name,
                "conversation_history": self._get_conversation_history(agent_input),
            },
        )

        self.logger.info(
            "[FLOW][TOOL] tool_result_success, handoff_to_generation: "
            f"tool_name={tool_name}, payload={self._summarize_payload(tool_result)}"
        )
        yield StreamChunk.create_thinking("正在基于工具结果生成回答...")
        async for chunk in self.generation_agent.generate_with_tool_result_stream(
            generation_input,
            tool_result,
        ):
            yield chunk

    async def _execute_multi_agent_workflow(
        self,
        agent_input: AgentInput,
        decision: Dict[str, Any],
    ) -> AsyncGenerator[StreamChunk, None]:
        """执行多Agent协作工作流。"""
        self.logger.info(
            "[FLOW][MULTI_AGENT] start: "
            f"decision={self._summarize_payload(decision)}"
        )
        yield StreamChunk.create_thinking("正在启动多Agent协作工作流...")

        workflow_config = decision.get("workflow_config")
        if not self._is_valid_workflow_config(workflow_config):
            template_name = decision.get("workflow_template", "retrieval_then_tool")
            self.logger.info(f"使用工作流模板: {template_name}")
            workflow_config = get_workflow_template(template_name)

        if not self._is_valid_workflow_config(workflow_config):
            self.logger.warning("[FLOW][MULTI_AGENT] invalid workflow_config, use default config")
            workflow_config = self._get_default_multi_agent_workflow_config()

        self.logger.info(
            "[FLOW][MULTI_AGENT] workflow_config="
            f"{self._summarize_payload(workflow_config)}"
        )

        async for chunk in self.multi_agent_workflow.execute(agent_input, workflow_config):
            if chunk.chunk_type in ("result", "error", "tool_call"):
                self.logger.info(
                    "[FLOW][MULTI_AGENT] chunk="
                    f"type={chunk.chunk_type}, payload={self._summarize_payload(chunk.content)}"
                )
            yield chunk

    def get_workflow_type(self, action: str) -> str:
        """获取工作流类型名称。"""
        workflow_types = {
            "direct_answer": "直接回答工作流",
            "retrieval": "检索增强工作流",
            "tool_call": "工具调用工作流",
            "multi_agent": "多Agent协作工作流",
        }
        return workflow_types.get(action, "未知工作流")
