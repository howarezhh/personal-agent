from __future__ import annotations

import asyncio
from collections.abc import AsyncGenerator, Awaitable, Callable
from typing import Optional

from backend.application.task_runtime.interfaces import (
    GoalJudge,
    GoalParser,
    Planner,
    Replanner,
    StepEvaluator,
    StepExecutor,
)
from backend.contracts.errors import ErrorCode
from backend.contracts.task_runtime import (
    ReplanDecision,
    TaskArtifact,
    TaskControllerRequest,
    TaskEvaluationReport,
    TaskPlan,
    TaskPlanStep,
    TaskRuntimeControllerEvent,
    TaskRuntimeState,
    TerminationDecision,
)


# EventEmitter：控制器向外发射结构化运行事件的回调类型。
# 调用方通常会把该事件继续转换成 SSE、日志或测试断言对象。
EventEmitter = Callable[[TaskRuntimeControllerEvent], Awaitable[None]]
# StateProbe：外部状态探针类型。
# 应用层可通过该探针把“暂停 / 取消”等外部状态变更反馈给控制器主循环。
StateProbe = Callable[[TaskRuntimeState], Awaitable[str | None]]


class TaskController:
    """闭环任务控制器。

    该控制器负责把一个任务从“目标解析”推进到“计划生成、步骤执行、结果评估、重规划、终止”。
    它是 task-runtime 核心编排器，但本身并不直接依赖具体基础设施实现，
    而是通过注入的解析器、规划器、执行器、评估器和重规划器协同工作。

    核心职责：
    - 解析用户目标并初始化运行时状态；
    - 驱动步骤级循环执行；
    - 在每轮结束后判断目标是否完成；
    - 必要时生成新计划并继续推进；
    - 统一发出过程事件与终止事件。
    """

    def __init__(
        self,
        *,
        goal_parser: GoalParser,
        planner: Planner,
        step_executor: StepExecutor,
        step_evaluator: StepEvaluator,
        goal_judge: GoalJudge,
        replanner: Replanner,
        max_iterations: int = 8,
    ):
        # goal_parser：负责把用户输入解析为结构化任务目标。
        self.goal_parser = goal_parser
        # planner：负责依据目标与当前状态生成任务计划。
        self.planner = planner
        # step_executor：负责真正执行某个步骤。
        self.step_executor = step_executor
        # step_evaluator：负责评估步骤执行结果是否达标。
        self.step_evaluator = step_evaluator
        # goal_judge：负责从全局视角判断目标是否已经完成。
        self.goal_judge = goal_judge
        # replanner：负责在目标未完成时决定是否需要重规划。
        self.replanner = replanner
        # max_iterations：最大循环轮次，用于防止控制器无限执行。
        self.max_iterations = max_iterations

    async def prepare(self, request: TaskControllerRequest) -> TaskRuntimeState:
        """准备目标与初始计划，但不执行后续步骤。

        参数说明：
        - `request`：控制器请求对象，包含用户输入、会话链路字段以及业务元数据。

        核心逻辑：
        1. 先把自然语言输入解析成结构化 goal；
        2. 再创建运行时状态对象；
        3. 把 request 中的链路信息下沉到状态 metadata；
        4. 生成首个任务计划，但暂不进入步骤执行。
        """
        # goal：由目标解析器产出的结构化目标对象，是后续规划与评估的输入基线。
        goal = await self.goal_parser.parse_goal(request)
        # state：本次任务运行时状态容器，后续所有中间结果都会持续回写到这里。
        state = TaskRuntimeState(
            goal=goal,
            max_iterations=self.max_iterations,
            metadata={
                **dict(request.metadata),
                "request_id": request.request_id,
                "execution_id": request.execution_id,
                "conversation_id": request.conversation_id,
                "message_id": request.message_id,
            },
        )
        await self._ensure_plan(state)
        return state

    async def run(self, request: TaskControllerRequest) -> TaskRuntimeState:
        """运行闭环控制流程并返回最终状态。

        这是非流式模式下的统一入口：内部仍走相同主循环，
        只是调用方不消费中间事件，只关心最终状态对象。
        """
        state = await self.prepare(request)
        await self._run_loop(state)
        return state

    async def run_stream(self, request: TaskControllerRequest) -> AsyncGenerator[TaskRuntimeControllerEvent, None]:
        """以事件流方式运行控制流程。

        与 `run()` 的区别在于：
        - `run()` 返回最终状态；
        - `run_stream()` 按阶段持续产出结构化事件，适合 SSE 或调试观测。
        """
        state = await self.prepare(request)

        async for event in self.run_stream_from_state(state):
            yield event

    async def run_stream_from_state(
        self,
        state: TaskRuntimeState,
        *,
        state_probe: StateProbe | None = None,
    ) -> AsyncGenerator[TaskRuntimeControllerEvent, None]:
        """基于已准备好的状态继续流式执行，避免重复生成 goal / plan。

        适用场景：
        - prepare 与 stream 分阶段调用；
        - 中断后基于已有状态继续执行；
        - 调用方需要先拿初始计划，再真正启动执行。

        实现要点：
        - 先同步发出 goal / planning 初始事件；
        - 再通过队列桥接后台主循环与前台事件消费；
        - 使用 `None` 作为结束哨兵，确保流能自然收尾。
        """

        # 基于已准备状态，先补发 goal_parsing 事件，便于前端或日志感知执行起点。
        yield self._build_event(
            state,
            stage="goal_parsing",
            message="任务目标解析完成。",
            payload={"goal": state.goal.model_dump()},
        )
        if state.current_plan is not None:
            yield self._build_event(
                state,
                stage="planning",
                message="初始计划已生成。",
                payload={"plan": state.current_plan.model_dump()},
                plan_id=state.current_plan.plan_id,
            )

        # queue：后台主循环与前台事件流之间的桥接队列；`None` 作为结束哨兵。
        queue: asyncio.Queue[TaskRuntimeControllerEvent | None] = asyncio.Queue()

        async def _emit(event: TaskRuntimeControllerEvent) -> None:
            await queue.put(event)

        async def _runner() -> None:
            try:
                await self._run_loop(state, emit_event=_emit, state_probe=state_probe)
            finally:
                await queue.put(None)

        task = asyncio.create_task(_runner())
        try:
            while True:
                event = await queue.get()
                if event is None:
                    break
                yield event
        finally:
            await task

    async def _run_loop(
        self,
        state: TaskRuntimeState,
        *,
        emit_event: EventEmitter | None = None,
        state_probe: StateProbe | None = None,
    ) -> None:
        """执行主循环，可选地向外发出结构化事件。

        这是任务控制器最核心的闭环逻辑。

        每轮循环大致分为：
        1. 探测外部运行状态（如暂停、取消）；
        2. 选出下一个可执行步骤；
        3. 若无步骤可执行，则进行整体目标评估；
        4. 若目标未完成，则决定是否重规划；
        5. 若有步骤可执行，则执行步骤并评估步骤结果；
        6. 达到终止条件时统一收敛为终止事件。
        """
        try:
            # 进入主循环前，先把运行时状态标记为 running。
            self._update_runtime_status(state, status="running")
            # 核心循环：只要任务尚未终止，就持续探测状态、执行步骤、评估目标。
            while not state.terminated:
                # 外部探针允许应用层把“暂停/取消”等外部控制信号反馈给控制器。
                external_status = await self._probe_runtime_status(state, state_probe)
                if external_status == "paused":
                    self._update_runtime_status(state, status="paused")
                    break
                if external_status == "cancelled":
                    self._terminate(
                        state,
                        status="failed",
                        reason="任务已取消，控制器停止执行。",
                        execution_status="cancelled",
                    )
                    await self._emit_termination_event(state, emit_event)
                    break

                # next_step：当前计划中下一个满足依赖且尚未完成的步骤。
                next_step = self._get_next_pending_step(state)
                if next_step is None:
                    # 当没有可执行步骤时，说明当前计划已跑完，需要从全局视角判断目标是否达成。
                    goal_evaluation = await self.goal_judge.evaluate_goal(state.goal, state)
                    state.goal_evaluations.append(goal_evaluation)
                    self._sync_goal_evaluation_outputs(state, goal_evaluation)
                    await self._emit_event(
                        emit_event,
                        self._build_event(
                            state,
                            stage="goal_evaluation",
                            message="已完成整体目标评估。",
                            payload={"goal_evaluation": goal_evaluation.model_dump()},
                        ),
                    )
                    if goal_evaluation.goal_completed:
                        self._terminate(
                            state,
                            status="completed",
                            reason=goal_evaluation.reasoning or "目标已完成。",
                            final_output=goal_evaluation.final_output,
                        )
                        await self._emit_termination_event(state, emit_event)
                        break

                    # 目标尚未完成时，进入重规划判断，决定是生成新计划还是终止。
                    replan_decision, next_plan = await self._apply_replan_decision(
                        state,
                        await self.replanner.decide_replan(
                            state.goal,
                            state,
                            goal_evaluation=goal_evaluation,
                        ),
                    )
                    await self._emit_replan_event(state, emit_event, replan_decision, next_plan)
                    if next_plan is None:
                        await self._emit_termination_event(state, emit_event)
                        break
                    continue

                if state.iteration_count >= state.max_iterations:
                    self._terminate(
                        state,
                        status="max_iterations",
                        reason="达到最大迭代次数，控制器终止。",
                    )
                    await self._emit_termination_event(state, emit_event)
                    break

                state.iteration_count += 1
                state.current_step_id = next_step.step_id
                self._update_runtime_status(state, status="running")
                await self._emit_event(
                    emit_event,
                    self._build_event(
                        state,
                        stage="step_started",
                        message=f"开始执行步骤：{next_step.title}",
                        payload={"step": next_step.model_dump()},
                        plan_id=state.current_plan.plan_id if state.current_plan else None,
                        step_id=next_step.step_id,
                    ),
                )

                observation = await self.step_executor.execute_step(next_step, state)
                state.step_observations.append(observation)
                self._ingest_step_artifacts(state, next_step, observation)
                await self._emit_event(
                    emit_event,
                    self._build_event(
                        state,
                        stage="step_observation",
                        message=observation.summary or f"步骤 {next_step.title} 已产出观测结果。",
                        payload={
                            "step": next_step.model_dump(),
                            "observation": observation.model_dump(),
                        },
                        plan_id=state.current_plan.plan_id if state.current_plan else None,
                        step_id=next_step.step_id,
                    ),
                )

                step_evaluation = await self.step_evaluator.evaluate_step(
                    next_step,
                    observation,
                    state.goal,
                    state,
                )
                state.step_evaluations.append(step_evaluation)
                await self._emit_event(
                    emit_event,
                    self._build_event(
                        state,
                        stage="step_evaluation",
                        message=step_evaluation.reasoning or f"步骤 {next_step.title} 已完成评估。",
                        payload={
                            "step": next_step.model_dump(),
                            "step_evaluation": step_evaluation.model_dump(),
                        },
                        plan_id=state.current_plan.plan_id if state.current_plan else None,
                        step_id=next_step.step_id,
                    ),
                )

                if step_evaluation.step_completed and next_step.step_id not in state.completed_step_ids:
                    state.completed_step_ids.append(next_step.step_id)
                state.updated_at = self._utc_now_iso()

                if step_evaluation.next_action == "retry":
                    continue

                if step_evaluation.next_action == "replan":
                    # 目标尚未完成时，进入重规划判断，决定是生成新计划还是终止。
                    replan_decision, next_plan = await self._apply_replan_decision(
                        state,
                        await self.replanner.decide_replan(
                            state.goal,
                            state,
                            step_evaluation=step_evaluation,
                        ),
                    )
                    await self._emit_replan_event(state, emit_event, replan_decision, next_plan)
                    if next_plan is None:
                        await self._emit_termination_event(state, emit_event)
                        break
        except Exception as error:
            self._terminate(
                state,
                status="failed",
                reason=f"控制器执行失败：{error}",
            )
            await self._emit_termination_event(
                state,
                emit_event,
                extra_payload={"error_message": str(error)},
            )

    async def _ensure_plan(self, state: TaskRuntimeState) -> TaskPlan:
        """确保当前状态存在可执行计划。"""
        if state.current_plan is not None:
            return state.current_plan
        plan = await self.planner.create_plan(state.goal, state)
        self._activate_plan(state, plan)
        return plan

    def _activate_plan(self, state: TaskRuntimeState, plan: TaskPlan) -> None:
        """激活一份新计划并记录计划历史。"""
        state.current_plan = plan
        state.plan_history.append(plan)

    def _get_next_pending_step(self, state: TaskRuntimeState) -> Optional[TaskPlanStep]:
        """返回当前计划中下一个可执行且未完成的步骤。"""
        if state.current_plan is None:
            return None

        completed_step_ids = set(state.completed_step_ids)
        for step in state.current_plan.steps:
            if step.step_id in completed_step_ids:
                continue
            if any(dependency not in completed_step_ids for dependency in step.depends_on):
                continue
            return step
        return None

    async def _apply_replan_decision(
        self,
        state: TaskRuntimeState,
        decision: ReplanDecision,
    ) -> tuple[ReplanDecision, TaskPlan | None]:
        """应用重规划决策，并返回新的计划（如有）。

        若决策结果为“不重规划”，则任务会被终止为 blocked；
        若允许重规划，则优先采用决策中携带的新计划，否则回退调用 planner 生成。
        """
        if not decision.should_replan:
            self._terminate(
                state,
                status="blocked",
                reason=decision.reason or "目标未完成且未生成新计划。",
            )
            return decision, None

        next_plan = decision.new_plan or await self.planner.create_plan(state.goal, state)
        self._activate_plan(state, next_plan)
        return decision, next_plan

    async def _emit_replan_event(
        self,
        state: TaskRuntimeState,
        emit_event: EventEmitter | None,
        decision: ReplanDecision,
        next_plan: TaskPlan | None,
    ) -> None:
        """统一发出重规划事件。

        这样无论是“未生成新计划”还是“成功切换到新计划”，
        上层都只需要消费同一种 stage=`replan` 的事件结构。
        """
        if next_plan is None and not decision.should_replan:
            await self._emit_event(
                emit_event,
                self._build_event(
                    state,
                    stage="replan",
                    message=decision.reason or "当前未生成新计划。",
                    payload={"replan_decision": decision.model_dump()},
                ),
            )
            return

        await self._emit_event(
            emit_event,
            self._build_event(
                state,
                stage="replan",
                message=decision.reason or "已生成新的任务计划。",
                payload={
                    "replan_decision": decision.model_dump(),
                    "plan": next_plan.model_dump() if next_plan is not None else None,
                },
                plan_id=next_plan.plan_id if next_plan is not None else None,
            ),
        )

    async def _emit_termination_event(
        self,
        state: TaskRuntimeState,
        emit_event: EventEmitter | None,
        extra_payload: dict | None = None,
    ) -> None:
        """统一发出终止事件。

        终止事件会尽量携带前端与持久化需要的完整上下文，
        包括终止决策、最终输出、引用、评估报告、标准产物与错误码。
        """
        # payload：终止阶段对外输出的统一载荷，尽量一次性给全上下文。
        payload = {
            "termination": state.termination.model_dump() if state.termination is not None else None,
            "final_output": self._extract_latest_final_output(state),
            "citations": self._extract_latest_citations(state),
            "evaluation_report": state.evaluation_report.model_dump() if state.evaluation_report is not None else None,
            "artifacts": [artifact.model_dump() for artifact in state.artifacts],
            "error_code": self._resolve_termination_error_code(state),
        }
        if extra_payload:
            payload.update(extra_payload)
        await self._emit_event(
            emit_event,
            self._build_event(
                state,
                stage="termination",
                message=(state.termination.reason if state.termination is not None else "控制器已终止。"),
                payload=payload,
                plan_id=state.current_plan.plan_id if state.current_plan is not None else None,
            ),
        )

    async def _emit_event(
        self,
        emit_event: EventEmitter | None,
        event: TaskRuntimeControllerEvent,
    ) -> None:
        """在外部需要时发出事件。

        控制器内部并不强制要求每次运行都输出事件，
        因此通过空判断支持“静默运行”和“流式运行”两种模式共存。
        """
        if emit_event is not None:
            await emit_event(event)

    @staticmethod
    def _build_event(
        state: TaskRuntimeState,
        *,
        stage: str,
        message: str,
        payload: dict | None = None,
        plan_id: str | None = None,
        step_id: str | None = None,
    ) -> TaskRuntimeControllerEvent:
        """构建统一控制器事件。

        所有阶段事件都在这里收敛为统一结构，
        以保证后续 SSE 翻译、日志记录和测试断言都基于同一事实来源。
        """
        # runtime_metadata：运行时元数据，通常包含 request_id / execution_id / conversation_id 等链路字段。
        runtime_metadata = state.metadata or {}
        resolved_plan_id = plan_id
        if resolved_plan_id is None and state.current_plan is not None:
            resolved_plan_id = state.current_plan.plan_id

        return TaskRuntimeControllerEvent(
            stage=stage,
            message=message,
            payload=payload or {},
            request_id=runtime_metadata.get("request_id"),
            conversation_id=state.goal.conversation_id,
            message_id=state.goal.source_message_id or runtime_metadata.get("message_id"),
            execution_id=runtime_metadata.get("execution_id"),
            plan_id=resolved_plan_id,
            step_id=step_id,
        )

    @staticmethod
    def _terminate(
        state: TaskRuntimeState,
        *,
        status: str,
        reason: str,
        final_output: Optional[str] = None,
        execution_status: str | None = None,
    ) -> None:
        """统一写入终止状态。"""
        state.terminated = True
        state.final_output = final_output
        state.current_step_id = None
        state.status = execution_status or TaskController._map_termination_to_execution_status(status)
        state.updated_at = TaskController._utc_now_iso()
        state.termination = TerminationDecision(
            status=status,
            reason=reason,
            final_output=final_output,
        )

    @staticmethod
    async def _probe_runtime_status(
        state: TaskRuntimeState,
        state_probe: StateProbe | None,
    ) -> str | None:
        """从外部探测任务状态，支持暂停/取消等生命周期动作。"""
        if state_probe is None:
            return None
        return await state_probe(state)

    @staticmethod
    def _update_runtime_status(state: TaskRuntimeState, *, status: str) -> None:
        """更新运行态状态与更新时间。"""
        state.status = status
        state.updated_at = TaskController._utc_now_iso()

    @staticmethod
    def _sync_goal_evaluation_outputs(state: TaskRuntimeState, goal_evaluation) -> None:
        """把 goal judge 产出的验收报告和最终文本同步回运行时状态。

        该方法负责把目标评估阶段的结构化结果沉淀进统一状态对象，
        避免最终输出、评估报告只停留在临时变量中。
        """
        # metadata：goal judge 返回的附加元数据，可能包含结构化评估报告。
        metadata = goal_evaluation.metadata or {}
        raw_report = metadata.get("evaluation_report")
        if isinstance(raw_report, dict):
            state.evaluation_report = TaskEvaluationReport.model_validate(raw_report)
        if goal_evaluation.final_output and not state.final_output:
            state.final_output = goal_evaluation.final_output
        if goal_evaluation.final_output:
            # 核心逻辑：最终文本也沉淀为标准 artifact，便于后续 resume / audit / frontend 展示。
            state.artifacts.append(
                TaskArtifact(
                    artifact_type="text",
                    title="final_output",
                    content=goal_evaluation.final_output,
                    source_plan_id=state.current_plan.plan_id if state.current_plan is not None else None,
                    metadata={"source": "goal_evaluation"},
                )
            )

    @staticmethod
    def _ingest_step_artifacts(state: TaskRuntimeState, step: TaskPlanStep, observation) -> None:
        """从步骤观测中抽取结构化产物，供前端与后续步骤复用。

        不同步骤类型会沉淀为不同 artifact：
        - retrieve -> evidence
        - tool_call -> tool_result
        - analyze -> text
        """
        if step.step_type == "retrieve":
            retrieved_items = observation.output_data.get("retrieved_items") or []
            if retrieved_items:
                state.artifacts.append(
                    TaskArtifact(
                        artifact_type="evidence",
                        title=step.title,
                        content=retrieved_items,
                        source_plan_id=state.current_plan.plan_id if state.current_plan is not None else None,
                        source_step_id=step.step_id,
                    )
                )
        if step.step_type == "tool_call" and observation.success:
            state.artifacts.append(
                TaskArtifact(
                    artifact_type="tool_result",
                    title=step.title,
                    content=observation.output_data,
                    source_plan_id=state.current_plan.plan_id if state.current_plan is not None else None,
                    source_step_id=step.step_id,
                )
            )
        if step.step_type == "analyze" and observation.output_data.get("analysis_summary"):
            state.artifacts.append(
                TaskArtifact(
                    artifact_type="text",
                    title=step.title,
                    content=observation.output_data.get("analysis_summary"),
                    source_plan_id=state.current_plan.plan_id if state.current_plan is not None else None,
                    source_step_id=step.step_id,
                )
            )

    @staticmethod
    def _map_termination_to_execution_status(termination_status: str) -> str:
        """将终止状态映射为任务执行状态。

        控制器内部终止状态更偏“原因语义”，
        应用层或持久化层执行状态更偏“展示/检索语义”，因此需要统一映射。
        """
        if termination_status == "completed":
            return "succeeded"
        if termination_status == "max_iterations":
            return "timed_out"
        return "failed"

    @staticmethod
    def _utc_now_iso() -> str:
        """生成当前 UTC ISO 时间文本。

        统一使用 UTC + ISO 8601，减少前后端与存储层时区歧义。
        """
        from datetime import datetime, timezone

        return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")

    @staticmethod
    def _extract_latest_final_output(state: TaskRuntimeState) -> Optional[str]:
        """优先从终止态读取最终输出，否则回退到最近一次生成步骤观测。

        这样可以兼容：
        - 已显式写入 `state.final_output` 的标准路径；
        - 仍停留在步骤观测中的兼容路径。
        """
        if state.final_output:
            return state.final_output

        for observation in reversed(state.step_observations):
            final_output = observation.output_data.get("final_output")
            if isinstance(final_output, str) and final_output.strip():
                return final_output
        return None

    @staticmethod
    def _extract_latest_citations(state: TaskRuntimeState) -> list[dict]:
        """提取最近一次生成步骤附带的引用信息，供 SSE 与持久化复用。

        这里统一做 list[dict] 过滤与转换，避免上层反复编写兼容逻辑。
        """
        for observation in reversed(state.step_observations):
            raw_citations = observation.output_data.get("citations")
            if isinstance(raw_citations, list):
                return [dict(item) for item in raw_citations if isinstance(item, dict)]
        return []

    @staticmethod
    def _resolve_termination_error_code(state: TaskRuntimeState) -> str | None:
        """统一推导终止阶段错误码，避免前端依赖 message 文本判断。

        终止时若没有稳定错误码，前端往往会退化为依赖 message 文本分支，
        因此这里显式把关键终止状态映射为统一错误码。
        """
        termination = state.termination
        if termination is None:
            return None
        if termination.status == "failed":
            return ErrorCode.WORKFLOW_EXECUTION_ERROR.value
        if termination.status == "blocked":
            return ErrorCode.WORKFLOW_INVALID_INPUT.value
        return None
