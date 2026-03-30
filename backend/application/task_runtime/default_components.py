from __future__ import annotations

import ast
import logging
import operator
import re
from typing import Any

from backend.application.task_runtime.task_controller import TaskController
from backend.contracts.task_runtime import (
    GoalEvaluation,
    ReplanDecision,
    StepEvaluation,
    StepObservation,
    TaskEvaluationReport,
    TaskControllerRequest,
    TaskGoal,
    TaskPlan,
    TaskPlanStep,
    TaskRuntimeState,
)

logger = logging.getLogger(__name__)


_ALLOWED_BINARY_OPERATORS = {
    ast.Add: operator.add,
    ast.Sub: operator.sub,
    ast.Mult: operator.mul,
    ast.Div: operator.truediv,
    ast.Mod: operator.mod,
}
_ALLOWED_UNARY_OPERATORS = {
    ast.UAdd: operator.pos,
    ast.USub: operator.neg,
}
_ARITHMETIC_EXPRESSION_PATTERN = re.compile(
    r"(?P<expression>(?:\d+(?:\.\d+)?\s*[-+/*%]\s*)+\d+(?:\.\d+)?)"
)
_SMALLTALK_ONLY_PATTERN = re.compile(r"^(?:哈|呵|嘿|嗨|嗯|哦|啊)+$")


def _safe_evaluate_expression(expression: str) -> float | int:
    """安全计算基础四则表达式。"""
    parsed = ast.parse(expression, mode="eval")

    def _evaluate(node: ast.AST) -> float | int:
        if isinstance(node, ast.Expression):
            return _evaluate(node.body)
        if isinstance(node, ast.Constant) and isinstance(node.value, (int, float)):
            return node.value
        if isinstance(node, ast.BinOp) and type(node.op) in _ALLOWED_BINARY_OPERATORS:
            return _ALLOWED_BINARY_OPERATORS[type(node.op)](_evaluate(node.left), _evaluate(node.right))
        if isinstance(node, ast.UnaryOp) and type(node.op) in _ALLOWED_UNARY_OPERATORS:
            return _ALLOWED_UNARY_OPERATORS[type(node.op)](_evaluate(node.operand))
        raise ValueError("仅支持基础数字四则运算")

    return _evaluate(parsed)


def _detect_arithmetic_expression(text: str) -> str | None:
    """从用户输入中提取可计算的简单表达式。"""
    match = _ARITHMETIC_EXPRESSION_PATTERN.search(text or "")
    if not match:
        return None
    return match.group("expression").strip()


def _normalize_text(value: Any) -> str:
    """把任意输入规整为单行文本。"""
    return re.sub(r"\s+", " ", str(value or "")).strip()


def _normalize_intent_text(value: Any) -> str:
    """把输入规整为便于意图识别的紧凑文本。"""
    normalized_value = _normalize_text(value).lower()
    return re.sub(r"[\s\.,，。!！?？~～:：;；、]+", "", normalized_value)


def _extract_previous_user_message(metadata: dict[str, Any]) -> str | None:
    """从请求元信息中提取上一条有效的用户问题。"""
    direct_value = _normalize_text(metadata.get("previous_user_message"))
    if direct_value:
        return direct_value

    raw_recent_messages = metadata.get("recent_messages")
    if isinstance(raw_recent_messages, list):
        for item in reversed(raw_recent_messages):
            if not isinstance(item, dict):
                continue
            message_type = _normalize_text(item.get("message_type") or item.get("role")).lower()
            if message_type not in {"user", "human"}:
                continue
            content = _normalize_text(item.get("content"))
            if content:
                return content
    return None


def _is_knowledge_follow_up_instruction(user_input: str) -> bool:
    """识别“用知识库重新回答上一问”这类指令型续问。"""
    normalized_value = _normalize_intent_text(user_input)
    if not normalized_value:
        return False

    knowledge_tokens = ("知识库", "资料", "文档")
    answer_tokens = ("回答", "回复", "作答")
    trigger_tokens = ("检索", "查询", "搜索", "基于", "根据", "使用", "用")

    contains_knowledge = any(token in normalized_value for token in knowledge_tokens)
    contains_answer = any(token in normalized_value for token in answer_tokens)
    contains_trigger = any(token in normalized_value for token in trigger_tokens)
    if contains_knowledge and contains_answer and contains_trigger:
        return True

    return normalized_value in {"重新回答", "重新作答", "重新回复", "继续回答", "继续回复"}


def _resolve_effective_user_input(user_input: str, metadata: dict[str, Any]) -> tuple[str, dict[str, Any]]:
    """在“指令型续问”场景下恢复真正需要回答的上一轮问题。"""
    normalized_user_input = _normalize_text(user_input) or "未命名任务"
    resolved_metadata = dict(metadata)
    resolved_metadata.setdefault("raw_user_input", normalized_user_input)

    previous_user_message = _extract_previous_user_message(resolved_metadata)
    if previous_user_message and _is_knowledge_follow_up_instruction(normalized_user_input):
        resolved_metadata["is_contextual_follow_up"] = True
        resolved_metadata["follow_up_instruction"] = normalized_user_input
        resolved_metadata["resolved_user_input"] = previous_user_message
        return previous_user_message, resolved_metadata

    resolved_metadata.setdefault("resolved_user_input", normalized_user_input)
    return normalized_user_input, resolved_metadata


def _detect_conversation_intent(user_input: str) -> str:
    """识别当前输入更像任务请求还是寒暄闲聊。"""
    normalized_value = _normalize_intent_text(user_input)
    if not normalized_value:
        return "task"

    smalltalk_tokens = {
        "hi",
        "hello",
        "嗨",
        "你好",
        "您好",
        "在吗",
        "在嘛",
        "ok",
        "okay",
        "收到",
        "谢谢",
        "thanks",
        "thankyou",
        "测试",
        "test",
    }
    if normalized_value in smalltalk_tokens or _SMALLTALK_ONLY_PATTERN.fullmatch(normalized_value):
        return "smalltalk"
    return "task"


def _normalize_goal_for_display(user_input: str) -> str:
    """为寒暄类输入生成更可读的目标文案。"""
    normalized_goal = _normalize_text(user_input) or "未命名任务"
    if _detect_conversation_intent(normalized_goal) == "smalltalk":
        return "友好回应用户的寒暄或轻松表达"
    return normalized_goal


def _looks_like_information_request(user_input: str) -> bool:
    """判断输入是否更像需要知识或资料支撑的信息请求。"""
    normalized_value = _normalize_text(user_input)
    if not normalized_value:
        return False
    return bool(
        re.search(r"什么|怎么|如何|为何|为什么|多少|是否|能否|请|帮我|介绍|说明|总结|概括|分析|对比|列出|告诉我|解读|梳理|依据|根据|查询|查找|检索", normalized_value)
        or "?" in normalized_value
        or "？" in normalized_value
    )


def _latest_observation(state: TaskRuntimeState, step_type: str) -> StepObservation | None:
    """获取某个步骤类型最近一次观测。"""
    if state.current_plan is None:
        return None
    step_type_by_id = {step.step_id: step.step_type for plan in state.plan_history for step in plan.steps}
    for observation in reversed(state.step_observations):
        if step_type_by_id.get(observation.step_id) == step_type:
            return observation
    return None


def _infer_plan_risk_level(goal: TaskGoal) -> str:
    """根据目标依赖类型推断复杂任务的风险等级。"""
    if goal.metadata.get("needs_tool_call") and goal.metadata.get("needs_retrieval"):
        return "high"
    if goal.metadata.get("needs_tool_call") or goal.metadata.get("needs_retrieval"):
        return "medium"
    return "low"


def _build_plan_management_metadata(goal: TaskGoal, *, step_count: int, strategy: str) -> dict[str, object]:
    """补齐复杂任务规划所需的验收、预算和调度元信息。"""
    required_capabilities: list[str] = ["reasoning"]
    if goal.metadata.get("needs_retrieval"):
        required_capabilities.append("retrieval")
    if goal.metadata.get("needs_tool_call"):
        required_capabilities.append("tool_call")

    produces_artifacts: list[str] = []
    if goal.metadata.get("needs_retrieval"):
        produces_artifacts.append("evidence")
    if goal.metadata.get("needs_tool_call"):
        produces_artifacts.append("tool_result")
    produces_artifacts.extend(["analysis", "final_output"])
    risk_level = _infer_plan_risk_level(goal)
    timeout_seconds = 90 if risk_level == "high" else 60 if step_count >= 3 else 45
    return {
        "planning_strategy": strategy,
        "acceptance_criteria": list(goal.success_criteria),
        "required_capabilities": required_capabilities,
        "risk_level": risk_level,
        "estimated_cost": round(0.15 * step_count, 2),
        "retry_policy": {"max_attempts": 2, "backoff_seconds": 1},
        "timeout_seconds": timeout_seconds,
        "produces_artifacts": produces_artifacts,
    }


def _build_step_management_metadata(
    goal: TaskGoal,
    *,
    step_type: str,
    acceptance_criteria: list[str],
    base_metadata: dict[str, object] | None = None,
) -> dict[str, object]:
    """补齐单步计划的能力、重试、超时和产物声明。"""
    step_metadata: dict[str, object] = dict(base_metadata or {})
    capability_by_step_type = {
        "clarify": ["reasoning"],
        "retrieve": ["retrieval"],
        "tool_call": ["tool_call"],
        "analyze": ["reasoning"],
        "synthesize_answer": ["reasoning"],
        "custom": ["reasoning"],
    }
    artifact_by_step_type = {
        "retrieve": ["evidence"],
        "tool_call": ["tool_result"],
        "analyze": ["analysis"],
        "synthesize_answer": ["final_output"],
    }
    timeout_by_step_type = {
        "clarify": 20,
        "retrieve": 45,
        "tool_call": 45,
        "analyze": 30,
        "synthesize_answer": 30,
        "custom": 30,
    }
    step_metadata.setdefault("acceptance_criteria", acceptance_criteria)
    step_metadata.setdefault("required_capabilities", capability_by_step_type.get(step_type, ["reasoning"]))
    step_metadata.setdefault("retry_policy", {"max_attempts": 2, "backoff_seconds": 1})
    step_metadata.setdefault("timeout_seconds", timeout_by_step_type.get(step_type, 30))
    step_metadata.setdefault("produces_artifacts", artifact_by_step_type.get(step_type, []))
    if goal.constraints.get("output_format"):
        step_metadata.setdefault("output_format", goal.constraints.get("output_format"))
    return step_metadata


def _build_task_evaluation_report(goal: TaskGoal, state: TaskRuntimeState, evaluation: GoalEvaluation) -> TaskEvaluationReport:
    """把目标评估结果归一为标准任务验收报告。"""
    final_output = evaluation.final_output or state.final_output or ""
    satisfied_criteria: list[str] = []
    missing_criteria: list[str] = []
    for criterion in goal.success_criteria:
        normalized_criterion = _normalize_text(criterion)
        if not normalized_criterion:
            continue
        if normalized_criterion in evaluation.missing_items:
            missing_criteria.append(normalized_criterion)
        elif evaluation.goal_completed or final_output:
            satisfied_criteria.append(normalized_criterion)
        else:
            missing_criteria.append(normalized_criterion)

    risks: list[str] = []
    if goal.metadata.get("needs_retrieval"):
        retrieval_observation = _latest_observation(state, "retrieve")
        if retrieval_observation is None or not retrieval_observation.output_data.get("retrieved_items"):
            risks.append("缺少可验证资料证据")
    if goal.metadata.get("needs_tool_call"):
        tool_observation = _latest_observation(state, "tool_call")
        if tool_observation is None or not tool_observation.success:
            risks.append("缺少稳定工具结果")
    if "限制说明" in final_output:
        risks.append("最终答复包含限制说明")

    recommendations: list[str] = []
    if missing_criteria:
        recommendations.append("补齐未满足的 success criteria 后再次验收")
    if risks:
        recommendations.append("补充证据或在答复中明确当前风险边界")

    return TaskEvaluationReport(
        task_id=state.task_id,
        success=evaluation.goal_completed,
        overall_score=evaluation.completion_score,
        summary=evaluation.reasoning or ("任务已达到验收标准。" if evaluation.goal_completed else "任务仍存在验收缺口。"),
        satisfied_criteria=satisfied_criteria,
        missing_criteria=missing_criteria,
        risks=risks,
        recommendations=recommendations,
        metadata={"goal_id": goal.goal_id, "final_output_present": bool(final_output.strip())},
    )


def _infer_replan_failure_type(step_evaluation: StepEvaluation | None, goal_evaluation: GoalEvaluation | None) -> str:
    """根据步骤或目标评估推断结构化失败类型。"""
    if step_evaluation is not None:
        failure_type = _normalize_text((step_evaluation.metadata or {}).get("failure_type"))
        if failure_type:
            return failure_type
        issue_text = " ".join(step_evaluation.issues)
        if "资料" in issue_text or "证据" in issue_text:
            return "missing_evidence"
        if "工具" in issue_text or "计算" in issue_text:
            return "tool_execution_failed"
        if "分析" in issue_text:
            return "analysis_incomplete"
        if "答复" in issue_text:
            return "final_output_missing"

    if goal_evaluation is not None:
        missing_text = " ".join(goal_evaluation.missing_items)
        if "资料" in missing_text or "证据" in missing_text:
            return "missing_evidence"
        if "答复" in missing_text:
            return "final_output_missing"
    return "generic_gap"


def _normalize_retrieval_items(raw_items: Any) -> list[dict[str, Any]]:
    """将外部传入的检索上下文统一归一化。"""
    normalized_items: list[dict[str, Any]] = []
    if not isinstance(raw_items, list):
        return normalized_items

    for index, item in enumerate(raw_items, start=1):
        if isinstance(item, dict):
            normalized_items.append(
                {
                    "index": index,
                    "title": _normalize_text(item.get("title") or item.get("source") or f"资料{index}"),
                    "content": _normalize_text(item.get("content") or item.get("text") or item.get("summary")),
                }
            )
            continue
        normalized_items.append(
            {
                "index": index,
                "title": f"资料{index}",
                "content": _normalize_text(item),
            }
        )
    return [item for item in normalized_items if item["content"]]


class DefaultGoalParser:
    """默认目标解析器。

    该实现仅保留为测试 / 离线 fallback，不作为主链路组件。
    """

    async def parse_goal(self, request: TaskControllerRequest) -> TaskGoal:
        normalized_goal = request.user_input.strip() or "未命名任务"
        return TaskGoal(
            user_id=request.user_id,
            conversation_id=request.conversation_id,
            source_message_id=request.message_id,
            original_user_input=request.user_input,
            normalized_goal=normalized_goal,
            success_criteria=["给出可执行结果或明确阻塞原因"],
            metadata=dict(request.metadata),
        )


class DefaultPlanner:
    """默认规划器。

    该实现仅保留为测试 / 离线 fallback，不作为主链路组件。
    """

    async def create_plan(self, goal: TaskGoal, state: TaskRuntimeState) -> TaskPlan:
        return TaskPlan(
            goal_id=goal.goal_id,
            version=len(state.plan_history) + 1,
            reasoning="默认规划器生成单步计划，后续可替换为多步规划器。",
            steps=[
                TaskPlanStep(
                    step_type="synthesize_answer",
                    title="生成初始结果",
                    description=f"围绕目标“{goal.normalized_goal}”产出第一版结果。",
                )
            ],
        )


class DefaultStepExecutor:
    """默认步骤执行器，仅作 fallback 使用。"""

    async def execute_step(self, step: TaskPlanStep, state: TaskRuntimeState) -> StepObservation:
        return StepObservation(
            step_id=step.step_id,
            success=True,
            summary="默认执行器已完成占位执行。",
            output_data={
                "step_type": step.step_type,
                "step_title": step.title,
                "goal": state.goal.normalized_goal,
            },
        )


class DefaultStepEvaluator:
    """默认步骤评估器，仅作 fallback 使用。"""

    async def evaluate_step(
        self,
        step: TaskPlanStep,
        observation: StepObservation,
        goal: TaskGoal,
        state: TaskRuntimeState,
    ) -> StepEvaluation:
        return StepEvaluation(
            step_id=step.step_id,
            step_completed=observation.success,
            contributes_to_goal=observation.success,
            next_action="continue",
            quality_score=1.0 if observation.success else 0.0,
            reasoning="默认步骤评估器将成功执行视为可继续推进。",
        )


class DefaultGoalJudge:
    """默认目标判定器，仅作 fallback 使用。"""

    async def evaluate_goal(self, goal: TaskGoal, state: TaskRuntimeState) -> GoalEvaluation:
        current_plan = state.current_plan
        plan_steps = current_plan.steps if current_plan is not None else []
        all_completed = bool(plan_steps) and all(
            step.step_id in state.completed_step_ids for step in plan_steps
        )
        return GoalEvaluation(
            goal_id=goal.goal_id,
            goal_completed=all_completed,
            completion_score=1.0 if all_completed else 0.0,
            missing_items=[] if all_completed else ["仍缺少已完成步骤或最终结果整合"],
            reasoning="默认目标判定器按当前计划步骤是否全部完成进行判定。",
            final_output="默认闭环控制器已完成占位执行。" if all_completed else None,
        )


class DefaultReplanner:
    """默认重规划器，仅作 fallback 使用。"""

    async def decide_replan(
        self,
        goal: TaskGoal,
        state: TaskRuntimeState,
        *,
        goal_evaluation: GoalEvaluation | None = None,
        step_evaluation: StepEvaluation | None = None,
    ) -> ReplanDecision:
        return ReplanDecision(
            should_replan=False,
            reason="默认重规划器尚未接入真实策略。",
        )


class RuleBasedGoalParser:
    """基于规则的真实目标解析器。"""

    async def parse_goal(self, request: TaskControllerRequest) -> TaskGoal:
        effective_user_input, metadata = _resolve_effective_user_input(request.user_input, dict(request.metadata))
        combined_user_input = _normalize_text(f"{effective_user_input} {request.user_input}")
        normalized_goal = _normalize_goal_for_display(effective_user_input)
        constraints = self._extract_constraints(combined_user_input)
        metadata["conversation_intent"] = _detect_conversation_intent(effective_user_input)
        detected_expression = _detect_arithmetic_expression(combined_user_input)
        needs_retrieval = self._detect_retrieval_need(combined_user_input, metadata)
        needs_tool_call = self._detect_tool_need(combined_user_input, metadata, detected_expression)
        if detected_expression:
            metadata["detected_expression"] = detected_expression
        metadata["needs_retrieval"] = needs_retrieval
        metadata["needs_tool_call"] = needs_tool_call
        success_criteria = self._build_success_criteria(combined_user_input, constraints, needs_retrieval, needs_tool_call)
        return TaskGoal(
            user_id=request.user_id,
            conversation_id=request.conversation_id,
            source_message_id=request.message_id,
            original_user_input=effective_user_input,
            normalized_goal=normalized_goal,
            success_criteria=success_criteria,
            constraints=constraints,
            metadata=metadata,
        )

    @staticmethod
    def _extract_constraints(user_input: str) -> dict[str, Any]:
        """提取输出格式、粒度等约束。"""
        constraints: dict[str, Any] = {"language": "zh-CN"}
        if "表格" in user_input:
            constraints["output_format"] = "table"
        elif "列表" in user_input or "清单" in user_input:
            constraints["output_format"] = "list"
        else:
            constraints["output_format"] = "paragraph"

        if "详细" in user_input:
            constraints["response_style"] = "detailed"
        elif "简洁" in user_input or "简要" in user_input:
            constraints["response_style"] = "brief"
        else:
            constraints["response_style"] = "balanced"
        return constraints

    @staticmethod
    def _detect_retrieval_need(user_input: str, metadata: dict[str, Any]) -> bool:
        """判断当前任务是否需要资料支撑。"""
        if metadata.get("conversation_intent") == "smalltalk":
            return False
        if re.search(r"知识库|文档|资料|出处|引用|根据.*资料|根据.*文档", user_input):
            return True
        if metadata.get("enable_knowledge_base") or metadata.get("knowledge_base_id"):
            return _looks_like_information_request(user_input)
        return False

    @staticmethod
    def _detect_tool_need(user_input: str, metadata: dict[str, Any], expression: str | None) -> bool:
        """判断当前任务是否需要工具步骤。"""
        if metadata.get("force_tool_call"):
            return True
        return expression is not None and any(token in user_input for token in ["计算", "+", "-", "*", "/", "%"])

    @staticmethod
    def _build_success_criteria(
        user_input: str,
        constraints: dict[str, Any],
        needs_retrieval: bool,
        needs_tool_call: bool,
    ) -> list[str]:
        """根据任务特征构建成功标准。"""
        criteria = ["给出与用户目标直接对应的结果"]
        if needs_retrieval:
            criteria.append("说明资料依据或明确资料缺失")
        if needs_tool_call:
            criteria.append("给出可验证的工具或计算结果")
        if constraints.get("output_format") == "table":
            criteria.append("按表格结构组织结果")
        elif constraints.get("output_format") == "list":
            criteria.append("按条目列表组织结果")
        if "方案" in user_input or "计划" in user_input or "步骤" in user_input:
            criteria.append("输出清晰的步骤化建议")
        return criteria


class HeuristicPlanner:
    """基于任务特征生成多步计划的真实规划器。"""

    async def create_plan(self, goal: TaskGoal, state: TaskRuntimeState) -> TaskPlan:
        previous_version = state.plan_history[-1].version if state.plan_history else 0

        # 寒暄类输入直接走自然回复，避免无意义的检索和分析步骤。
        if (
            goal.metadata.get("conversation_intent") == "smalltalk"
            and not goal.metadata.get("needs_retrieval")
            and not goal.metadata.get("needs_tool_call")
        ):
            synthesize_metadata = _build_step_management_metadata(
                goal,
                step_type="synthesize_answer",
                acceptance_criteria=["自然回应用户当前输入"],
                base_metadata={"response_style": "natural"},
            )
            synthesize_step = TaskPlanStep(
                step_type="synthesize_answer",
                title="自然回应用户",
                description="直接以自然、友好的方式回应用户当前表达。",
                metadata=synthesize_metadata,
            )
            plan_metadata = _build_plan_management_metadata(goal, step_count=1, strategy="heuristic_smalltalk_direct_reply")
            plan_metadata["acceptance_criteria"] = ["自然回应用户当前输入"]
            return TaskPlan(
                goal_id=goal.goal_id,
                version=previous_version + 1,
                reasoning="目标属于轻松交流或寒暄，直接生成自然回复。",
                steps=[synthesize_step],
                metadata={
                    **plan_metadata,
                    "needs_retrieval": False,
                    "needs_tool_call": False,
                    "conversation_intent": "smalltalk",
                },
            )

        steps: list[TaskPlanStep] = []
        dependency_ids: list[str] = []

        if goal.metadata.get("needs_retrieval"):
            retrieve_metadata = _build_step_management_metadata(
                goal,
                step_type="retrieve",
                acceptance_criteria=["整理出与目标直接相关的资料证据"],
                base_metadata={"retrieval_required": True},
            )
            retrieve_step = TaskPlanStep(
                step_type="retrieve",
                title="整理支撑资料",
                description="从已提供资料或知识上下文中提取与目标直接相关的信息。",
                metadata=retrieve_metadata,
            )
            steps.append(retrieve_step)
            dependency_ids.append(retrieve_step.step_id)

        if goal.metadata.get("needs_tool_call"):
            tool_metadata = _build_step_management_metadata(
                goal,
                step_type="tool_call",
                acceptance_criteria=["产出可验证的工具或计算结果"],
                base_metadata={"expression": goal.metadata.get("detected_expression")},
            )
            tool_step = TaskPlanStep(
                step_type="tool_call",
                title="执行工具或计算",
                description="对可结构化处理的部分先进行工具化求解。",
                metadata=tool_metadata,
            )
            steps.append(tool_step)
            dependency_ids.append(tool_step.step_id)

        analyze_metadata = _build_step_management_metadata(
            goal,
            step_type="analyze",
            acceptance_criteria=["形成可用于最终答复的中间结论"],
            base_metadata={"output_format": goal.constraints.get("output_format")},
        )
        analyze_step = TaskPlanStep(
            step_type="analyze",
            title="汇总并分析现有信息",
            description="整合前置步骤产出的资料、结果与限制，形成可回答的中间结论。",
            depends_on=list(dependency_ids),
            metadata=analyze_metadata,
        )
        steps.append(analyze_step)

        synthesize_metadata = _build_step_management_metadata(
            goal,
            step_type="synthesize_answer",
            acceptance_criteria=list(goal.success_criteria) or ["输出满足目标的最终答复"],
            base_metadata={"response_style": goal.constraints.get("response_style", "balanced")},
        )
        synthesize_step = TaskPlanStep(
            step_type="synthesize_answer",
            title="生成最终答复",
            description="基于分析结论生成最终答复，并在必要时说明限制。",
            depends_on=[analyze_step.step_id],
            metadata=synthesize_metadata,
        )
        steps.append(synthesize_step)

        reasoning_parts = []
        if goal.metadata.get("needs_retrieval"):
            reasoning_parts.append("目标包含资料或知识依据要求，因此先整理支撑信息")
        if goal.metadata.get("needs_tool_call"):
            reasoning_parts.append("目标包含可计算内容，因此加入工具或计算步骤")
        reasoning_parts.append("随后统一分析并生成最终答复")

        plan_metadata = _build_plan_management_metadata(goal, step_count=len(steps), strategy="heuristic_multi_step")
        return TaskPlan(
            goal_id=goal.goal_id,
            version=previous_version + 1,
            reasoning="；".join(reasoning_parts),
            steps=steps,
            metadata={
                **plan_metadata,
                "needs_retrieval": bool(goal.metadata.get("needs_retrieval")),
                "needs_tool_call": bool(goal.metadata.get("needs_tool_call")),
            },
        )


class RuntimeStepExecutor:
    """真实步骤执行器。"""

    async def execute_step(self, step: TaskPlanStep, state: TaskRuntimeState) -> StepObservation:
        if step.step_type == "retrieve":
            return self._execute_retrieve_step(step, state)
        if step.step_type == "tool_call":
            return self._execute_tool_step(step, state)
        if step.step_type == "analyze":
            return self._execute_analyze_step(step, state)
        if step.step_type == "synthesize_answer":
            return self._execute_synthesize_step(step, state)
        if step.step_type == "clarify":
            return self._execute_clarify_step(step, state)
        return StepObservation(
            step_id=step.step_id,
            success=False,
            summary=f"暂不支持步骤类型：{step.step_type}",
            error_message=f"unsupported step type: {step.step_type}",
            output_data={"step_type": step.step_type},
        )

    def _execute_retrieve_step(self, step: TaskPlanStep, state: TaskRuntimeState) -> StepObservation:
        """执行资料整理步骤。"""
        metadata = state.goal.metadata or {}
        raw_items = metadata.get("knowledge_items") or metadata.get("retrieval_results")
        retrieval_items = _normalize_retrieval_items(raw_items)
        query_terms = [part for part in re.split(r"[，。！？、\s]+", state.goal.normalized_goal) if part][:5]

        if retrieval_items:
            return StepObservation(
                step_id=step.step_id,
                success=True,
                summary=f"已整理出 {len(retrieval_items)} 条可用资料。",
                output_data={
                    "retrieved_items": retrieval_items,
                    "retrieved_count": len(retrieval_items),
                    "query_terms": query_terms,
                },
                metadata={"source": "request_metadata"},
            )

        return StepObservation(
            step_id=step.step_id,
            success=False,
            summary="当前任务需要资料支撑，但本次请求未提供可用资料。",
            error_message="missing retrieval context",
            output_data={
                "retrieved_items": [],
                "retrieved_count": 0,
                "query_terms": query_terms,
            },
            metadata={"retrieval_required": True},
        )

    def _execute_tool_step(self, step: TaskPlanStep, state: TaskRuntimeState) -> StepObservation:
        """执行工具 / 计算步骤。"""
        expression = step.metadata.get("expression") or state.goal.metadata.get("detected_expression")
        if not expression:
            expression = _detect_arithmetic_expression(state.goal.original_user_input)

        if not expression:
            return StepObservation(
                step_id=step.step_id,
                success=False,
                summary="未识别到可执行的计算表达式。",
                error_message="no executable expression detected",
                output_data={"tool_name": "calculator"},
            )

        try:
            result = _safe_evaluate_expression(expression)
        except Exception as error:
            return StepObservation(
                step_id=step.step_id,
                success=False,
                summary=f"表达式 {expression} 计算失败。",
                error_message=str(error),
                output_data={"tool_name": "calculator", "expression": expression},
            )

        return StepObservation(
            step_id=step.step_id,
            success=True,
            summary=f"已完成计算：{expression} = {result}",
            output_data={
                "tool_name": "calculator",
                "expression": expression,
                "result": result,
            },
        )

    def _execute_analyze_step(self, step: TaskPlanStep, state: TaskRuntimeState) -> StepObservation:
        """综合前置步骤结果并输出中间分析结论。"""
        retrieval_observation = _latest_observation(state, "retrieve")
        tool_observation = _latest_observation(state, "tool_call")
        analysis_lines = [f"目标：{state.goal.normalized_goal}"]
        gaps: list[str] = []

        if retrieval_observation is not None:
            retrieved_items = retrieval_observation.output_data.get("retrieved_items") or []
            if retrieved_items:
                analysis_lines.append(f"资料支撑：已获得 {len(retrieved_items)} 条资料，可用于回答。")
            else:
                gaps.append("缺少资料支撑")
                analysis_lines.append("资料支撑：当前没有可用资料，需要在最终答复中说明限制。")

        if tool_observation is not None:
            if tool_observation.success:
                analysis_lines.append(
                    f"工具结果：{tool_observation.output_data.get('expression')} = {tool_observation.output_data.get('result')}。"
                )
            else:
                gaps.append("工具步骤未成功")
                analysis_lines.append("工具结果：工具步骤未成功，需在最终答复中说明。")

        if retrieval_observation is None and tool_observation is None:
            analysis_lines.append("当前任务无需额外外部步骤，可直接基于目标组织回答。")

        if "方案" in state.goal.normalized_goal or "计划" in state.goal.normalized_goal or "步骤" in state.goal.normalized_goal:
            analysis_lines.append("输出应强调结构化步骤和行动建议。")

        analysis_summary = "\n".join(analysis_lines)
        return StepObservation(
            step_id=step.step_id,
            success=True,
            summary="已完成阶段性分析。",
            output_data={
                "analysis_summary": analysis_summary,
                "gaps": gaps,
            },
        )

    def _execute_synthesize_step(self, step: TaskPlanStep, state: TaskRuntimeState) -> StepObservation:
        """生成最终答复。"""
        analysis_observation = _latest_observation(state, "analyze")
        retrieval_observation = _latest_observation(state, "retrieve")
        tool_observation = _latest_observation(state, "tool_call")
        constraints = state.goal.constraints or {}
        response_style = step.metadata.get("response_style") or constraints.get("response_style", "balanced")
        output_format = constraints.get("output_format", "paragraph")

        body_lines: list[str] = []
        limitations: list[str] = []
        if analysis_observation is not None:
            body_lines.append(analysis_observation.output_data.get("analysis_summary") or analysis_observation.summary)

        if retrieval_observation is not None:
            retrieved_items = retrieval_observation.output_data.get("retrieved_items") or []
            if retrieved_items:
                body_lines.append("已结合已提供资料进行归纳整理。")
            else:
                limitations.append("当前未提供可用资料或知识库证据，因此答案仅基于请求本身与已知上下文。")

        if tool_observation is not None and tool_observation.success:
            body_lines.append(
                f"可验证结果：{tool_observation.output_data.get('expression')} = {tool_observation.output_data.get('result')}。"
            )
        elif tool_observation is not None and not tool_observation.success:
            limitations.append("工具步骤未成功执行，因此未提供自动计算结果。")

        opening = f"针对“{state.goal.normalized_goal}”，当前执行结论如下："
        if output_format == "list":
            formatted_body = "\n".join(f"- {line}" for line in body_lines if line)
        elif output_format == "table":
            formatted_body = "| 项目 | 内容 |\n| --- | --- |\n" + "\n".join(
                f"| 结论{index} | {line.replace('|', '｜')} |"
                for index, line in enumerate([item for item in body_lines if item], start=1)
            )
        else:
            formatted_body = "\n\n".join(line for line in body_lines if line)

        if response_style == "brief":
            formatted_body = formatted_body.split("\n")[0] if formatted_body else ""

        final_parts = [opening]
        if formatted_body:
            final_parts.append(formatted_body)
        if limitations:
            final_parts.append("限制说明：" + "；".join(limitations))
        if not formatted_body and not limitations:
            final_parts.append("已完成任务，但当前没有额外可补充的信息。")

        final_output = "\n\n".join(part for part in final_parts if part)
        return StepObservation(
            step_id=step.step_id,
            success=bool(final_output.strip()),
            summary="已生成最终答复。",
            output_data={
                "final_output": final_output,
                "limitations": limitations,
            },
        )

    def _execute_clarify_step(self, step: TaskPlanStep, state: TaskRuntimeState) -> StepObservation:
        """输出需要澄清的点。"""
        summary = "当前任务信息已足够，无需额外澄清。"
        if len(state.goal.normalized_goal) <= 6:
            summary = "当前任务描述较短，后续回答中会显式说明假设前提。"
        return StepObservation(
            step_id=step.step_id,
            success=True,
            summary=summary,
            output_data={"clarification_summary": summary},
        )


class RuleBasedStepEvaluator:
    """基于观测结果生成真实评估结论。"""

    async def evaluate_step(
        self,
        step: TaskPlanStep,
        observation: StepObservation,
        goal: TaskGoal,
        state: TaskRuntimeState,
    ) -> StepEvaluation:
        if step.step_type == "retrieve":
            retrieved_items = observation.output_data.get("retrieved_items") or []
            if observation.success and retrieved_items:
                return StepEvaluation(
                    step_id=step.step_id,
                    step_completed=True,
                    contributes_to_goal=True,
                    next_action="continue",
                    quality_score=0.92,
                    reasoning="已取得足够的资料支撑，可以继续后续分析。",
                    metadata={"failure_type": ""},
                )
            return StepEvaluation(
                step_id=step.step_id,
                step_completed=False,
                contributes_to_goal=False,
                next_action="replan",
                quality_score=0.25,
                issues=["缺少可用资料支撑"],
                reasoning="当前任务要求资料支撑，但本轮没有拿到有效资料，建议重规划到降级方案。",
                metadata={"failure_type": "missing_evidence"},
            )

        if step.step_type == "tool_call":
            if observation.success:
                return StepEvaluation(
                    step_id=step.step_id,
                    step_completed=True,
                    contributes_to_goal=True,
                    next_action="continue",
                    quality_score=0.95,
                    reasoning="工具步骤已得到可验证结果。",
                    metadata={"failure_type": ""},
                )
            return StepEvaluation(
                step_id=step.step_id,
                step_completed=False,
                contributes_to_goal=False,
                next_action="replan",
                quality_score=0.2,
                issues=["工具步骤未成功完成"],
                reasoning="当前工具步骤失败，建议改用无工具降级方案并明确限制。",
                metadata={"failure_type": "tool_execution_failed"},
            )

        if step.step_type == "analyze":
            analysis_summary = observation.output_data.get("analysis_summary") or ""
            if analysis_summary.strip():
                return StepEvaluation(
                    step_id=step.step_id,
                    step_completed=True,
                    contributes_to_goal=True,
                    next_action="continue",
                    quality_score=0.82,
                    reasoning="已经形成可用于回答的分析结论。",
                    metadata={"failure_type": ""},
                )
            return StepEvaluation(
                step_id=step.step_id,
                step_completed=False,
                contributes_to_goal=False,
                next_action="retry",
                quality_score=0.1,
                issues=["分析结论为空"],
                reasoning="分析步骤没有产出可用内容，应重试。",
                metadata={"failure_type": "analysis_incomplete"},
            )

        if step.step_type == "synthesize_answer":
            final_output = observation.output_data.get("final_output") or ""
            if final_output.strip():
                return StepEvaluation(
                    step_id=step.step_id,
                    step_completed=True,
                    contributes_to_goal=True,
                    next_action="continue",
                    quality_score=0.96,
                    reasoning="已生成最终答复，可以进入整体目标判定。",
                    metadata={"failure_type": ""},
                )
            return StepEvaluation(
                step_id=step.step_id,
                step_completed=False,
                contributes_to_goal=False,
                next_action="retry",
                quality_score=0.1,
                issues=["最终答复为空"],
                reasoning="最终答复为空，应重新生成。",
                metadata={"failure_type": "final_output_missing"},
            )

        return StepEvaluation(
            step_id=step.step_id,
            step_completed=observation.success,
            contributes_to_goal=observation.success,
            next_action="continue",
            quality_score=1.0 if observation.success else 0.0,
            reasoning="默认按观测是否成功判断步骤结果。",
            metadata={"failure_type": "" if observation.success else "generic_gap"},
        )


class RuleBasedGoalJudge:
    """基于最终答复和缺口信息进行目标判定。"""

    async def evaluate_goal(self, goal: TaskGoal, state: TaskRuntimeState) -> GoalEvaluation:
        synthesize_observation = _latest_observation(state, "synthesize_answer")
        if synthesize_observation is not None:
            final_output = synthesize_observation.output_data.get("final_output") or ""
            if final_output.strip():
                completion_score = 0.88 if "限制说明" in final_output else 1.0
                evaluation = GoalEvaluation(
                    goal_id=goal.goal_id,
                    goal_completed=True,
                    completion_score=completion_score,
                    reasoning="已经生成最终答复，目标可视为完成。",
                    final_output=final_output,
                    metadata={"final_step_id": synthesize_observation.step_id},
                )
                evaluation.metadata["evaluation_report"] = _build_task_evaluation_report(goal, state, evaluation).model_dump()
                return evaluation

        missing_items = ["尚未产出最终答复"]
        retrieval_observation = _latest_observation(state, "retrieve")
        if goal.metadata.get("needs_retrieval") and (
            retrieval_observation is None or not retrieval_observation.output_data.get("retrieved_items")
        ):
            missing_items.append("缺少资料支撑")

        evaluation = GoalEvaluation(
            goal_id=goal.goal_id,
            goal_completed=False,
            completion_score=0.4 if state.completed_step_ids else 0.1,
            missing_items=missing_items,
            reasoning="当前尚未得到满足目标要求的最终输出。",
            metadata={"failure_type": _infer_replan_failure_type(None, GoalEvaluation(goal_id=goal.goal_id, goal_completed=False, missing_items=missing_items))},
        )
        evaluation.metadata["evaluation_report"] = _build_task_evaluation_report(goal, state, evaluation).model_dump()
        return evaluation


class RuleBasedReplanner:
    """根据步骤失败原因生成降级计划。"""

    async def decide_replan(
        self,
        goal: TaskGoal,
        state: TaskRuntimeState,
        *,
        goal_evaluation: GoalEvaluation | None = None,
        step_evaluation: StepEvaluation | None = None,
    ) -> ReplanDecision:
        failure_type = _infer_replan_failure_type(step_evaluation, goal_evaluation)
        if step_evaluation is not None and step_evaluation.next_action == "replan":
            reason = step_evaluation.issues[0] if step_evaluation.issues else step_evaluation.reasoning
            return ReplanDecision(
                should_replan=True,
                reason=reason,
                new_plan=self._build_fallback_plan(goal, state, reason, failure_type=failure_type),
                metadata={"trigger": "step_evaluation", "failure_type": failure_type},
            )

        if goal_evaluation is not None and not goal_evaluation.goal_completed:
            reason = goal_evaluation.missing_items[0] if goal_evaluation.missing_items else goal_evaluation.reasoning
            if state.current_plan and any(step.step_type == "synthesize_answer" for step in state.current_plan.steps):
                return ReplanDecision(
                    should_replan=False,
                    reason=f"{reason}，且当前计划已包含最终答复步骤，控制器终止。",
                    metadata={"trigger": "goal_evaluation", "failure_type": failure_type},
                )
            return ReplanDecision(
                should_replan=True,
                reason=reason,
                new_plan=self._build_fallback_plan(goal, state, reason, failure_type=failure_type),
                metadata={"trigger": "goal_evaluation", "failure_type": failure_type},
            )

        return ReplanDecision(
            should_replan=False,
            reason="当前无需重规划。",
        )

    @staticmethod
    def _build_fallback_plan(goal: TaskGoal, state: TaskRuntimeState, reason: str, *, failure_type: str) -> TaskPlan:
        """构建降级计划，保证仍能给出带限制说明的结果。"""
        previous_version = state.plan_history[-1].version if state.plan_history else 0
        if failure_type == "final_output_missing":
            synthesize_step = TaskPlanStep(
                step_type="synthesize_answer",
                title="重新生成最终答复",
                description="保留现有中间结果，直接重写最终答复并补齐缺口说明。",
                metadata=_build_step_management_metadata(
                    goal,
                    step_type="synthesize_answer",
                    acceptance_criteria=list(goal.success_criteria) or ["输出满足目标的最终答复"],
                    base_metadata={"fallback_mode": True, "replan_reason": reason, "failure_type": failure_type},
                ),
            )
            fallback_steps = [synthesize_step]
            replan_strategy = "retry_final_delivery"
        else:
            analyze_step = TaskPlanStep(
                step_type="analyze",
                title="整理当前已知信息",
                description="基于现有观测总结可回答内容与缺口。",
                metadata=_build_step_management_metadata(
                    goal,
                    step_type="analyze",
                    acceptance_criteria=["形成可用于最终答复的中间结论"],
                    base_metadata={"fallback_mode": True, "replan_reason": reason, "failure_type": failure_type},
                ),
            )
            synthesize_step = TaskPlanStep(
                step_type="synthesize_answer",
                title="输出带限制说明的答复",
                description="在缺少资料或工具结果时，明确限制并给出当前最佳结论。",
                depends_on=[analyze_step.step_id],
                metadata=_build_step_management_metadata(
                    goal,
                    step_type="synthesize_answer",
                    acceptance_criteria=list(goal.success_criteria) or ["输出满足目标的最终答复"],
                    base_metadata={"fallback_mode": True, "failure_type": failure_type},
                ),
            )
            fallback_steps = [analyze_step, synthesize_step]
            replan_strategy = {
                "missing_evidence": "evidence_free_fallback",
                "tool_execution_failed": "tool_free_fallback",
                "analysis_incomplete": "analysis_rebuild",
            }.get(failure_type, "generic_fallback")

        plan_metadata = _build_plan_management_metadata(goal, step_count=len(fallback_steps), strategy="rule_based_replan")
        return TaskPlan(
            goal_id=goal.goal_id,
            version=previous_version + 1,
            reasoning=f"由于“{reason}”，切换为无外部依赖的降级计划。",
            steps=fallback_steps,
            metadata={
                **plan_metadata,
                "fallback_mode": True,
                "replan_reason": reason,
                "failure_type": failure_type,
                "replan_strategy": replan_strategy,
            },
        )


def build_default_task_controller(
    *,
    max_iterations: int = 8,
    use_fallback_components: bool = False,
    use_llm_components: bool | None = None,
) -> TaskController:
    """构建任务运行时控制器。"""
    if use_fallback_components:
        return TaskController(
            goal_parser=DefaultGoalParser(),
            planner=DefaultPlanner(),
            step_executor=DefaultStepExecutor(),
            step_evaluator=DefaultStepEvaluator(),
            goal_judge=DefaultGoalJudge(),
            replanner=DefaultReplanner(),
            max_iterations=max_iterations,
        )

    # 仅在显式启用或配置开启时尝试挂载 LLM 组件；构建失败时保持规则链路不变。
    if use_llm_components is not False:
        try:
            from backend.application.task_runtime.llm_components import build_task_runtime_llm_bundle

            llm_bundle = build_task_runtime_llm_bundle(force_enable=bool(use_llm_components))
            if llm_bundle is not None:
                return TaskController(
                    goal_parser=llm_bundle.goal_parser,
                    planner=llm_bundle.planner,
                    step_executor=RuntimeStepExecutor(),
                    step_evaluator=llm_bundle.step_evaluator,
                    goal_judge=llm_bundle.goal_judge,
                    replanner=llm_bundle.replanner,
                    max_iterations=max_iterations,
                )
        except Exception as error:
            logger.warning("Failed to enable task runtime LLM components, fallback to rule-based chain: %s", error)

    return TaskController(
        goal_parser=RuleBasedGoalParser(),
        planner=HeuristicPlanner(),
        step_executor=RuntimeStepExecutor(),
        step_evaluator=RuleBasedStepEvaluator(),
        goal_judge=RuleBasedGoalJudge(),
        replanner=RuleBasedReplanner(),
        max_iterations=max_iterations,
    )
