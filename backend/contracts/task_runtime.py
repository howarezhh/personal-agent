from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict, List, Literal, Optional
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field


TaskStepType = Literal[
    "clarify",
    "retrieve",
    "tool_call",
    "analyze",
    "synthesize_answer",
    "custom",
]

StepNextAction = Literal["continue", "retry", "replan"]

TerminationStatus = Literal["completed", "blocked", "max_iterations", "failed"]

TaskExecutionStatus = Literal[
    "pending",
    "running",
    "paused",
    "succeeded",
    "failed",
    "cancelled",
    "timed_out",
]

TaskLifecycleAction = Literal["pause", "resume", "cancel", "retry"]

TaskArtifactType = Literal[
    "text",
    "plan",
    "evidence",
    "report",
    "tool_result",
    "retrieval_result",
    "custom",
]

TaskRuntimeStage = Literal[
    "goal_parsing",
    "planning",
    "step_started",
    "step_observation",
    "step_evaluation",
    "goal_evaluation",
    "replan",
    "termination",
]


def _generate_runtime_id(prefix: str) -> str:
    """生成带前缀的稳定运行时标识。"""
    return f"{prefix}_{uuid4().hex}"


def _utc_now_iso() -> str:
    """统一返回 UTC ISO 8601 时间文本。"""
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


class TaskControllerRequest(BaseModel):
    """任务控制器的统一入口请求。"""

    model_config = ConfigDict(extra="forbid")

    user_id: str
    conversation_id: str
    user_input: str
    message_id: Optional[str] = None
    request_id: Optional[str] = None
    execution_id: Optional[str] = None
    metadata: Dict[str, Any] = Field(default_factory=dict)


class TaskGoal(BaseModel):
    """任务目标模型，负责表达当前轮次真正要完成的目标。"""

    model_config = ConfigDict(extra="forbid")

    goal_id: str = Field(default_factory=lambda: _generate_runtime_id("goal"))
    user_id: str
    conversation_id: str
    source_message_id: Optional[str] = None
    original_user_input: str
    normalized_goal: str
    success_criteria: List[str] = Field(default_factory=list)
    constraints: Dict[str, Any] = Field(default_factory=dict)
    metadata: Dict[str, Any] = Field(default_factory=dict)


class TaskPlanStep(BaseModel):
    """任务计划中的单个步骤定义。"""

    model_config = ConfigDict(extra="forbid")

    step_id: str = Field(default_factory=lambda: _generate_runtime_id("step"))
    step_type: TaskStepType
    title: str
    description: str = ""
    depends_on: List[str] = Field(default_factory=list)
    metadata: Dict[str, Any] = Field(default_factory=dict)


class TaskPlan(BaseModel):
    """任务计划模型。"""

    model_config = ConfigDict(extra="forbid")

    plan_id: str = Field(default_factory=lambda: _generate_runtime_id("plan"))
    goal_id: str
    version: int = 1
    reasoning: str = ""
    steps: List[TaskPlanStep] = Field(default_factory=list)
    metadata: Dict[str, Any] = Field(default_factory=dict)


class StepObservation(BaseModel):
    """步骤执行后的客观观测结果。"""

    model_config = ConfigDict(extra="forbid")

    observation_id: str = Field(default_factory=lambda: _generate_runtime_id("obs"))
    step_id: str
    success: bool
    summary: str = ""
    output_data: Dict[str, Any] = Field(default_factory=dict)
    error_message: Optional[str] = None
    metadata: Dict[str, Any] = Field(default_factory=dict)


class StepEvaluation(BaseModel):
    """步骤评估结果，用于驱动继续、重试或重规划。"""

    model_config = ConfigDict(extra="forbid")

    evaluation_id: str = Field(default_factory=lambda: _generate_runtime_id("step_eval"))
    step_id: str
    step_completed: bool
    contributes_to_goal: bool
    next_action: StepNextAction = "continue"
    quality_score: float = 1.0
    issues: List[str] = Field(default_factory=list)
    reasoning: str = ""
    metadata: Dict[str, Any] = Field(default_factory=dict)


class GoalEvaluation(BaseModel):
    """整体目标评估结果。"""

    model_config = ConfigDict(extra="forbid")

    evaluation_id: str = Field(default_factory=lambda: _generate_runtime_id("goal_eval"))
    goal_id: str
    goal_completed: bool
    completion_score: float = 0.0
    missing_items: List[str] = Field(default_factory=list)
    reasoning: str = ""
    final_output: Optional[str] = None
    metadata: Dict[str, Any] = Field(default_factory=dict)


class ReplanDecision(BaseModel):
    """重规划决策结果。"""

    model_config = ConfigDict(extra="forbid")

    decision_id: str = Field(default_factory=lambda: _generate_runtime_id("replan"))
    should_replan: bool
    reason: str = ""
    new_plan: Optional[TaskPlan] = None
    metadata: Dict[str, Any] = Field(default_factory=dict)


class TerminationDecision(BaseModel):
    """控制器终止时的统一结果。"""

    model_config = ConfigDict(extra="forbid")

    status: TerminationStatus
    reason: str
    final_output: Optional[str] = None
    metadata: Dict[str, Any] = Field(default_factory=dict)


class TaskCheckpoint(BaseModel):
    """任务执行检查点，用于后续恢复、回放与审计。"""

    model_config = ConfigDict(extra="forbid")

    checkpoint_id: str = Field(default_factory=lambda: _generate_runtime_id("checkpoint"))
    task_id: Optional[str] = None
    execution_id: Optional[str] = None
    status: TaskExecutionStatus = "pending"
    iteration_count: int = 0
    completed_step_ids: List[str] = Field(default_factory=list)
    latest_plan_id: Optional[str] = None
    latest_step_id: Optional[str] = None
    checkpoint_reason: str = ""
    created_at: str = Field(default_factory=_utc_now_iso)
    metadata: Dict[str, Any] = Field(default_factory=dict)


class TaskArtifact(BaseModel):
    """任务执行过程中沉淀的标准产物。"""

    model_config = ConfigDict(extra="forbid")

    artifact_id: str = Field(default_factory=lambda: _generate_runtime_id("artifact"))
    artifact_type: TaskArtifactType = "custom"
    title: str = ""
    content: Any = None
    source_plan_id: Optional[str] = None
    source_step_id: Optional[str] = None
    created_at: str = Field(default_factory=_utc_now_iso)
    metadata: Dict[str, Any] = Field(default_factory=dict)


class TaskEvaluationReport(BaseModel):
    """任务最终验收报告。"""

    model_config = ConfigDict(extra="forbid")

    report_id: str = Field(default_factory=lambda: _generate_runtime_id("task_report"))
    task_id: Optional[str] = None
    success: bool = False
    overall_score: float = 0.0
    summary: str = ""
    satisfied_criteria: List[str] = Field(default_factory=list)
    missing_criteria: List[str] = Field(default_factory=list)
    risks: List[str] = Field(default_factory=list)
    recommendations: List[str] = Field(default_factory=list)
    created_at: str = Field(default_factory=_utc_now_iso)
    metadata: Dict[str, Any] = Field(default_factory=dict)


class TaskExecutionRecord(BaseModel):
    """任务执行摘要契约，供状态接口与前端任务中心统一消费。"""

    model_config = ConfigDict(extra="forbid")

    task_id: str = Field(default_factory=lambda: _generate_runtime_id("task"))
    request_id: str
    execution_id: str
    user_id: str
    conversation_id: str
    message_id: Optional[str] = None
    status: TaskExecutionStatus = "pending"
    current_plan_id: Optional[str] = None
    current_step_id: Optional[str] = None
    checkpoint_id: Optional[str] = None
    created_at: str = Field(default_factory=_utc_now_iso)
    updated_at: str = Field(default_factory=_utc_now_iso)
    metadata: Dict[str, Any] = Field(default_factory=dict)


class TaskRuntimeState(BaseModel):
    """闭环控制器的完整运行时状态。"""

    model_config = ConfigDict(extra="forbid")

    goal: TaskGoal
    current_plan: Optional[TaskPlan] = None
    plan_history: List[TaskPlan] = Field(default_factory=list)
    completed_step_ids: List[str] = Field(default_factory=list)
    step_observations: List[StepObservation] = Field(default_factory=list)
    step_evaluations: List[StepEvaluation] = Field(default_factory=list)
    goal_evaluations: List[GoalEvaluation] = Field(default_factory=list)
    task_id: Optional[str] = None
    status: TaskExecutionStatus = "pending"
    checkpoint_id: Optional[str] = None
    current_step_id: Optional[str] = None
    artifacts: List[TaskArtifact] = Field(default_factory=list)
    evaluation_report: Optional[TaskEvaluationReport] = None
    iteration_count: int = 0
    max_iterations: int = 8
    terminated: bool = False
    termination: Optional[TerminationDecision] = None
    final_output: Optional[str] = None
    created_at: str = Field(default_factory=_utc_now_iso)
    updated_at: str = Field(default_factory=_utc_now_iso)
    metadata: Dict[str, Any] = Field(default_factory=dict)


class TaskRuntimePreparation(BaseModel):
    """任务运行时准备结果。"""

    model_config = ConfigDict(extra="forbid")

    task_id: Optional[str] = None
    request_id: str
    execution_id: str
    status: TaskExecutionStatus = "pending"
    checkpoint_id: Optional[str] = None
    goal: TaskGoal
    plan: TaskPlan
    evaluation_report: Optional[TaskEvaluationReport] = None
    created_at: str = Field(default_factory=_utc_now_iso)
    updated_at: str = Field(default_factory=_utc_now_iso)
    metadata: Dict[str, Any] = Field(default_factory=dict)


class TaskRuntimeControllerEvent(BaseModel):
    """控制器内部流式事件，用于统一翻译为 SSE 事件。"""

    model_config = ConfigDict(extra="forbid")

    event_id: str = Field(default_factory=lambda: _generate_runtime_id("evt"))
    stage: TaskRuntimeStage
    message: str = ""
    payload: Dict[str, Any] = Field(default_factory=dict)
    timestamp: str = Field(default_factory=_utc_now_iso)
    request_id: Optional[str] = None
    conversation_id: Optional[str] = None
    message_id: Optional[str] = None
    execution_id: Optional[str] = None
    plan_id: Optional[str] = None
    step_id: Optional[str] = None
