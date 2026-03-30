from __future__ import annotations

import re
from typing import Any

from backend.agents.base.agent_input import GenerationAgentInput, RetrievalAgentInput, ToolAgentInput
from backend.contracts.task_runtime import StepObservation, TaskPlanStep, TaskRuntimeState


class TaskRuntimeAgentInputMapper:
    """把任务运行时状态映射为标准 AgentInput。"""

    def map_retrieval_input(self, step: TaskPlanStep, state: TaskRuntimeState) -> RetrievalAgentInput:
        """为检索步骤构建标准检索输入。"""
        metadata = self._build_common_metadata(step, state)
        retrieval_options = dict(step.metadata.get("retrieval_options") or {})
        metadata["retrieval_options"] = retrieval_options

        # 中文说明：检索必须优先面向用户原始问题，而不是 LLM 归一化后的目标描述。
        # 旧逻辑使用 `normalized_goal`，会把专有名词、标题和精确短语改写成抽象任务，
        # 从而直接降低知识库召回精度。
        retrieval_query = state.goal.original_user_input or state.goal.normalized_goal

        return RetrievalAgentInput(
            user_id=state.goal.user_id,
            conversation_id=state.goal.conversation_id,
            message_id=state.goal.source_message_id,
            request_id=state.metadata.get("request_id"),
            execution_id=state.metadata.get("execution_id"),
            content=retrieval_query,
            knowledge_base_id=self._resolve_knowledge_base_id(state),
            enable_knowledge_base=bool(self._resolve_knowledge_base_id(state)),
            metadata=metadata,
            top_k=int(step.metadata.get("top_k") or 5),
            vector_search_filter=self._resolve_vector_search_filter(state),
        )

    def map_tool_input(self, step: TaskPlanStep, state: TaskRuntimeState) -> ToolAgentInput:
        """为工具步骤构建标准工具输入。"""
        metadata = self._build_common_metadata(step, state)
        expression = self._resolve_expression(step, state)
        tool_name = str(step.metadata.get("tool_name") or "calculator")
        tool_params = dict(step.metadata.get("tool_params") or {})
        if expression and "expression" not in tool_params:
            tool_params["expression"] = expression

        return ToolAgentInput(
            user_id=state.goal.user_id,
            conversation_id=state.goal.conversation_id,
            message_id=state.goal.source_message_id,
            request_id=state.metadata.get("request_id"),
            execution_id=state.metadata.get("execution_id"),
            content=state.goal.original_user_input,
            metadata=metadata,
            tool_name=tool_name,
            tool_params=tool_params,
            available_tools=[tool_name],
        )

    def map_generation_input(self, step: TaskPlanStep, state: TaskRuntimeState) -> GenerationAgentInput:
        """为答案生成步骤构建标准生成输入。"""
        metadata = self._build_common_metadata(step, state)
        retrieval_results = self._resolve_retrieval_results(state)
        tool_result = self._resolve_tool_result(state)
        if retrieval_results:
            metadata["retrieval_results"] = retrieval_results
        if tool_result:
            metadata["tool_result"] = tool_result

        return GenerationAgentInput(
            user_id=state.goal.user_id,
            conversation_id=state.goal.conversation_id,
            message_id=state.goal.source_message_id,
            request_id=state.metadata.get("request_id"),
            execution_id=state.metadata.get("execution_id"),
            content=state.goal.original_user_input,
            metadata=metadata,
            retrieval_results=retrieval_results or None,
            sources=retrieval_results or None,
        )

    def _build_common_metadata(self, step: TaskPlanStep, state: TaskRuntimeState) -> dict[str, Any]:
        """沉淀任务运行时公共元信息，便于 Agent 感知链路上下文。"""
        return {
            "task_runtime": {
                "goal_id": state.goal.goal_id,
                "step_id": step.step_id,
                "step_type": step.step_type,
                "plan_id": state.current_plan.plan_id if state.current_plan else None,
            },
            "goal": state.goal.normalized_goal,
            "step_metadata": dict(step.metadata),
            "goal_metadata": dict(state.goal.metadata),
        }

    @staticmethod
    def _resolve_knowledge_base_id(state: TaskRuntimeState) -> str | None:
        """优先从目标约束或元信息中提取知识库标识。"""
        constraint_value = state.goal.constraints.get("knowledge_base_id")
        if constraint_value:
            return str(constraint_value)
        metadata_value = state.goal.metadata.get("knowledge_base_id")
        return str(metadata_value) if metadata_value else None

    @staticmethod
    def _resolve_vector_search_filter(state: TaskRuntimeState) -> dict[str, Any] | None:
        """透传向量检索过滤条件，避免步骤执行器硬编码过滤规则。"""
        value = state.goal.metadata.get("vector_search_filter")
        return dict(value) if isinstance(value, dict) else None

    @staticmethod
    def _resolve_expression(step: TaskPlanStep, state: TaskRuntimeState) -> str | None:
        """从步骤元信息或目标文本中提取计算表达式。"""
        expression = step.metadata.get("expression") or state.goal.metadata.get("detected_expression")
        if expression:
            return str(expression)
        match = re.search(r"(?P<expression>(?:\d+(?:\.\d+)?\s*[-+/*%]\s*)+\d+(?:\.\d+)?)", state.goal.original_user_input)
        if match:
            return match.group("expression").strip()
        return None

    def _resolve_retrieval_results(self, state: TaskRuntimeState) -> list[dict[str, Any]]:
        """优先使用最新检索步骤结果，其次使用请求上下文中的已有资料。"""
        latest = self._latest_observation(state, "retrieve")
        if latest is not None:
            value = latest.output_data.get("retrieved_items")
            if isinstance(value, list):
                return [dict(item) for item in value if isinstance(item, dict)]

        raw_items = state.goal.metadata.get("knowledge_items") or state.goal.metadata.get("retrieval_results")
        if isinstance(raw_items, list):
            return [dict(item) for item in raw_items if isinstance(item, dict)]
        return []

    def _resolve_tool_result(self, state: TaskRuntimeState) -> dict[str, Any] | None:
        """提取最近一次工具执行结果，供生成步骤复用。"""
        latest = self._latest_observation(state, "tool_call")
        if latest is None:
            return None
        value = latest.output_data.get("tool_result")
        if isinstance(value, dict):
            return dict(value)
        if latest.output_data:
            return dict(latest.output_data)
        return None

    @staticmethod
    def _latest_observation(state: TaskRuntimeState, step_type: str) -> StepObservation | None:
        """根据计划历史回溯某类步骤的最近观测。"""
        step_type_by_id = {
            step.step_id: step.step_type
            for plan in state.plan_history
            for step in plan.steps
        }
        if state.current_plan is not None:
            for step in state.current_plan.steps:
                step_type_by_id.setdefault(step.step_id, step.step_type)

        for observation in reversed(state.step_observations):
            if step_type_by_id.get(observation.step_id) == step_type:
                return observation
        return None
