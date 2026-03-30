# -*- coding: utf-8 -*-
"""任务运行时 LLM 组件。

本模块负责：
1. 通过 `PromptManager` 统一读取 planner / critic Prompt；
2. 通过 `LangChainModelManager` 执行结构化模型调用；
3. 在模型不可用、Prompt 缺失或结构化结果非法时回退到规则组件；
4. 为 `task-runtime` 提供可渐进启用的 LLM 基础设施。
"""

from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass
from typing import Any, Literal, Sequence

from pydantic import BaseModel, ConfigDict, Field

from backend.application.task_runtime.default_components import (
    HeuristicPlanner,
    RuleBasedGoalJudge,
    RuleBasedGoalParser,
    RuleBasedReplanner,
    RuleBasedStepEvaluator,
    _build_plan_management_metadata,
    _build_step_management_metadata,
    _build_task_evaluation_report,
    _detect_conversation_intent,
    _infer_replan_failure_type,
    _looks_like_information_request,
    _normalize_goal_for_display,
    _normalize_text,
    _resolve_effective_user_input,
)
from backend.contracts.task_runtime import (
    GoalEvaluation,
    ReplanDecision,
    StepEvaluation,
    StepObservation,
    TaskControllerRequest,
    TaskGoal,
    TaskPlan,
    TaskPlanStep,
    TaskRuntimeState,
)
from backend.core.config_manager import ConfigManager, get_config_manager
from backend.core.llm_manager import LangChainModelManager, LangChainModelRuntime
from backend.core.prompt_manager import PromptManager, get_prompt_manager


logger = logging.getLogger(__name__)


# 用于识别简单四则运算表达式，作为工具调用判定的规则增强信号。
_ARITHMETIC_EXPRESSION_PATTERN = re.compile(
    r"(?P<expression>(?:\d+(?:\.\d+)?\s*[-+/*%]\s*)+\d+(?:\.\d+)?)"
)


def _json_dumps(payload: Any) -> str:
    """把对象稳定序列化为 Prompt 可消费的 JSON 文本。"""
    return json.dumps(payload, ensure_ascii=False, indent=2, default=str)


def _normalize_text(value: Any) -> str:
    """把任意输入规整为单行文本。"""
    return re.sub(r"\s+", " ", str(value or "")).strip()


def _sanitize_string_list(values: Sequence[Any] | None) -> list[str]:
    """清洗字符串数组，避免空值和噪声项进入契约对象。"""
    sanitized_values: list[str] = []
    for value in values or []:
        normalized_value = _normalize_text(value)
        if normalized_value:
            sanitized_values.append(normalized_value)
    return sanitized_values


def _clamp_score(score: float | int | None) -> float:
    """把模型分数稳定裁剪到 0 到 1。"""
    try:
        numeric_score = float(score)
    except (TypeError, ValueError):
        numeric_score = 0.0
    return max(0.0, min(1.0, numeric_score))


def _detect_arithmetic_expression(text: str) -> str | None:
    """从用户输入中提取可计算的简单表达式。"""
    match = _ARITHMETIC_EXPRESSION_PATTERN.search(text or "")
    if not match:
        return None
    return match.group("expression").strip()


def _build_state_snapshot(state: TaskRuntimeState) -> dict[str, Any]:
    """压缩运行时状态，避免直接把完整内部对象细节暴露给 Prompt。"""
    # 这里只截取最近若干条计划/观察/评估信息，
    # 既能给模型提供足够上下文，也能避免 Prompt 因状态过大而失控。
    return {
        "current_plan": state.current_plan.model_dump() if state.current_plan is not None else None,
        "plan_history": [plan.model_dump() for plan in state.plan_history[-3:]],
        "completed_step_ids": list(state.completed_step_ids),
        "step_observations": [observation.model_dump() for observation in state.step_observations[-5:]],
        "step_evaluations": [evaluation.model_dump() for evaluation in state.step_evaluations[-5:]],
        "goal_evaluations": [evaluation.model_dump() for evaluation in state.goal_evaluations[-3:]],
        "iteration_count": state.iteration_count,
        "max_iterations": state.max_iterations,
        "terminated": state.terminated,
        "final_output": state.final_output,
        "metadata": dict(state.metadata),
    }


@dataclass(frozen=True)
class TaskRuntimeLLMSettings:
    """任务运行时 LLM 组件配置。"""

    # 总开关：关闭时整个 task-runtime 不装配 LLM 组件。
    enable_llm_components: bool = False
    # 初始化或调用失败时，是否允许回退到规则版组件。
    fallback_to_rule_based: bool = True
    # 统一模型类型标识，由模型管理器映射到具体 provider/model。
    model: str = "primary"
    # 分组件开关，支持渐进启用和灰度排障。
    goal_parser_enabled: bool = True
    planner_enabled: bool = True
    step_evaluator_enabled: bool = True
    goal_judge_enabled: bool = True
    replanner_enabled: bool = True
    # 不同组件使用独立温度，便于控制“生成”和“判定”的稳定性。
    goal_parser_temperature: float = 0.2
    planner_temperature: float = 0.2
    critic_temperature: float = 0.1
    replanner_temperature: float = 0.2
    # 统一控制结构化输出 token 上限，避免单次调用过大。
    max_tokens: int = 1400

    @classmethod
    def from_config_manager(cls, config_manager: ConfigManager | None = None) -> "TaskRuntimeLLMSettings":
        """从统一配置中心读取 task runtime LLM 配置。"""
        resolved_config_manager = config_manager or get_config_manager()
        task_runtime_config = resolved_config_manager.get("agent.task_runtime", {}) or {}
        return cls(
            enable_llm_components=bool(task_runtime_config.get("enable_llm_components", False)),
            fallback_to_rule_based=bool(task_runtime_config.get("fallback_to_rule_based", True)),
            model=str(task_runtime_config.get("model", "primary") or "primary"),
            goal_parser_enabled=bool(task_runtime_config.get("goal_parser_enabled", True)),
            planner_enabled=bool(task_runtime_config.get("planner_enabled", True)),
            step_evaluator_enabled=bool(task_runtime_config.get("step_evaluator_enabled", True)),
            goal_judge_enabled=bool(task_runtime_config.get("goal_judge_enabled", True)),
            replanner_enabled=bool(task_runtime_config.get("replanner_enabled", True)),
            goal_parser_temperature=float(task_runtime_config.get("goal_parser_temperature", 0.2) or 0.2),
            planner_temperature=float(task_runtime_config.get("planner_temperature", 0.2) or 0.2),
            critic_temperature=float(task_runtime_config.get("critic_temperature", 0.1) or 0.1),
            replanner_temperature=float(task_runtime_config.get("replanner_temperature", 0.2) or 0.2),
            max_tokens=max(1, int(task_runtime_config.get("max_tokens", 1400) or 1400)),
        )

class GoalParseStructuredOutput(BaseModel):
    """目标解析器结构化输出。"""

    # extra=forbid：强制模型输出严格遵循 schema，避免字段漂移。
    model_config = ConfigDict(extra="forbid")

    # 归一化后的任务目标，会作为后续 planner 的核心输入。
    normalized_goal: str
    # 成功标准，用于后续 goal judge 判断任务是否完成。
    success_criteria: list[str] = Field(default_factory=list)
    # 约束信息，如语言、格式、范围等。
    constraints: dict[str, Any] = Field(default_factory=dict)
    # 模型建议是否需要检索，后续还会结合规则信号修正。
    needs_retrieval: bool = False
    # 模型建议是否需要工具调用，后续也允许规则兜底增强。
    needs_tool_call: bool = False
    # 扩展元数据，承载非主链路辅助信息。
    metadata: dict[str, Any] = Field(default_factory=dict)


class TaskPlanStepStructuredOutput(BaseModel):
    """规划步骤结构化输出。"""

    model_config = ConfigDict(extra="forbid")

    step_type: Literal["clarify", "retrieve", "tool_call", "analyze", "synthesize_answer", "custom"]
    title: str
    description: str = ""
    depends_on_indices: list[int] = Field(default_factory=list)
    acceptance_criteria: list[str] = Field(default_factory=list)
    required_capabilities: list[str] = Field(default_factory=list)
    timeout_seconds: int | None = None
    retry_policy: dict[str, Any] = Field(default_factory=dict)
    produces_artifacts: list[str] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)


class TaskPlanStructuredOutput(BaseModel):
    """规划器结构化输出。"""

    model_config = ConfigDict(extra="forbid")

    reasoning: str = ""
    steps: list[TaskPlanStepStructuredOutput] = Field(default_factory=list)
    acceptance_criteria: list[str] = Field(default_factory=list)
    required_capabilities: list[str] = Field(default_factory=list)
    risk_level: str = "medium"
    estimated_cost: float = 0.0
    retry_policy: dict[str, Any] = Field(default_factory=dict)
    timeout_seconds: int | None = None
    produces_artifacts: list[str] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)


class StepEvaluationStructuredOutput(BaseModel):
    """步骤评估器结构化输出。"""

    model_config = ConfigDict(extra="forbid")

    step_completed: bool
    contributes_to_goal: bool
    next_action: Literal["continue", "retry", "replan"] = "continue"
    quality_score: float = 0.0
    issues: list[str] = Field(default_factory=list)
    reasoning: str = ""
    metadata: dict[str, Any] = Field(default_factory=dict)


class GoalJudgementStructuredOutput(BaseModel):
    """目标判定器结构化输出。"""

    model_config = ConfigDict(extra="forbid")

    goal_completed: bool
    completion_score: float = 0.0
    missing_items: list[str] = Field(default_factory=list)
    satisfied_criteria: list[str] = Field(default_factory=list)
    risks: list[str] = Field(default_factory=list)
    recommendations: list[str] = Field(default_factory=list)
    reasoning: str = ""
    final_output: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class ReplanStructuredOutput(BaseModel):
    """重规划器结构化输出。"""

    model_config = ConfigDict(extra="forbid")

    should_replan: bool
    reason: str = ""
    failure_type: str = ""
    plan_reasoning: str = ""
    steps: list[TaskPlanStepStructuredOutput] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)


@dataclass(frozen=True)
class TaskRuntimeLLMComponentBundle:
    """任务运行时 LLM 组件集合。"""

    goal_parser: LLMGoalParser | RuleBasedGoalParser
    planner: LLMPlanner | HeuristicPlanner
    step_evaluator: LLMStepEvaluator | RuleBasedStepEvaluator
    goal_judge: LLMGoalJudge | RuleBasedGoalJudge
    replanner: LLMReplanner | RuleBasedReplanner


class _TaskRuntimeLLMComponentBase:
    """任务运行时 LLM 组件基础能力。"""

    def __init__(
        self,
        *,
        prompt_manager: PromptManager,
        model_manager: LangChainModelManager,
        settings: TaskRuntimeLLMSettings,
    ) -> None:
        self.prompt_manager = prompt_manager
        self.model_manager = model_manager
        self.settings = settings

    def _build_chat_prompt_call(
        self,
        *,
        system_prompt_key: str,
        user_prompt_key: str,
        user_variables: dict[str, Any],
    ):
        """构造统一的 ChatPromptTemplate 调用参数。"""
        # 提前校验 Prompt 是否存在，避免模型调用后才暴露配置缺失问题。
        if not self.prompt_manager.get_prompt(system_prompt_key):
            raise ValueError(f"{system_prompt_key} is not configured")
        if not self.prompt_manager.get_prompt(user_prompt_key):
            raise ValueError(f"{user_prompt_key} is not configured")
        return self.prompt_manager.build_chat_prompt_call(
            user_prompt_key=user_prompt_key,
            user_variables=user_variables,
            system_prompt_key=system_prompt_key,
            user_prompt_default="{goal_json}",
        )

    async def _invoke_structured_prompt(
        self,
        *,
        system_prompt_key: str,
        user_prompt_key: str,
        user_variables: dict[str, Any],
        output_schema: type[BaseModel],
        temperature: float,
    ) -> BaseModel:
        """执行统一的结构化 Prompt 调用。"""
        # 所有 LLM 组件统一走结构化输出链路，保证：
        # 1. Prompt 来源统一；2. 输出 schema 统一；3. 运行参数统一。
        prompt_template, prompt_variables = self._build_chat_prompt_call(
            system_prompt_key=system_prompt_key,
            user_prompt_key=user_prompt_key,
            user_variables=user_variables,
        )
        return await self.model_manager.with_structured_output(output_schema).invoke_chat_prompt_template(
            prompt_template,
            prompt_variables,
            temperature=temperature,
            max_tokens=self.settings.max_tokens,
        )

    @staticmethod
    def _build_plan_from_structured_output(
        *,
        goal: TaskGoal,
        state: TaskRuntimeState,
        plan_output: TaskPlanStructuredOutput,
    ) -> TaskPlan:
        """把 LLM 规划输出转换为标准 `TaskPlan`。"""
        if not plan_output.steps:
            raise ValueError("LLM planner returned empty steps")

        # 计划版本号基于历史递增，便于后续审计和多轮重规划回溯。
        previous_version = state.plan_history[-1].version if state.plan_history else 0
        plan_steps: list[TaskPlanStep] = []
        step_id_by_index: dict[int, str] = {}
        # 目标解析阶段若已识别出数学表达式，后续工具步骤直接复用该结果。
        detected_expression = state.goal.metadata.get("detected_expression")

        for index, step_output in enumerate(plan_output.steps, start=1):
            step_metadata = dict(step_output.metadata or {})
            # 根据步骤类型补充最小必要的运行时管理信息。
            if step_output.step_type == "retrieve":
                step_metadata.setdefault("retrieval_required", True)
            if step_output.step_type == "tool_call" and detected_expression:
                step_metadata.setdefault("expression", detected_expression)
            step_metadata = _build_step_management_metadata(
                goal,
                step_type=step_output.step_type,
                acceptance_criteria=_sanitize_string_list(step_output.acceptance_criteria),
                base_metadata=step_metadata,
            )
            if step_output.required_capabilities:
                step_metadata["required_capabilities"] = _sanitize_string_list(step_output.required_capabilities)
            if step_output.timeout_seconds is not None:
                step_metadata["timeout_seconds"] = max(1, int(step_output.timeout_seconds))
            if step_output.retry_policy:
                step_metadata["retry_policy"] = dict(step_output.retry_policy)
            if step_output.produces_artifacts:
                step_metadata["produces_artifacts"] = _sanitize_string_list(step_output.produces_artifacts)

            task_step = TaskPlanStep(
                step_type=step_output.step_type,
                title=_normalize_text(step_output.title) or f"步骤{index}",
                description=_normalize_text(step_output.description),
                metadata=step_metadata,
            )
            plan_steps.append(task_step)
            step_id_by_index[index] = task_step.step_id

        for index, step_output in enumerate(plan_output.steps, start=1):
            # 仅保留合法的前置依赖，避免模型给出循环依赖或非法索引。
            valid_indices = sorted(
                {
                    dependency_index
                    for dependency_index in step_output.depends_on_indices
                    if 0 < dependency_index < index and dependency_index in step_id_by_index
                }
            )
            plan_steps[index - 1].depends_on = [step_id_by_index[dependency_index] for dependency_index in valid_indices]

        # 当前运行时要求计划必须包含最终答案汇总步骤，否则无法自然收敛给用户答复。
        if not any(plan_step.step_type == "synthesize_answer" for plan_step in plan_steps):
            raise ValueError("LLM planner must include synthesize_answer step")

        plan_metadata = dict(plan_output.metadata or {})
        default_plan_metadata = _build_plan_management_metadata(goal, step_count=len(plan_steps), strategy="llm_structured_plan")
        plan_metadata = {**default_plan_metadata, **plan_metadata}
        if plan_output.acceptance_criteria:
            plan_metadata["acceptance_criteria"] = _sanitize_string_list(plan_output.acceptance_criteria)
        if plan_output.required_capabilities:
            plan_metadata["required_capabilities"] = _sanitize_string_list(plan_output.required_capabilities)
        plan_metadata["risk_level"] = _normalize_text(plan_output.risk_level) or plan_metadata.get("risk_level")
        if plan_output.estimated_cost:
            plan_metadata["estimated_cost"] = float(plan_output.estimated_cost)
        if plan_output.retry_policy:
            plan_metadata["retry_policy"] = dict(plan_output.retry_policy)
        if plan_output.timeout_seconds is not None:
            plan_metadata["timeout_seconds"] = max(1, int(plan_output.timeout_seconds))
        if plan_output.produces_artifacts:
            plan_metadata["produces_artifacts"] = _sanitize_string_list(plan_output.produces_artifacts)
        return TaskPlan(
            goal_id=goal.goal_id,
            version=previous_version + 1,
            reasoning=_normalize_text(plan_output.reasoning),
            steps=plan_steps,
            metadata=plan_metadata,
        )


class LLMGoalParser(_TaskRuntimeLLMComponentBase):
    """基于 LLM 的目标解析器。"""

    def __init__(
        self,
        *,
        prompt_manager: PromptManager,
        model_manager: LangChainModelManager,
        settings: TaskRuntimeLLMSettings,
        fallback: RuleBasedGoalParser,
    ) -> None:
        super().__init__(prompt_manager=prompt_manager, model_manager=model_manager, settings=settings)
        self.fallback = fallback

    async def parse_goal(self, request: TaskControllerRequest) -> TaskGoal:
        """把用户输入解析为标准 `TaskGoal`，失败时自动回退到规则解析。"""
        try:
            # 统一解析“有效用户输入”和透传 metadata：
            # - 有些请求会在 metadata 中附带改写后的输入；
            # - 这里先做一次归一，避免后续 Prompt 和规则判断拿到不同文本。
            effective_user_input, effective_metadata = _resolve_effective_user_input(request.user_input, dict(request.metadata))
            # 合并原始输入与有效输入，便于规则方法提取数学表达式等局部信号。
            combined_user_input = _normalize_text(f"{effective_user_input} {request.user_input}")
            prompt_result = await self._invoke_structured_prompt(
                system_prompt_key="planner.planner_goal_parser_system_prompt",
                user_prompt_key="planner.planner_goal_parser_user_prompt",
                user_variables={
                    "user_input": effective_user_input,
                    "request_metadata_json": _json_dumps(effective_metadata),
                },
                output_schema=GoalParseStructuredOutput,
                temperature=self.settings.goal_parser_temperature,
            )
            structured_output = GoalParseStructuredOutput.model_validate(prompt_result)
            goal_metadata = dict(effective_metadata)
            goal_metadata.update(structured_output.metadata)
            # 识别会话意图，后续会直接影响规划、检索和最终回答策略。
            conversation_intent = _detect_conversation_intent(effective_user_input)
            goal_metadata["conversation_intent"] = conversation_intent

            # 通过规则补充表达式识别，避免模型漏掉显式计算型需求。
            detected_expression = _detect_arithmetic_expression(combined_user_input)
            if detected_expression:
                goal_metadata["detected_expression"] = detected_expression
            if conversation_intent == "smalltalk":
                # 寒暄/闲聊类输入通常不需要走检索链路。
                goal_metadata["needs_retrieval"] = False
            else:
                goal_metadata["needs_retrieval"] = bool(
                    structured_output.needs_retrieval
                    or (
                        (goal_metadata.get("enable_knowledge_base") or goal_metadata.get("knowledge_base_id"))
                        and _looks_like_information_request(combined_user_input)
                    )
                )
            # 只要模型判断需要工具，或规则发现了数学表达式，就标记为需要工具调用。
            goal_metadata["needs_tool_call"] = bool(structured_output.needs_tool_call or detected_expression)

            goal_constraints = dict(structured_output.constraints or {})
            # 当前项目默认中文输出，作为缺省约束写入 goal。
            goal_constraints.setdefault("language", "zh-CN")

            normalized_goal = _normalize_text(structured_output.normalized_goal) or _normalize_goal_for_display(effective_user_input)
            if conversation_intent == "smalltalk":
                # 对闲聊场景保留更自然的展示目标，而不是过度任务化抽象。
                normalized_goal = _normalize_goal_for_display(effective_user_input)
            success_criteria = _sanitize_string_list(structured_output.success_criteria) or ["给出与用户目标直接对应的结果"]
            return TaskGoal(
                user_id=request.user_id,
                conversation_id=request.conversation_id,
                source_message_id=request.message_id,
                original_user_input=effective_user_input,
                normalized_goal=normalized_goal,
                success_criteria=success_criteria,
                constraints=goal_constraints,
                metadata=goal_metadata,
            )
        except Exception as error:
            logger.warning("LLMGoalParser failed, fallback to rule-based parser: %s", error)
            return await self.fallback.parse_goal(request)


class LLMPlanner(_TaskRuntimeLLMComponentBase):
    """基于 LLM 的任务规划器。"""

    def __init__(
        self,
        *,
        prompt_manager: PromptManager,
        model_manager: LangChainModelManager,
        settings: TaskRuntimeLLMSettings,
        fallback: HeuristicPlanner,
    ) -> None:
        super().__init__(prompt_manager=prompt_manager, model_manager=model_manager, settings=settings)
        self.fallback = fallback

    async def create_plan(self, goal: TaskGoal, state: TaskRuntimeState) -> TaskPlan:
        """根据目标与状态生成结构化计划，失败时退回启发式规划。"""
        # 寒暄类输入优先复用启发式直答策略，避免 LLM 规划出多余检索/分析步骤。
        if goal.metadata.get("conversation_intent") == "smalltalk":
            return await self.fallback.create_plan(goal, state)
        try:
            prompt_result = await self._invoke_structured_prompt(
                system_prompt_key="planner.planner_task_decomposition_system_prompt",
                user_prompt_key="planner.planner_task_decomposition_user_prompt",
                user_variables={
                    "goal_json": _json_dumps(goal.model_dump()),
                    "runtime_state_json": _json_dumps(_build_state_snapshot(state)),
                },
                output_schema=TaskPlanStructuredOutput,
                temperature=self.settings.planner_temperature,
            )
            structured_output = TaskPlanStructuredOutput.model_validate(prompt_result)
            return self._build_plan_from_structured_output(goal=goal, state=state, plan_output=structured_output)
        except Exception as error:
            logger.warning("LLMPlanner failed, fallback to heuristic planner: %s", error)
            return await self.fallback.create_plan(goal, state)


class LLMStepEvaluator(_TaskRuntimeLLMComponentBase):
    """基于 LLM 的步骤评估器。"""

    def __init__(
        self,
        *,
        prompt_manager: PromptManager,
        model_manager: LangChainModelManager,
        settings: TaskRuntimeLLMSettings,
        fallback: RuleBasedStepEvaluator,
    ) -> None:
        super().__init__(prompt_manager=prompt_manager, model_manager=model_manager, settings=settings)
        self.fallback = fallback

    async def evaluate_step(
        self,
        step: TaskPlanStep,
        observation: StepObservation,
        goal: TaskGoal,
        state: TaskRuntimeState,
    ) -> StepEvaluation:
        """评估单个步骤结果，失败时回退到规则评估。"""
        try:
            prompt_result = await self._invoke_structured_prompt(
                system_prompt_key="critic.critic_step_evaluation_system_prompt",
                user_prompt_key="critic.critic_step_evaluation_user_prompt",
                user_variables={
                    "goal_json": _json_dumps(goal.model_dump()),
                    "step_json": _json_dumps(step.model_dump()),
                    "observation_json": _json_dumps(observation.model_dump()),
                    "runtime_state_json": _json_dumps(_build_state_snapshot(state)),
                },
                output_schema=StepEvaluationStructuredOutput,
                temperature=self.settings.critic_temperature,
            )
            structured_output = StepEvaluationStructuredOutput.model_validate(prompt_result)
            # 将模型返回值再次映射为项目内部契约对象，
            # 防止上层依赖 Prompt schema 细节。
            return StepEvaluation(
                step_id=step.step_id,
                step_completed=structured_output.step_completed,
                contributes_to_goal=structured_output.contributes_to_goal,
                next_action=structured_output.next_action,
                quality_score=_clamp_score(structured_output.quality_score),
                issues=_sanitize_string_list(structured_output.issues),
                reasoning=_normalize_text(structured_output.reasoning),
                metadata=dict(structured_output.metadata),
            )
        except Exception as error:
            logger.warning("LLMStepEvaluator failed, fallback to rule-based evaluator: %s", error)
            return await self.fallback.evaluate_step(step, observation, goal, state)


class LLMGoalJudge(_TaskRuntimeLLMComponentBase):
    """基于 LLM 的整体目标判定器。"""

    def __init__(
        self,
        *,
        prompt_manager: PromptManager,
        model_manager: LangChainModelManager,
        settings: TaskRuntimeLLMSettings,
        fallback: RuleBasedGoalJudge,
    ) -> None:
        super().__init__(prompt_manager=prompt_manager, model_manager=model_manager, settings=settings)
        self.fallback = fallback

    async def evaluate_goal(self, goal: TaskGoal, state: TaskRuntimeState) -> GoalEvaluation:
        """判断整体目标是否完成，失败时回退到规则判定。"""
        try:
            prompt_result = await self._invoke_structured_prompt(
                system_prompt_key="critic.critic_goal_judgement_system_prompt",
                user_prompt_key="critic.critic_goal_judgement_user_prompt",
                user_variables={
                    "goal_json": _json_dumps(goal.model_dump()),
                    "runtime_state_json": _json_dumps(_build_state_snapshot(state)),
                },
                output_schema=GoalJudgementStructuredOutput,
                temperature=self.settings.critic_temperature,
            )
            structured_output = GoalJudgementStructuredOutput.model_validate(prompt_result)
            goal_evaluation = GoalEvaluation(
                goal_id=goal.goal_id,
                goal_completed=structured_output.goal_completed,
                completion_score=_clamp_score(structured_output.completion_score),
                missing_items=_sanitize_string_list(structured_output.missing_items),
                reasoning=_normalize_text(structured_output.reasoning),
                final_output=structured_output.final_output,
                metadata=dict(structured_output.metadata),
            )
            # 汇总报告更偏“可观测信息”，因此挂到 metadata 中，
            # 保持 GoalEvaluation 主字段稳定简洁。
            evaluation_report = _build_task_evaluation_report(goal, state, goal_evaluation)
            if structured_output.satisfied_criteria:
                evaluation_report.satisfied_criteria = _sanitize_string_list(structured_output.satisfied_criteria)
            if structured_output.risks:
                evaluation_report.risks = _sanitize_string_list(structured_output.risks)
            if structured_output.recommendations:
                evaluation_report.recommendations = _sanitize_string_list(structured_output.recommendations)
            goal_evaluation.metadata["evaluation_report"] = evaluation_report.model_dump()
            return goal_evaluation
        except Exception as error:
            logger.warning("LLMGoalJudge failed, fallback to rule-based judge: %s", error)
            return await self.fallback.evaluate_goal(goal, state)


class LLMReplanner(_TaskRuntimeLLMComponentBase):
    """基于 LLM 的重规划器。"""

    def __init__(
        self,
        *,
        prompt_manager: PromptManager,
        model_manager: LangChainModelManager,
        settings: TaskRuntimeLLMSettings,
        fallback: RuleBasedReplanner,
    ) -> None:
        super().__init__(prompt_manager=prompt_manager, model_manager=model_manager, settings=settings)
        self.fallback = fallback

    async def decide_replan(
        self,
        goal: TaskGoal,
        state: TaskRuntimeState,
        *,
        goal_evaluation: GoalEvaluation | None = None,
        step_evaluation: StepEvaluation | None = None,
    ) -> ReplanDecision:
        """决定是否需要重规划，失败时回退到规则重规划器。"""
        try:
            prompt_result = await self._invoke_structured_prompt(
                system_prompt_key="planner.planner_replan_system_prompt",
                user_prompt_key="planner.planner_replan_user_prompt",
                user_variables={
                    "goal_json": _json_dumps(goal.model_dump()),
                    "runtime_state_json": _json_dumps(_build_state_snapshot(state)),
                    "step_evaluation_json": _json_dumps(step_evaluation.model_dump() if step_evaluation is not None else {}),
                    "goal_evaluation_json": _json_dumps(goal_evaluation.model_dump() if goal_evaluation is not None else {}),
                },
                output_schema=ReplanStructuredOutput,
                temperature=self.settings.replanner_temperature,
            )
            structured_output = ReplanStructuredOutput.model_validate(prompt_result)
            new_plan: TaskPlan | None = None
            if structured_output.should_replan and structured_output.steps:
                # 重规划时先把 LLM 输出包装成标准计划结构，
                # 再复用统一计划转换逻辑，避免新旧计划构造路径分叉。
                plan_output = TaskPlanStructuredOutput(
                    reasoning=structured_output.plan_reasoning,
                    steps=structured_output.steps,
                    metadata={
                        **dict(structured_output.metadata),
                        "failure_type": _normalize_text(structured_output.failure_type)
                        or _infer_replan_failure_type(step_evaluation, goal_evaluation),
                    },
                )
                new_plan = self._build_plan_from_structured_output(goal=goal, state=state, plan_output=plan_output)
            return ReplanDecision(
                should_replan=structured_output.should_replan,
                reason=_normalize_text(structured_output.reason),
                new_plan=new_plan,
                metadata={
                    **dict(structured_output.metadata),
                    "failure_type": _normalize_text(structured_output.failure_type)
                    or _infer_replan_failure_type(step_evaluation, goal_evaluation),
                },
            )
        except Exception as error:
            logger.warning("LLMReplanner failed, fallback to rule-based replanner: %s", error)
            return await self.fallback.decide_replan(
                goal,
                state,
                goal_evaluation=goal_evaluation,
                step_evaluation=step_evaluation,
            )


def build_task_runtime_llm_bundle(
    *,
    config_manager: ConfigManager | None = None,
    prompt_manager: PromptManager | None = None,
    model_manager: LangChainModelManager | None = None,
    force_enable: bool = False,
) -> TaskRuntimeLLMComponentBundle | None:
    """构建任务运行时 LLM 组件集合。

    当配置未启用 LLM 组件时返回 `None`；
    若初始化模型运行时失败，则按配置决定是否优雅降级。
    """
    resolved_config_manager = config_manager or get_config_manager()
    settings = TaskRuntimeLLMSettings.from_config_manager(resolved_config_manager)
    if not force_enable and not settings.enable_llm_components:
        # 未启用时直接返回 None，由调用方继续使用规则组件即可。
        return None

    try:
        resolved_prompt_manager = prompt_manager or get_prompt_manager()
        resolved_model_manager = model_manager or LangChainModelManager(
            runtime=LangChainModelRuntime(
                config_manager=resolved_config_manager,
                model_type=settings.model,
            )
        )
    except Exception as error:
        logger.warning("Failed to initialize task runtime LLM bundle: %s", error)
        if settings.fallback_to_rule_based:
            # 初始化失败时整体回退，而不是返回半初始化对象，
            # 这样运行期行为更可预测，也更容易排障。
            return None
        raise

    rule_based_goal_parser = RuleBasedGoalParser()
    heuristic_planner = HeuristicPlanner()
    rule_based_step_evaluator = RuleBasedStepEvaluator()
    rule_based_goal_judge = RuleBasedGoalJudge()
    rule_based_replanner = RuleBasedReplanner()

    return TaskRuntimeLLMComponentBundle(
        # 每个组件都支持独立灰度启用：
        # 开启时使用 LLM 版本，关闭时回到规则版本。
        goal_parser=(
            LLMGoalParser(
                prompt_manager=resolved_prompt_manager,
                model_manager=resolved_model_manager,
                settings=settings,
                fallback=rule_based_goal_parser,
            )
            if settings.goal_parser_enabled
            else rule_based_goal_parser
        ),
        planner=(
            LLMPlanner(
                prompt_manager=resolved_prompt_manager,
                model_manager=resolved_model_manager,
                settings=settings,
                fallback=heuristic_planner,
            )
            if settings.planner_enabled
            else heuristic_planner
        ),
        step_evaluator=(
            LLMStepEvaluator(
                prompt_manager=resolved_prompt_manager,
                model_manager=resolved_model_manager,
                settings=settings,
                fallback=rule_based_step_evaluator,
            )
            if settings.step_evaluator_enabled
            else rule_based_step_evaluator
        ),
        goal_judge=(
            LLMGoalJudge(
                prompt_manager=resolved_prompt_manager,
                model_manager=resolved_model_manager,
                settings=settings,
                fallback=rule_based_goal_judge,
            )
            if settings.goal_judge_enabled
            else rule_based_goal_judge
        ),
        replanner=(
            LLMReplanner(
                prompt_manager=resolved_prompt_manager,
                model_manager=resolved_model_manager,
                settings=settings,
                fallback=rule_based_replanner,
            )
            if settings.replanner_enabled
            else rule_based_replanner
        ),
    )

__all__ = [
    "GoalJudgementStructuredOutput",
    "GoalParseStructuredOutput",
    "LLMGoalJudge",
    "LLMGoalParser",
    "LLMPlanner",
    "LLMReplanner",
    "LLMStepEvaluator",
    "ReplanStructuredOutput",
    "StepEvaluationStructuredOutput",
    "TaskPlanStepStructuredOutput",
    "TaskPlanStructuredOutput",
    "TaskRuntimeLLMComponentBundle",
    "TaskRuntimeLLMSettings",
    "build_task_runtime_llm_bundle",
]
