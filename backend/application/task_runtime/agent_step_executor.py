from __future__ import annotations

from typing import Any

from backend.agents.base.agent_output import AgentOutput, GenerationAgentOutput, RetrievalAgentOutput, ToolAgentOutput
from backend.application.task_runtime.agent_input_mapper import TaskRuntimeAgentInputMapper
from backend.contracts.task_runtime import StepObservation, TaskPlanStep, TaskRuntimeState


class AgentStepExecutor:
    """复用现有 Agent 的任务运行时步骤执行器。"""

    def __init__(
        self,
        *,
        retrieval_agent: Any | None = None,
        tool_agent: Any | None = None,
        generation_agent: Any | None = None,
        input_mapper: TaskRuntimeAgentInputMapper | None = None,
        fallback_step_executor: Any | None = None,
    ) -> None:
        # 这里优先复用现有 Agent；仅在非关键步骤上回退到规则执行器。
        self.retrieval_agent = retrieval_agent
        self.tool_agent = tool_agent
        self.generation_agent = generation_agent
        self.input_mapper = input_mapper or TaskRuntimeAgentInputMapper()
        self.fallback_step_executor = fallback_step_executor or _LazyRuntimeFallbackExecutor()

    async def execute_step(self, step: TaskPlanStep, state: TaskRuntimeState) -> StepObservation:
        """按步骤类型路由到真实 Agent，无法复用时保留原有 fallback。"""
        if step.step_type == "retrieve":
            self._ensure_agents_ready(require_retrieval=True)
            return await self._execute_retrieve_step(step, state)
        if step.step_type == "tool_call":
            self._ensure_agents_ready(require_tool=True)
            return await self._execute_tool_step(step, state)
        if step.step_type == "synthesize_answer":
            self._ensure_agents_ready(require_generation=True)
            return await self._execute_synthesize_step(step, state)
        return await self.fallback_step_executor.execute_step(step, state)

    def _ensure_agents_ready(
        self,
        *,
        require_retrieval: bool = False,
        require_tool: bool = False,
        require_generation: bool = False,
    ) -> None:
        """按需延迟实例化真实 Agent，避免模块导入阶段循环依赖。"""
        if require_retrieval and self.retrieval_agent is None:
            from backend.agents.retrieval.retrieval_agent import RetrievalAgent

            self.retrieval_agent = RetrievalAgent()
        if require_tool and self.tool_agent is None:
            from backend.agents.tool.tool_agent import ToolAgent

            self.tool_agent = ToolAgent()
        if require_generation and self.generation_agent is None:
            from backend.agents.generation.generation_agent import GenerationAgent

            self.generation_agent = GenerationAgent()

    async def _execute_retrieve_step(self, step: TaskPlanStep, state: TaskRuntimeState) -> StepObservation:
        """通过 RetrievalAgent 执行检索步骤。"""
        agent_input = self.input_mapper.map_retrieval_input(step, state)
        try:
            output = await self.retrieval_agent.execute(agent_input)
        except Exception as error:
            return await self._execute_fallback_step(
                step=step,
                state=state,
                fallback_agent_name="RetrievalAgent",
                error=error,
            )

        retrieval_results = output.get_retrieval_results() or []
        success = output.is_success() and bool(retrieval_results)
        return StepObservation(
            step_id=step.step_id,
            success=success,
            summary=(
                f"检索步骤已获得 {len(retrieval_results)} 条资料。"
                if success
                else (output.error_message or "检索步骤未返回可用资料。")
            ),
            error_message=None if success else (output.error_message or "retrieval agent returned no results"),
            output_data={
                "retrieved_items": retrieval_results,
                "retrieved_count": len(retrieval_results),
                "agent_execution_id": output.execution_id,
                "agent_name": output.agent_name,
                "agent_type": output.agent_type,
            },
            metadata={
                "source": "retrieval_agent",
                "agent_status": output.status,
            },
        )

    async def _execute_tool_step(self, step: TaskPlanStep, state: TaskRuntimeState) -> StepObservation:
        """通过 ToolAgent 执行工具步骤。"""
        agent_input = self.input_mapper.map_tool_input(step, state)
        try:
            output = await self.tool_agent.execute(agent_input)
        except Exception as error:
            return await self._execute_fallback_step(
                step=step,
                state=state,
                fallback_agent_name="ToolAgent",
                error=error,
            )

        tool_result = output.get_tool_result() or {}
        interpreted_result = dict(getattr(output, "interpreted_result", None) or {})
        tool_payload = self._extract_tool_payload(tool_result)
        success = output.is_success() and bool(tool_result.get("success", output.is_success()))
        return StepObservation(
            step_id=step.step_id,
            success=success,
            summary=(
                output.content or f"工具 {getattr(output, 'tool_name', None) or agent_input.tool_name} 已执行完成。"
                if success
                else (output.error_message or output.content or "工具步骤执行失败。")
            ),
            error_message=None if success else (output.error_message or str(tool_result.get("error") or "tool execution failed")),
            output_data={
                "tool_name": getattr(output, "tool_name", None) or agent_input.tool_name,
                "tool_params": dict(getattr(output, "tool_params", None) or agent_input.tool_params or {}),
                "tool_result": tool_result,
                "interpreted_result": interpreted_result,
                "agent_execution_id": output.execution_id,
                **tool_payload,
            },
            metadata={
                "source": "tool_agent",
                "agent_status": output.status,
                "tool_call_id": getattr(output, "tool_call_id", None),
            },
        )

    async def _execute_synthesize_step(self, step: TaskPlanStep, state: TaskRuntimeState) -> StepObservation:
        """通过 GenerationAgent 执行最终答案生成步骤。"""
        agent_input = self.input_mapper.map_generation_input(step, state)
        try:
            output = await self.generation_agent.execute(agent_input)
        except Exception as error:
            return await self._execute_fallback_step(
                step=step,
                state=state,
                fallback_agent_name="GenerationAgent",
                error=error,
            )

        final_output = output.content or ""
        citations = list(getattr(output, "citations", None) or [])
        sources = list(getattr(output, "sources", None) or [])
        success = output.is_success() and bool(final_output.strip())
        if not success:
            # 生成阶段必须尽量产出最终答复，避免降级计划再次陷入空结果重试。
            return await self._execute_fallback_step(
                step=step,
                state=state,
                fallback_agent_name="GenerationAgent",
                agent_output=output,
            )
        return StepObservation(
            step_id=step.step_id,
            success=success,
            summary="已通过 GenerationAgent 生成最终答复。" if success else (output.error_message or "生成步骤未产出有效答复。"),
            error_message=None if success else (output.error_message or "generation agent returned empty content"),
            output_data={
                "final_output": final_output,
                "citations": citations,
                "sources": sources,
                "agent_execution_id": output.execution_id,
                "agent_name": output.agent_name,
                "agent_type": output.agent_type,
            },
            metadata={
                "source": "generation_agent",
                "agent_status": output.status,
            },
        )

    async def _execute_fallback_step(
        self,
        *,
        step: TaskPlanStep,
        state: TaskRuntimeState,
        fallback_agent_name: str,
        error: Exception | None = None,
        agent_output: AgentOutput | None = None,
    ) -> StepObservation:
        """当真实 Agent 失败时，回退到规则执行器生成可降级的标准观测。"""
        try:
            fallback_observation = await self.fallback_step_executor.execute_step(step, state)
        except Exception:
            if error is not None:
                return self._build_agent_exception_observation(
                    step=step,
                    agent_name=fallback_agent_name,
                    summary=f"{fallback_agent_name} 执行失败，且规则回退也失败。",
                    error=error,
                )
            return StepObservation(
                step_id=step.step_id,
                success=False,
                summary=f"{fallback_agent_name} 未产出有效结果，且规则回退也失败。",
                error_message=f"{fallback_agent_name} execution failed",
                output_data={
                    "agent_name": fallback_agent_name,
                    "step_type": step.step_type,
                },
                metadata={
                    "source": fallback_agent_name,
                    "fallback_used": True,
                },
            )

        fallback_metadata = dict(fallback_observation.metadata or {})
        fallback_metadata["fallback_used"] = True
        fallback_metadata["fallback_from_agent"] = fallback_agent_name
        if error is not None:
            fallback_metadata["exception_type"] = type(error).__name__
            fallback_metadata["exception_message"] = str(error)
        if agent_output is not None:
            fallback_metadata["agent_status"] = agent_output.status

        fallback_output_data = dict(fallback_observation.output_data or {})
        fallback_output_data.setdefault("agent_name", fallback_agent_name)
        fallback_output_data.setdefault("step_type", step.step_type)

        return StepObservation(
            step_id=step.step_id,
            success=fallback_observation.success,
            summary=fallback_observation.summary,
            error_message=fallback_observation.error_message,
            output_data=fallback_output_data,
            metadata=fallback_metadata,
        )

    @staticmethod
    def _build_agent_exception_observation(
        *,
        step: TaskPlanStep,
        agent_name: str,
        summary: str,
        error: Exception,
    ) -> StepObservation:
        """统一吞掉 Agent 异常，避免原始异常直接透传到 API。"""
        return StepObservation(
            step_id=step.step_id,
            success=False,
            summary=summary,
            error_message=f"{agent_name} execution failed",
            output_data={
                "agent_name": agent_name,
                "step_type": step.step_type,
            },
            metadata={
                "source": agent_name,
                "exception_type": type(error).__name__,
                "exception_message": str(error),
            },
        )

    @staticmethod
    def _extract_tool_payload(tool_result: dict[str, Any]) -> dict[str, Any]:
        """把常见工具结果字段扁平到步骤观测，便于复用现有评估逻辑。"""
        data = tool_result.get("data") if isinstance(tool_result.get("data"), dict) else {}
        payload: dict[str, Any] = {}
        if "expression" in data:
            payload["expression"] = data.get("expression")
        if "result" in data:
            payload["result"] = data.get("result")
        return payload


class _LazyRuntimeFallbackExecutor:
    """延迟加载原有规则执行器，避免导入阶段形成不必要耦合。"""

    def __init__(self) -> None:
        self._executor: Any | None = None

    async def execute_step(self, step: TaskPlanStep, state: TaskRuntimeState) -> StepObservation:
        if self._executor is None:
            from backend.application.task_runtime.default_components import RuntimeStepExecutor

            self._executor = RuntimeStepExecutor()
        return await self._executor.execute_step(step, state)
