"""多 Agent 协作工作流。

该模块负责把多个 Agent 组织成可编排的执行链路，支持：
1. 顺序执行；
2. 并行执行；
3. 条件分支；
4. 预定义模板和自定义配置；
5. 在步骤之间安全传递上下文、上一步结果和阶段性元数据。

这个模块的核心价值，不只是“调用多个 Agent”，而是把多 Agent 协作过程收敛为统一的
步骤结果结构与状态推进机制，降低链路复杂度。
"""

import ast
import asyncio
from copy import deepcopy
from typing import Any, AsyncGenerator, Dict, List, Optional, TypedDict

from backend.agents.base.agent_input import AgentInput
from backend.agents.base.agent_output import AgentOutput
from backend.agents.base.base_agent import BaseAgent
from backend.agents.base.stream_chunk import StreamChunk
from backend.agents.registry import get_agent_registry
from backend.contracts.errors import ErrorCode
from backend.utils.logger import get_logger
from backend.workflows.state_graph import WorkflowAction, WorkflowState, get_state_graph

CHUNK_THINKING = "thinking"
CHUNK_CONTENT = "content"
CHUNK_TOOL_CALL = "tool_call"
CHUNK_RESULT = "result"
CHUNK_ERROR = "error"
CHUNK_METADATA = "metadata"

STEP_TYPE_AGENT = "agent"
STEP_TYPE_CONDITION = "condition"


class WorkflowStep(TypedDict, total=False):
    """工作流步骤定义。

    约定：
    - `type=agent` 表示执行某个具体 Agent；
    - `type=condition` 表示执行条件判断，并进入 true/false 分支；
    - `config` 用于控制是否传递上一步输出、是否为必需步骤等。
    """

    name: str
    type: str
    agent_type: str
    config: Dict[str, Any]
    condition: str
    true_branch: List[Dict[str, Any]]
    false_branch: List[Dict[str, Any]]


class StepResult(TypedDict):
    """统一的步骤执行结果。

    所有 Agent、所有执行模式（普通 / 流式 / 顺序 / 并行）最终都会收敛到这个结构，
    这样上层代码只需要理解一种结果协议。
    """

    success: bool
    agent_type: str
    step_name: str
    step_key: str
    execution_id: Optional[str]
    content: str
    metadata: Dict[str, Any]
    data: Any
    error: Optional[str]


class MultiAgentWorkflow:
    """多Agent协作工作流。"""

    def __init__(self):
        # 独立 logger 便于在复杂多步骤链路中快速定位是哪一个工作流实例输出的日志。
        self.logger = get_logger(self.__class__.__name__)
        # 共享状态图单例，确保所有工作流实例遵循同一套状态机规则。
        self.state_graph = get_state_graph()
        self.current_state = WorkflowState.INIT

    def _create_error_chunk(
        self,
        error_message: str,
        *,
        error_code: str = ErrorCode.WORKFLOW_EXECUTION_ERROR.value,
        error_type: str = "workflow_error",
        **metadata: Any,
    ) -> StreamChunk:
        return StreamChunk.create_error(
            error_message,
            error_code=error_code,
            error_type=error_type,
            **metadata,
        )

    def _augment_step_chunk(
        self,
        chunk: StreamChunk,
        *,
        step_name: str,
        step_key: str,
        agent_type: str,
    ) -> StreamChunk:
        metadata = deepcopy(chunk.metadata) if chunk.metadata else {}
        metadata.setdefault("step_name", step_name)
        metadata.setdefault("step_key", step_key)
        metadata.setdefault("agent_type", agent_type)
        if chunk.chunk_type == CHUNK_RESULT:
            metadata.setdefault("result_scope", "step")
        if chunk.chunk_type == CHUNK_ERROR:
            metadata.setdefault("error_code", ErrorCode.WORKFLOW_EXECUTION_ERROR.value)
            metadata.setdefault("error_type", "agent_error")

        if metadata == (chunk.metadata or {}):
            return chunk

        return StreamChunk(
            chunk_id=chunk.chunk_id,
            chunk_type=chunk.chunk_type,
            content=chunk.content,
            metadata=metadata or None,
            timestamp=chunk.timestamp,
        )

    def _build_workflow_summary_result(
        self,
        *,
        status: str,
        final_step_key: Optional[str],
        final_step_result: Optional[StepResult],
        step_count: int,
    ) -> Dict[str, Any]:
        final_content = self._extract_result_content(final_step_result)
        payload: Dict[str, Any] = {
            "status": status,
            "final_step_key": final_step_key,
            "final_content": final_content,
            "content": final_content,
            "step_count": step_count,
        }

        if final_step_result:
            if final_step_result.get("execution_id"):
                payload["execution_id"] = final_step_result["execution_id"]

            final_data = final_step_result.get("data")
            if isinstance(final_data, dict):
                citations = final_data.get("citations")
                if isinstance(citations, list):
                    payload["citations"] = deepcopy(citations)

        return {key: value for key, value in payload.items() if value is not None}

    def _collect_context_handoffs(self, context: Dict[str, StepResult]) -> Dict[str, Any]:
        latest_retrieval_results = None
        latest_tool_result = None

        for result in reversed(list(context.values())):
            if not result.get("success"):
                continue

            result_data = result.get("data")
            result_metadata = result.get("metadata") or {}

            if latest_retrieval_results is None:
                if isinstance(result_data, dict) and result_data.get("retrieval_results"):
                    latest_retrieval_results = deepcopy(result_data.get("retrieval_results"))
                elif result_metadata.get("retrieval_results"):
                    latest_retrieval_results = deepcopy(result_metadata.get("retrieval_results"))

            if latest_tool_result is None:
                if isinstance(result_data, dict) and result_data.get("tool_result"):
                    latest_tool_result = deepcopy(result_data.get("tool_result"))
                elif result_metadata.get("tool_result"):
                    latest_tool_result = deepcopy(result_metadata.get("tool_result"))

            if latest_retrieval_results is not None and latest_tool_result is not None:
                break

        handoffs: Dict[str, Any] = {}
        if latest_retrieval_results is not None:
            handoffs["retrieval_results"] = latest_retrieval_results
        if latest_tool_result is not None:
            handoffs["tool_result"] = latest_tool_result
        return handoffs

    async def execute(
        self,
        agent_input: AgentInput,
        workflow_config: Dict[str, Any]
    ) -> AsyncGenerator[StreamChunk, None]:
        """执行多Agent协作工作流。"""
        # `execution_state` 保存本次执行过程中的运行时状态，
        # 与 `context` 中持久化的步骤产物分离，避免两类职责混在一起。
        execution_state: Dict[str, Any] = {
            "step_counter": 0,
            "last_step_key": None,
            "last_step_result": None,
            "failed": False,
        }
        context: Dict[str, StepResult] = {}

        try:
            self.current_state = WorkflowState.INIT
            # 先显式回到 INIT，再通过状态图进入首个运行态，保证重复调用时状态可重入。
            self._transition_or_set(WorkflowAction.START, WorkflowState.ROUTING)

            # 工作流配置是多 Agent 编排的契约入口，先校验结构再执行，
            # 可以把很多运行期错误前移到入口阶段。
            if not self._is_valid_workflow_config(workflow_config):
                self._mark_failed()
                yield self._create_error_chunk(
                    "工作流配置无效",
                    error_code=ErrorCode.WORKFLOW_INVALID_INPUT.value,
                    error_type="workflow_config_error",
                )
                return

            steps = workflow_config.get("steps", [])
            self.logger.info(f"开始执行多Agent协作工作流，共{len(steps)}个步骤")
            yield StreamChunk.create_thinking("开始执行多Agent协作工作流...")

            # 统一由 `_execute_steps` 处理顺序步骤、条件分支、失败中断等控制流。
            async for chunk in self._execute_steps(
                agent_input=agent_input,
                steps=steps,
                context=context,
                execution_state=execution_state,
            ):
                yield chunk

            if execution_state["failed"]:
                return

            self._mark_completed()
            final_step_result = execution_state.get("last_step_result")
            self.logger.info("多Agent协作工作流执行完成")
            yield StreamChunk.create_thinking("多Agent协作工作流执行完成")
            yield StreamChunk.create_result(
                self._build_workflow_summary_result(
                    status="completed",
                    final_step_key=execution_state.get("last_step_key"),
                    final_step_result=final_step_result,
                    step_count=len(context),
                ),
                result_scope="workflow",
            )

        except Exception as error:
            self._mark_failed()
            self.logger.error(f"多Agent工作流执行失败: {error}", exc_info=True)
            yield self._create_error_chunk(
                f"多Agent工作流执行失败: {error}",
                error_type="workflow_runtime_error",
            )

    async def _execute_steps(
        self,
        agent_input: AgentInput,
        steps: List[WorkflowStep],
        context: Dict[str, StepResult],
        execution_state: Dict[str, Any],
    ) -> AsyncGenerator[StreamChunk, None]:
        """顺序执行步骤列表，支持条件分支。"""
        for step in steps:
            step_type = step.get("type", STEP_TYPE_AGENT)

            if step_type == STEP_TYPE_CONDITION:
                # 条件步骤本身不产出 Agent 结果，而是像一个“控制节点”一样决定后续要执行哪组步骤。
                condition = step.get("condition", "")
                branch_name = "true_branch" if self._evaluate_condition(condition, context) else "false_branch"
                selected_steps = step.get(branch_name, []) or []

                self.logger.info(
                    f"条件步骤命中分支: condition={condition!r}, branch={branch_name}, steps={len(selected_steps)}"
                )
                yield StreamChunk.create_thinking(f"条件分支判定完成，执行 {branch_name}...")

                # 这里递归调用 `_execute_steps`，从而复用相同的步骤执行逻辑，
                # 不需要为分支步骤单独维护另一套执行器。
                async for chunk in self._execute_steps(
                    agent_input=agent_input,
                    steps=selected_steps,
                    context=context,
                    execution_state=execution_state,
                ):
                    yield chunk

                if execution_state["failed"]:
                    return
                continue

            if step_type != STEP_TYPE_AGENT:
                # 任何未知步骤类型都视为配置错误，直接终止，避免进入不可预测状态。
                result = self._build_step_result(
                    success=False,
                    agent_type=step.get("agent_type", ""),
                    step_name=step.get("name", "未命名步骤"),
                    step_key=self._make_step_key(step.get("name", "未命名步骤"), execution_state["step_counter"] + 1, context),
                    error=f"不支持的步骤类型: {step_type}",
                )
                execution_state["failed"] = True
                execution_state["last_step_result"] = result
                self._mark_failed()
                yield self._create_error_chunk(
                    result["error"] or "步骤类型无效",
                    error_type="workflow_step_type_error",
                )
                return

            # 使用显式计数器而不是直接依赖 `enumerate`，
            # 是因为条件分支递归执行时仍然需要共享一套连续步骤编号。
            execution_state["step_counter"] += 1
            step_index = execution_state["step_counter"]
            step_name = step.get("name", f"步骤{step_index}")
            agent_type = step.get("agent_type", "")
            step_config = deepcopy(step.get("config", {}) or {})
            step_key = self._make_step_key(step_name, step_index, context)
            previous_result = execution_state.get("last_step_result")

            self.logger.info(
                f"执行步骤 {step_index}: step_name={step_name}, step_key={step_key}, agent_type={agent_type}"
            )
            yield StreamChunk.create_thinking(f"执行{step_name}...")

            # `step_state` 作为可变容器传入流式执行函数，
            # 这样既能边产出 chunk，又能在结束时把归一化结果“带出来”。
            step_state: Dict[str, StepResult] = {}
            async for chunk in self._execute_agent_step_stream(
                agent_input=agent_input,
                agent_type=agent_type,
                step_name=step_name,
                step_key=step_key,
                step_config=step_config,
                context=context,
                previous_result=previous_result,
                step_state=step_state,
            ):
                yield chunk

            step_result = step_state.get(
                "result",
                self._build_step_result(
                    success=False,
                    agent_type=agent_type,
                    step_name=step_name,
                    step_key=step_key,
                    error=f"步骤 {step_name} 未返回执行结果",
                ),
            )
            context[step_key] = step_result
            execution_state["last_step_key"] = step_key
            execution_state["last_step_result"] = step_result

            if not step_result["success"]:
                reason = step_result["error"] or "未知错误"
                # `required=False` 的步骤允许失败后继续执行，常用于可选增强步骤；
                # `required=True` 则视为主链路节点，失败即终止整个工作流。
                if step_config.get("required", True):
                    self.logger.error(f"必需步骤失败: step_key={step_key}, error={reason}")
                    execution_state["failed"] = True
                    self._mark_failed()
                    if not step_state.get("error_emitted"):
                        yield self._create_error_chunk(
                            f"步骤 {step_name} 失败: {reason}",
                            error_type="workflow_step_error",
                            step_key=step_key,
                            step_name=step_name,
                            agent_type=agent_type,
                        )
                    return

                self.logger.warning(f"可选步骤失败，继续执行: step_key={step_key}, error={reason}")
                yield StreamChunk.create_thinking(
                    f"步骤 {step_name} 失败，继续执行后续步骤...",
                    event="optional_step_failed",
                    step_key=step_key,
                    step_name=step_name,
                    error=reason,
                    agent_type=agent_type,
                )

    async def _execute_agent_step(
        self,
        agent_input: AgentInput,
        agent_type: str,
        step_config: Dict[str, Any],
        context: Dict[str, StepResult],
        step_name: Optional[str] = None,
        step_key: Optional[str] = None,
        previous_result: Optional[StepResult] = None,
    ) -> StepResult:
        """执行单个Agent步骤，返回统一结构。"""
        resolved_step_name = step_name or agent_type or "未命名步骤"
        resolved_step_key = step_key or self._make_step_key(resolved_step_name, len(context) + 1, context)

        try:
            agent = self._get_agent_instance(agent_type)
            if not agent:
                return self._build_step_result(
                    success=False,
                    agent_type=agent_type,
                    step_name=resolved_step_name,
                    step_key=resolved_step_key,
                    error=f"未知的Agent类型: {agent_type}",
                )

            # 在真正调用 Agent 之前，把当前工作流上下文和上一步结果合并到输入中，
            # 保证每个 Agent 都能感知自己所处的协作阶段。
            updated_input = self._update_input_with_context(
                agent_input=agent_input,
                context=context,
                step_config=step_config,
                previous_result=previous_result,
            )

            if callable(getattr(agent, "execute", None)):
                output = await agent.execute(updated_input)
                return self._result_from_agent_output(
                    output=output,
                    agent_type=agent_type,
                    step_name=resolved_step_name,
                    step_key=resolved_step_key,
                )

            if callable(getattr(agent, "execute_stream", None)):
                return await self._collect_step_result_from_stream(
                    agent=agent,
                    agent_input=updated_input,
                    agent_type=agent_type,
                    step_name=resolved_step_name,
                    step_key=resolved_step_key,
                )

            return self._build_step_result(
                success=False,
                agent_type=agent_type,
                step_name=resolved_step_name,
                step_key=resolved_step_key,
                error=f"Agent {agent_type} 未实现 execute/execute_stream 接口",
            )

        except Exception as error:
            self.logger.error(f"Agent步骤执行失败: {error}", exc_info=True)
            return self._build_step_result(
                success=False,
                agent_type=agent_type,
                step_name=resolved_step_name,
                step_key=resolved_step_key,
                error=str(error),
            )

    async def _execute_agent_step_stream(
        self,
        agent_input: AgentInput,
        agent_type: str,
        step_name: str,
        step_key: str,
        step_config: Dict[str, Any],
        context: Dict[str, StepResult],
        previous_result: Optional[StepResult],
        step_state: Dict[str, StepResult],
    ) -> AsyncGenerator[StreamChunk, None]:
        """流式执行单个Agent步骤，并写入统一格式结果。"""
        try:
            agent = self._get_agent_instance(agent_type)
            if not agent:
                error = f"未知的Agent类型: {agent_type}"
                step_state["result"] = self._build_step_result(
                    success=False,
                    agent_type=agent_type,
                    step_name=step_name,
                    step_key=step_key,
                    error=error,
                )
                step_state["error_emitted"] = True
                yield self._create_error_chunk(
                    error,
                    error_type="workflow_step_error",
                    step_key=step_key,
                    step_name=step_name,
                    agent_type=agent_type,
                )
                return

            # 在真正调用 Agent 之前，把当前工作流上下文和上一步结果合并到输入中，
            # 保证每个 Agent 都能感知自己所处的协作阶段。
            updated_input = self._update_input_with_context(
                agent_input=agent_input,
                context=context,
                step_config=step_config,
                previous_result=previous_result,
            )
            self._advance_state_for_agent(agent_type)

            # 优先走 `execute_stream`，因为它不仅能给出最终结果，
            # 还能保留 thinking/content/tool_call 等中间事件，便于前端实时展示。
            if callable(getattr(agent, "execute_stream", None)):
                # 下面这些累积变量用于把流式 chunk 重新归并成统一的 StepResult。
                content_parts: List[str] = []
                tool_calls: List[Any] = []
                metadata_payloads: List[Dict[str, Any]] = []
                result_payload: Any = None
                result_metadata: Dict[str, Any] = {}
                error_message: Optional[str] = None
                saw_result_chunk = False

                async for chunk in agent.execute_stream(updated_input):
                    if chunk.chunk_type == CHUNK_CONTENT and isinstance(chunk.content, str):
                        content_parts.append(chunk.content)
                    elif chunk.chunk_type == CHUNK_TOOL_CALL:
                        tool_calls.append({
                            "content": chunk.content,
                            "metadata": deepcopy(chunk.metadata) if chunk.metadata else {},
                        })
                    elif chunk.chunk_type == CHUNK_METADATA and isinstance(chunk.metadata, dict):
                        metadata_payloads.append(deepcopy(chunk.metadata))
                    elif chunk.chunk_type == CHUNK_RESULT:
                        saw_result_chunk = True
                        result_payload = deepcopy(chunk.content)
                        result_metadata = deepcopy(chunk.metadata) if chunk.metadata else {}
                    elif chunk.chunk_type == CHUNK_ERROR:
                        error_message = str(chunk.content)
                        step_state["error_emitted"] = True

                    yield self._augment_step_chunk(
                        chunk,
                        step_name=step_name,
                        step_key=step_key,
                        agent_type=agent_type,
                    )

                # 即使流中已经收到部分内容，只要最终出现 error chunk，
                # 仍然把该步骤判定为失败，但会保留已产出的内容和元数据，方便排障。
                if error_message:
                    step_state["result"] = self._build_step_result(
                        success=False,
                        agent_type=agent_type,
                        step_name=step_name,
                        step_key=step_key,
                        content="".join(content_parts),
                        metadata={
                            "tool_calls": tool_calls,
                            "stream_metadata": metadata_payloads,
                            **result_metadata,
                        },
                        data=result_payload if result_payload is not None else {},
                        error=error_message,
                    )
                    return

                if not content_parts and not saw_result_chunk:
                    step_state["result"] = self._build_step_result(
                        success=False,
                        agent_type=agent_type,
                        step_name=step_name,
                        step_key=step_key,
                        metadata={
                            "tool_calls": tool_calls,
                            "stream_metadata": metadata_payloads,
                        },
                        error=f"步骤 {step_name} 未产出有效结果",
                    )
                    step_state["error_emitted"] = True
                    yield self._create_error_chunk(
                        f"步骤 {step_name} 未产出有效结果",
                        error_type="workflow_step_error",
                        step_key=step_key,
                        step_name=step_name,
                        agent_type=agent_type,
                    )
                    return

                # 某些 Agent 可能只在 result payload 里返回最终文本，而不发送 content chunk，
                # 因此这里要做一次补偿提取，避免误判为空结果。
                normalized_content = "".join(content_parts)
                if not normalized_content:
                    normalized_content = self._extract_content_from_payload(result_payload)

                normalized_metadata: Dict[str, Any] = {
                    "tool_calls": tool_calls,
                    "stream_metadata": metadata_payloads,
                    **result_metadata,
                }
                normalized_data, normalized_metadata, execution_id = self._normalize_step_result_payload(
                    agent_type=agent_type,
                    payload=result_payload,
                    metadata=normalized_metadata,
                )
                step_state["result"] = self._build_step_result(
                    success=True,
                    agent_type=agent_type,
                    step_name=step_name,
                    step_key=step_key,
                    content=normalized_content,
                    metadata=normalized_metadata,
                    data=normalized_data,
                    execution_id=execution_id,
                )
                return

            if callable(getattr(agent, "execute", None)):
                output = await agent.execute(updated_input)
                step_result = self._result_from_agent_output(
                    output=output,
                    agent_type=agent_type,
                    step_name=step_name,
                    step_key=step_key,
                )
                if step_result["content"]:
                    yield StreamChunk.create_content(step_result["content"], step_key=step_key, step_name=step_name)
                if step_result["success"]:
                    yield StreamChunk.create_result(step_result["data"], step_key=step_key, step_name=step_name)
                else:
                    step_state["error_emitted"] = True
                    yield self._create_error_chunk(
                        step_result["error"] or f"步骤 {step_name} 执行失败",
                        error_type="workflow_step_error",
                        step_key=step_key,
                        step_name=step_name,
                        agent_type=agent_type,
                    )
                step_state["result"] = step_result
                return

            error = f"Agent {agent_type} 未实现 execute/execute_stream 接口"
            step_state["result"] = self._build_step_result(
                success=False,
                agent_type=agent_type,
                step_name=step_name,
                step_key=step_key,
                error=error,
            )
            step_state["error_emitted"] = True
            yield self._create_error_chunk(
                error,
                error_type="workflow_step_error",
                step_key=step_key,
                step_name=step_name,
                agent_type=agent_type,
            )

        except Exception as error:
            self.logger.error(f"Agent步骤流式执行失败: {error}", exc_info=True)
            step_state["result"] = self._build_step_result(
                success=False,
                agent_type=agent_type,
                step_name=step_name,
                step_key=step_key,
                error=str(error),
            )
            step_state["error_emitted"] = True
            yield self._create_error_chunk(
                f"步骤 {step_name} 执行失败: {error}",
                error_type="workflow_step_error",
                step_key=step_key,
                step_name=step_name,
                agent_type=agent_type,
            )

    async def _collect_step_result_from_stream(
        self,
        agent: BaseAgent,
        agent_input: AgentInput,
        agent_type: str,
        step_name: str,
        step_key: str,
    ) -> StepResult:
        """消费 execute_stream，统一归一化结果。"""
        # 这个方法用于“非流式调用场景下消费流式 Agent”，
        # 逻辑与 `_execute_agent_step_stream` 类似，但这里不向外 yield chunk，
        # 而是直接汇总成一个最终 StepResult 返回。
        content_parts: List[str] = []
        tool_calls: List[Any] = []
        metadata_payloads: List[Dict[str, Any]] = []
        result_payload: Any = None
        result_metadata: Dict[str, Any] = {}
        error_message: Optional[str] = None
        saw_result_chunk = False

        async for chunk in agent.execute_stream(agent_input):
            if chunk.chunk_type == CHUNK_CONTENT and isinstance(chunk.content, str):
                content_parts.append(chunk.content)
            elif chunk.chunk_type == CHUNK_TOOL_CALL:
                tool_calls.append({
                    "content": chunk.content,
                    "metadata": deepcopy(chunk.metadata) if chunk.metadata else {},
                })
            elif chunk.chunk_type == CHUNK_METADATA and isinstance(chunk.metadata, dict):
                metadata_payloads.append(deepcopy(chunk.metadata))
            elif chunk.chunk_type == CHUNK_RESULT:
                saw_result_chunk = True
                result_payload = deepcopy(chunk.content)
                result_metadata = deepcopy(chunk.metadata) if chunk.metadata else {}
            elif chunk.chunk_type == CHUNK_ERROR:
                error_message = str(chunk.content)

        if error_message:
            return self._build_step_result(
                success=False,
                agent_type=agent_type,
                step_name=step_name,
                step_key=step_key,
                content="".join(content_parts),
                metadata={
                    "tool_calls": tool_calls,
                    "stream_metadata": metadata_payloads,
                    **result_metadata,
                },
                data=result_payload if result_payload is not None else {},
                error=error_message,
            )

        has_content = bool(content_parts)
        has_result = saw_result_chunk
        if not has_content and not has_result:
            return self._build_step_result(
                success=False,
                agent_type=agent_type,
                step_name=step_name,
                step_key=step_key,
                metadata={
                    "tool_calls": tool_calls,
                    "stream_metadata": metadata_payloads,
                },
                error=f"步骤 {step_name} 未产出有效结果",
            )

        normalized_content = "".join(content_parts)
        if not normalized_content:
            normalized_content = self._extract_content_from_payload(result_payload)

        normalized_metadata: Dict[str, Any] = {
            "tool_calls": tool_calls,
            "stream_metadata": metadata_payloads,
            **result_metadata,
        }
        normalized_data, normalized_metadata, execution_id = self._normalize_step_result_payload(
            agent_type=agent_type,
            payload=result_payload,
            metadata=normalized_metadata,
        )

        return self._build_step_result(
            success=True,
            agent_type=agent_type,
            step_name=step_name,
            step_key=step_key,
            content=normalized_content,
            metadata=normalized_metadata,
            data=normalized_data,
            execution_id=execution_id,
        )

    def _get_agent_instance(self, agent_type: str) -> Optional[BaseAgent]:
        """根据 agent_type 获取 Agent 实例。"""
        agent = get_agent_registry().create(agent_type)
        if agent:
            return agent
        self.logger.error(f"未知的Agent类型: {agent_type}")
        return None

    def _update_input_with_context(
        self,
        agent_input: AgentInput,
        context: Dict[str, StepResult],
        step_config: Dict[str, Any],
        previous_result: Optional[StepResult] = None,
    ) -> AgentInput:
        """根据上下文更新 AgentInput。"""
        # 统一深拷贝输入上下文，避免下游 Agent 改写上游上下文对象。
        metadata = deepcopy(agent_input.metadata) if agent_input.metadata else {}
        conversation_history = deepcopy(agent_input.conversation_history)
        workflow_context = deepcopy(context)

        if conversation_history and "conversation_history" not in metadata:
            metadata["conversation_history"] = deepcopy(conversation_history)

        # 把完整 workflow_context 和当前 step_config 一并注入 metadata，
        # 这样下游 Agent 可以按需读取工作流上下文，而不必直接依赖执行器内部状态。
        metadata["workflow_context"] = workflow_context
        metadata["step_config"] = deepcopy(step_config)

        use_previous_output = bool(step_config.get("use_previous_output", False))

        if previous_result and previous_result.get("success") and use_previous_output:
            # 只有显式开启 `use_previous_output` 时才向下游传递上一步结果，
            # 避免所有步骤无差别继承上下文，导致提示词和输入变得不可控。
            metadata["previous_output"] = deepcopy(previous_result)

            previous_data = previous_result.get("data")
            previous_metadata = previous_result.get("metadata") or {}
            if isinstance(previous_data, dict) and previous_data.get("retrieval_results"):
                metadata["retrieval_results"] = deepcopy(previous_data.get("retrieval_results"))
            elif previous_metadata.get("retrieval_results"):
                metadata["retrieval_results"] = deepcopy(previous_metadata.get("retrieval_results"))

            if isinstance(previous_data, dict) and previous_data.get("tool_result"):
                metadata["tool_result"] = deepcopy(previous_data.get("tool_result"))
            elif previous_metadata.get("tool_result"):
                metadata["tool_result"] = deepcopy(previous_metadata.get("tool_result"))

        if use_previous_output:
            handoffs = self._collect_context_handoffs(workflow_context)
            if handoffs.get("retrieval_results") and "retrieval_results" not in metadata:
                metadata["retrieval_results"] = handoffs["retrieval_results"]
            if handoffs.get("tool_result") and "tool_result" not in metadata:
                metadata["tool_result"] = handoffs["tool_result"]

        return AgentInput(
            user_id=agent_input.user_id,
            conversation_id=agent_input.conversation_id,
            message_id=agent_input.message_id,
            content=agent_input.content,
            conversation_history=conversation_history,
            metadata=metadata,
        )

    def _normalize_step_result_payload(
        self,
        agent_type: str,
        payload: Any,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> tuple[Any, Dict[str, Any], Optional[str]]:
        """统一不同 Agent 的结果载荷结构，确保上下文字段稳定。"""
        normalized_metadata = deepcopy(metadata) if metadata else {}
        normalized_payload = deepcopy(payload) if payload is not None else {}

        if isinstance(normalized_payload, dict):
            # 优先从 metadata 和 payload 中提取 execution_id，
            # 这样无论不同 Agent 把执行 ID 放在哪一层，都能统一抽出来。
            execution_id = normalized_metadata.get("execution_id") or normalized_payload.get("execution_id")

            # Router 的产物在下游通常约定为 `decision` 字段；
            # 如果原始输出没有显式包一层，这里自动补齐，统一消费协议。
            if agent_type == "router" and "decision" not in normalized_payload:
                normalized_payload = {"decision": normalized_payload}

            # 对 Retrieval / Tool 这类关键结果，除了保留在 data 中，
            # 还同步镜像到 metadata，方便后续步骤按统一入口读取。
            if agent_type == "retrieval" and "retrieval_results" in normalized_payload:
                normalized_metadata.setdefault(
                    "retrieval_results",
                    deepcopy(normalized_payload.get("retrieval_results", [])),
                )

            if agent_type == "tool" and "tool_result" in normalized_payload:
                normalized_metadata.setdefault(
                    "tool_result",
                    deepcopy(normalized_payload.get("tool_result")),
                )

            return normalized_payload, normalized_metadata, execution_id

        return normalized_payload, normalized_metadata, normalized_metadata.get("execution_id")

    async def execute_sequential(
        self,
        agent_input: AgentInput,
        agent_sequence: List[str]
    ) -> AsyncGenerator[StreamChunk, None]:
        """按顺序执行多个Agent，使用统一结果结构。"""
        self.current_state = WorkflowState.INIT
        self._transition_or_set(WorkflowAction.START, WorkflowState.ROUTING)

        # 顺序执行模式下，`previous_result` 会沿链路向后传递，
        # 用于典型的“检索 -> 生成”或“初稿 -> 优化”串联场景。
        context: Dict[str, StepResult] = {}
        previous_result: Optional[StepResult] = None

        self.logger.info(f"开始顺序执行{len(agent_sequence)}个Agent")
        yield StreamChunk.create_thinking(f"开始顺序执行{len(agent_sequence)}个Agent...")

        for index, agent_type in enumerate(agent_sequence, start=1):
            step_name = f"{agent_type}_{index}"
            step_key = self._make_step_key(step_name, index, context)
            result = await self._execute_agent_step(
                agent_input=agent_input,
                agent_type=agent_type,
                step_config={"use_previous_output": True},
                context=context,
                step_name=step_name,
                step_key=step_key,
                previous_result=previous_result,
            )
            context[step_key] = result
            previous_result = result

            if not result["success"]:
                self._mark_failed()
                yield StreamChunk.create_error(
                    f"Agent {agent_type} 执行失败: {result['error'] or '未知错误'}"
                )
                return

        self._mark_completed()
        yield StreamChunk.create_result(
            self._build_workflow_summary_result(
                status="completed",
                final_step_key=previous_result["step_key"] if previous_result else None,
                final_step_result=previous_result,
                step_count=len(context),
            ),
            result_scope="workflow",
        )

    async def execute_parallel(
        self,
        agent_input: AgentInput,
        agent_list: List[str]
    ) -> AsyncGenerator[StreamChunk, None]:
        """并行执行多个Agent，返回统一结果结构。"""
        self.current_state = WorkflowState.INIT
        self._transition_or_set(WorkflowAction.START, WorkflowState.ROUTING)

        self.logger.info(f"开始并行执行{len(agent_list)}个Agent")
        yield StreamChunk.create_thinking(f"开始并行执行{len(agent_list)}个Agent...")

        # 并行模式不共享 `previous_result`，而是把每个任务看作独立步骤同时执行。
        task_specs = []
        context: Dict[str, StepResult] = {}
        for index, agent_type in enumerate(agent_list, start=1):
            step_name = f"{agent_type}_{index}"
            step_key = self._make_step_key(step_name, index, context)
            task_specs.append((
                step_key,
                agent_type,
                # 这里显式创建 Task，再统一 gather，
                # 这样所有并行步骤都会被调度，即使个别步骤失败也不会阻断其它任务启动。
                asyncio.create_task(
                    self._execute_agent_step(
                        agent_input=agent_input,
                        agent_type=agent_type,
                        step_config={},
                        context={},
                        step_name=step_name,
                        step_key=step_key,
                        previous_result=None,
                    )
                ),
            ))

        # `return_exceptions=True` 很关键：它保证 gather 在某个任务异常时仍然收集其它任务结果，
        # 从而让工作流能够输出“部分成功/部分失败”的完整上下文。
        results = await asyncio.gather(*(task for _, _, task in task_specs), return_exceptions=True)

        has_failure = False
        last_result: Optional[StepResult] = None
        for (step_key, agent_type, _), result in zip(task_specs, results):
            if isinstance(result, Exception):
                has_failure = True
                self.logger.error(
                    f"并行步骤执行异常: agent_type={agent_type}, error={result}",
                    exc_info=(type(result), result, result.__traceback__),
                )
                context[step_key] = self._build_step_result(
                    success=False,
                    agent_type=agent_type,
                    step_name=step_key,
                    step_key=step_key,
                    error=str(result),
                )
            else:
                context[step_key] = result
                last_result = result
                if not result["success"]:
                    has_failure = True

        if has_failure:
            self._mark_failed()
        else:
            self._mark_completed()

        yield StreamChunk.create_result(
            self._build_workflow_summary_result(
                status="completed" if not has_failure else "partial",
                final_step_key=last_result["step_key"] if last_result else None,
                final_step_result=last_result,
                step_count=len(context),
            ),
            result_scope="workflow",
        )

    def transition_state(self, action: WorkflowAction) -> bool:
        """按状态图推进当前状态。"""
        next_state = self.state_graph.get_next_state(self.current_state, action)
        if next_state is None:
            self.logger.warning(
                f"无效状态转换: {self.current_state.value} --{action.value}--> ?"
            )
            return False

        self.logger.info(
            f"状态转换: {self.current_state.value} --{action.value}--> {next_state.value}"
        )
        self.current_state = next_state
        return True

    def get_current_state(self) -> WorkflowState:
        """获取当前工作流状态。"""
        return self.current_state

    def is_completed(self) -> bool:
        """判断工作流是否结束。"""
        return self.state_graph.is_terminal_state(self.current_state)

    def _transition_or_set(self, action: WorkflowAction, fallback_state: WorkflowState) -> None:
        """优先按状态图转换，失败时回退到显式状态。"""
        # 绝大多数情况下优先遵循状态图；
        # 只有在状态图没有对应边时，才回退到显式设置状态，增强容错性。
        if not self.transition_state(action):
            self.current_state = fallback_state

    def _advance_state_for_agent(self, agent_type: str) -> None:
        """根据 Agent 类型同步工作流状态。"""
        mapping = {
            "router": (WorkflowAction.ROUTE, WorkflowState.ROUTING),
            "retrieval": (WorkflowAction.RETRIEVE, WorkflowState.RETRIEVING),
            "tool": (WorkflowAction.CALL_TOOL, WorkflowState.TOOL_CALLING),
            "generation": (WorkflowAction.GENERATE, WorkflowState.GENERATING),
        }
        action_state = mapping.get(agent_type)
        if not action_state:
            return
        action, fallback_state = action_state
        self._transition_or_set(action, fallback_state)

    def _mark_failed(self) -> None:
        """将状态推进为失败。"""
        self._transition_or_set(WorkflowAction.FAIL, WorkflowState.FAILED)

    def _mark_completed(self) -> None:
        """将状态推进为完成。"""
        self._transition_or_set(WorkflowAction.COMPLETE, WorkflowState.COMPLETED)

    def _build_step_result(
        self,
        success: bool,
        agent_type: str,
        step_name: str,
        step_key: str,
        execution_id: Optional[str] = None,
        content: str = "",
        metadata: Optional[Dict[str, Any]] = None,
        data: Any = None,
        error: Optional[str] = None,
    ) -> StepResult:
        """构造统一步骤结果结构。"""
        return {
            "success": success,
            "agent_type": agent_type,
            "step_name": step_name,
            "step_key": step_key,
            "execution_id": execution_id,
            "content": content or "",
            "metadata": deepcopy(metadata) if metadata else {},
            "data": deepcopy(data) if data is not None else {},
            "error": error,
        }

    def _result_from_agent_output(
        self,
        output: AgentOutput,
        agent_type: str,
        step_name: str,
        step_key: str,
    ) -> StepResult:
        """将 AgentOutput 归一化为统一步骤结果。"""
        metadata = deepcopy(output.metadata) if output.metadata else {}
        raw_data: Any = metadata if metadata else output.content
        data, metadata, execution_id = self._normalize_step_result_payload(
            agent_type=agent_type,
            payload=raw_data,
            metadata=metadata,
        )
        return self._build_step_result(
            success=output.is_success(),
            agent_type=agent_type,
            step_name=step_name,
            step_key=step_key,
            execution_id=execution_id or output.execution_id,
            content=output.content or self._extract_content_from_payload(data),
            metadata=metadata,
            data=data,
            error=output.error_message,
        )

    def _make_step_key(
        self,
        base_name: str,
        step_index: int,
        context: Dict[str, StepResult],
    ) -> str:
        """生成唯一且可读的上下文键。"""
        # 这里既追求可读性，也保证唯一性：优先使用业务语义化名称，冲突时再追加编号。
        normalized = base_name.strip() or f"step_{step_index}"
        if normalized not in context:
            return normalized
        return f"{normalized}#{step_index}"

    def _extract_content_from_payload(self, payload: Any) -> str:
        """从结果载荷中提取可读文本。"""
        if isinstance(payload, str):
            return payload
        if isinstance(payload, dict):
            for key in ("content", "final_content", "message", "answer"):
                value = payload.get(key)
                if isinstance(value, str) and value:
                    return value
        return ""

    def _extract_result_content(self, result: Optional[StepResult]) -> str:
        """从步骤结果中提取最终输出文本。"""
        if not result:
            return ""
        if result.get("content"):
            return result["content"]
        return self._extract_content_from_payload(result.get("data"))

    def _is_valid_workflow_config(self, workflow_config: Any) -> bool:
        """校验工作流配置结构。"""
        if not isinstance(workflow_config, dict):
            return False
        steps = workflow_config.get("steps")
        return self._are_valid_steps(steps)

    def is_valid_workflow_config(self, workflow_config: Any) -> bool:
        """对外暴露工作流配置校验，避免外部依赖私有方法。"""
        return self._is_valid_workflow_config(workflow_config)

    def _are_valid_steps(self, steps: Any) -> bool:
        """递归校验步骤列表。"""
        # 主步骤列表必须是非空列表；否则工作流没有任何可执行内容。
        if not isinstance(steps, list) or not steps:
            return False

        for step in steps:
            if not isinstance(step, dict):
                return False

            if "name" in step and not isinstance(step.get("name"), str):
                return False

            step_type = step.get("type", STEP_TYPE_AGENT)
            if step_type == STEP_TYPE_CONDITION:
                if not isinstance(step.get("condition"), str):
                    return False
                if not self._are_optional_steps_valid(step.get("true_branch", [])):
                    return False
                if not self._are_optional_steps_valid(step.get("false_branch", [])):
                    return False
                continue

            if step_type != STEP_TYPE_AGENT:
                return False
            if not step.get("agent_type"):
                return False
            if step.get("agent_type") not in set(get_agent_registry().registered_types()):
                return False
            if "config" in step and not isinstance(step.get("config"), dict):
                return False

        return True

    def _are_optional_steps_valid(self, steps: Any) -> bool:
        """允许分支为空，否则按步骤列表校验。"""
        if steps in (None, []):
            return True
        return self._are_valid_steps(steps)

    def _evaluate_condition(self, condition: str, context: Dict[str, StepResult]) -> bool:
        """安全计算条件表达式。"""
        if not condition:
            return False

        try:
            # 这里只允许表达式模式，不允许语句级代码，从源头限制条件表达式能力边界。
            tree = ast.parse(condition, mode="eval")
            env = {
                "context": context,
                "step_results": context,
                "last_step": next(reversed(context.values())) if context else {},
                "True": True,
                "False": False,
                "None": None,
            }
            # `env` 只暴露白名单变量，不让条件表达式直接访问任意 Python 全局对象。
            result = self._safe_eval_ast(tree.body, env)
            return bool(result)
        except Exception as error:
            self.logger.warning(f"条件表达式计算失败: condition={condition!r}, error={error}")
            return False

    def _safe_eval_ast(self, node: ast.AST, env: Dict[str, Any]) -> Any:
        """受限 AST 求值，只支持简单布尔与比较表达式。"""
        if isinstance(node, ast.Constant):
            return node.value

        if isinstance(node, ast.Dict):
            return {
                self._safe_eval_ast(key, env): self._safe_eval_ast(value, env)
                for key, value in zip(node.keys, node.values)
            }

        if isinstance(node, ast.List):
            return [self._safe_eval_ast(item, env) for item in node.elts]

        if isinstance(node, ast.Tuple):
            return tuple(self._safe_eval_ast(item, env) for item in node.elts)

        if isinstance(node, ast.Name):
            if node.id not in env:
                raise ValueError(f"不允许的变量: {node.id}")
            return env[node.id]

        if isinstance(node, ast.Attribute):
            value = self._safe_eval_ast(node.value, env)
            if isinstance(value, dict):
                return value.get(node.attr)
            return getattr(value, node.attr)

        if isinstance(node, ast.Call):
            # 出于安全考虑，这里只允许字典对象的 `get` 调用，
            # 不允许任意函数调用或方法调用。
            if isinstance(node.func, ast.Attribute) and node.func.attr == "get":
                target = self._safe_eval_ast(node.func.value, env)
                if not isinstance(target, dict):
                    raise ValueError("仅支持对字典调用 get")

                args = [self._safe_eval_ast(arg, env) for arg in node.args]
                if len(args) == 1:
                    return target.get(args[0])
                if len(args) == 2:
                    return target.get(args[0], args[1])

            raise ValueError("不支持的函数调用")

        if isinstance(node, ast.Subscript):
            value = self._safe_eval_ast(node.value, env)
            key = self._safe_eval_ast(node.slice, env)
            return value[key]

        if isinstance(node, ast.BoolOp):
            values = [self._safe_eval_ast(v, env) for v in node.values]
            if isinstance(node.op, ast.And):
                return all(values)
            if isinstance(node.op, ast.Or):
                return any(values)
            raise ValueError("不支持的布尔操作")

        if isinstance(node, ast.UnaryOp) and isinstance(node.op, ast.Not):
            return not self._safe_eval_ast(node.operand, env)

        if isinstance(node, ast.Compare):
            # 这里按 Python 链式比较的语义逐段计算，例如 a == b == c。
            left = self._safe_eval_ast(node.left, env)
            result = True
            for operator, comparator in zip(node.ops, node.comparators):
                right = self._safe_eval_ast(comparator, env)
                if isinstance(operator, ast.Eq):
                    result = result and (left == right)
                elif isinstance(operator, ast.NotEq):
                    result = result and (left != right)
                elif isinstance(operator, ast.Is):
                    result = result and (left is right)
                elif isinstance(operator, ast.IsNot):
                    result = result and (left is not right)
                elif isinstance(operator, ast.In):
                    result = result and (left in right)
                elif isinstance(operator, ast.NotIn):
                    result = result and (left not in right)
                else:
                    raise ValueError("不支持的比较操作")
                left = right
            return result

        raise ValueError(f"不支持的表达式节点: {type(node).__name__}")


class WorkflowBuilder:
    """工作流构建器。"""

    def __init__(self):
        self.steps: List[WorkflowStep] = []

    def add_step(
        self,
        name: str,
        agent_type: str,
        config: Optional[Dict[str, Any]] = None
    ) -> "WorkflowBuilder":
        # 构建器在这里做 deepcopy，避免外部传入的配置对象在 build 之后被继续修改。
        self.steps.append({
            "name": name,
            "type": STEP_TYPE_AGENT,
            "agent_type": agent_type,
            "config": deepcopy(config) if config else {},
        })
        return self

    def add_condition(
        self,
        condition: str,
        true_branch: List[Dict[str, Any]],
        false_branch: Optional[List[Dict[str, Any]]] = None
    ) -> "WorkflowBuilder":
        self.steps.append({
            "type": STEP_TYPE_CONDITION,
            "condition": condition,
            "true_branch": deepcopy(true_branch),
            "false_branch": deepcopy(false_branch or []),
        })
        return self

    def build(self) -> Dict[str, Any]:
        return {"steps": deepcopy(self.steps)}


# 预置模板用于覆盖最常见的工作流编排场景；
# 所有模板最终仍然会走统一的配置校验和执行路径。
WORKFLOW_TEMPLATES: Dict[str, Dict[str, Any]] = {
    "retrieval_then_tool": {
        "name": "先检索后工具调用",
        "description": "先从知识库检索信息，再根据结果调用工具，最后生成回答。",
        "steps": [
            {"name": "检索知识", "type": STEP_TYPE_AGENT, "agent_type": "retrieval", "config": {}},
            {"name": "调用工具", "type": STEP_TYPE_AGENT, "agent_type": "tool", "config": {}},
            {"name": "生成回答", "type": STEP_TYPE_AGENT, "agent_type": "generation", "config": {"use_previous_output": True}},
        ],
    },
    "tool_then_retrieval": {
        "name": "先工具调用后检索",
        "description": "先调用工具获取外部数据，再补充知识库检索，最后生成回答。",
        "steps": [
            {"name": "调用工具", "type": STEP_TYPE_AGENT, "agent_type": "tool", "config": {}},
            {"name": "检索知识", "type": STEP_TYPE_AGENT, "agent_type": "retrieval", "config": {}},
            {"name": "生成回答", "type": STEP_TYPE_AGENT, "agent_type": "generation", "config": {"use_previous_output": True}},
        ],
    },
    "iterative_refinement": {
        "name": "迭代优化",
        "description": "先生成初稿，再基于前一步结果继续优化。",
        "steps": [
            {"name": "初次生成", "type": STEP_TYPE_AGENT, "agent_type": "generation", "config": {}},
            {"name": "优化生成", "type": STEP_TYPE_AGENT, "agent_type": "generation", "config": {"use_previous_output": True}},
        ],
    },
    "conditional_retrieval": {
        "name": "按条件检索",
        "description": "先进行路由，如果上一步表明需要检索，则走检索分支，否则直接生成。",
        "steps": [
            {"name": "路由分析", "type": STEP_TYPE_AGENT, "agent_type": "router", "config": {}},
            {
                "type": STEP_TYPE_CONDITION,
                "condition": "last_step.data and last_step.data.get('decision', {}).get('action') == 'retrieval'",
                "true_branch": [
                    {"name": "检索知识", "type": STEP_TYPE_AGENT, "agent_type": "retrieval", "config": {}},
                    {"name": "生成回答", "type": STEP_TYPE_AGENT, "agent_type": "generation", "config": {"use_previous_output": True}},
                ],
                "false_branch": [
                    {"name": "直接生成", "type": STEP_TYPE_AGENT, "agent_type": "generation", "config": {}},
                ],
            },
        ],
    },
}


def get_workflow_template(template_name: str) -> Optional[Dict[str, Any]]:
    """获取预定义的工作流模板。"""
    template = WORKFLOW_TEMPLATES.get(template_name)
    return deepcopy(template) if template else None
