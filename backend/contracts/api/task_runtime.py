from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from backend.contracts.task_runtime import (
    TaskArtifact,
    TaskCheckpoint,
    TaskEvaluationReport,
    TaskExecutionRecord,
    TaskExecutionStatus,
    TaskGoal,
    TaskLifecycleAction,
    TaskPlan,
    TaskPlanStep,
    TaskRuntimePreparation,
    TerminationDecision,
)


class TaskRuntimeSubmitRequest(BaseModel):
    """任务运行时提交请求 DTO。"""

    model_config = ConfigDict(extra="forbid")

    conversation_id: str
    user_input: str
    message_id: str | None = None
    request_id: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class TaskRuntimeActionRequest(BaseModel):
    """任务生命周期控制请求 DTO。"""

    model_config = ConfigDict(extra="forbid")

    reason: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class TaskRuntimeGoalResponse(BaseModel):
    """任务目标响应 DTO。"""

    model_config = ConfigDict(extra="forbid")

    goal_id: str
    conversation_id: str
    source_message_id: str | None = None
    original_user_input: str
    normalized_goal: str
    success_criteria: list[str] = Field(default_factory=list)
    constraints: dict[str, Any] = Field(default_factory=dict)
    metadata: dict[str, Any] = Field(default_factory=dict)

    @classmethod
    def from_goal(cls, goal: TaskGoal) -> "TaskRuntimeGoalResponse":
        return cls(
            goal_id=goal.goal_id,
            conversation_id=goal.conversation_id,
            source_message_id=goal.source_message_id,
            original_user_input=goal.original_user_input,
            normalized_goal=goal.normalized_goal,
            success_criteria=list(goal.success_criteria),
            constraints=dict(goal.constraints),
            metadata=dict(goal.metadata),
        )


class TaskRuntimePlanStepResponse(BaseModel):
    """任务计划步骤响应 DTO。"""

    model_config = ConfigDict(extra="forbid")

    step_id: str
    step_type: str
    title: str
    description: str = ""
    depends_on: list[str] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)

    @classmethod
    def from_step(cls, step: TaskPlanStep) -> "TaskRuntimePlanStepResponse":
        return cls(
            step_id=step.step_id,
            step_type=step.step_type,
            title=step.title,
            description=step.description,
            depends_on=list(step.depends_on),
            metadata=dict(step.metadata),
        )


class TaskRuntimePlanResponse(BaseModel):
    """任务计划响应 DTO。"""

    model_config = ConfigDict(extra="forbid")

    plan_id: str
    goal_id: str
    version: int
    reasoning: str = ""
    steps: list[TaskRuntimePlanStepResponse] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)

    @classmethod
    def from_plan(cls, plan: TaskPlan) -> "TaskRuntimePlanResponse":
        return cls(
            plan_id=plan.plan_id,
            goal_id=plan.goal_id,
            version=plan.version,
            reasoning=plan.reasoning,
            steps=[TaskRuntimePlanStepResponse.from_step(step) for step in plan.steps],
            metadata=dict(plan.metadata),
        )


class TaskRuntimeCheckpointResponse(BaseModel):
    """任务检查点响应 DTO。"""

    model_config = ConfigDict(extra="forbid")

    checkpoint_id: str
    task_id: str | None = None
    execution_id: str | None = None
    status: TaskExecutionStatus = "pending"
    iteration_count: int = 0
    completed_step_ids: list[str] = Field(default_factory=list)
    latest_plan_id: str | None = None
    latest_step_id: str | None = None
    checkpoint_reason: str = ""
    created_at: str
    metadata: dict[str, Any] = Field(default_factory=dict)

    @classmethod
    def from_checkpoint(cls, checkpoint: TaskCheckpoint) -> "TaskRuntimeCheckpointResponse":
        return cls(
            checkpoint_id=checkpoint.checkpoint_id,
            task_id=checkpoint.task_id,
            execution_id=checkpoint.execution_id,
            status=checkpoint.status,
            iteration_count=checkpoint.iteration_count,
            completed_step_ids=list(checkpoint.completed_step_ids),
            latest_plan_id=checkpoint.latest_plan_id,
            latest_step_id=checkpoint.latest_step_id,
            checkpoint_reason=checkpoint.checkpoint_reason,
            created_at=checkpoint.created_at,
            metadata=dict(checkpoint.metadata),
        )


class TaskRuntimeArtifactResponse(BaseModel):
    """任务产物响应 DTO。"""

    model_config = ConfigDict(extra="forbid")

    artifact_id: str
    artifact_type: str
    title: str = ""
    content: Any = None
    source_plan_id: str | None = None
    source_step_id: str | None = None
    created_at: str
    metadata: dict[str, Any] = Field(default_factory=dict)

    @classmethod
    def from_artifact(cls, artifact: TaskArtifact) -> "TaskRuntimeArtifactResponse":
        return cls(
            artifact_id=artifact.artifact_id,
            artifact_type=artifact.artifact_type,
            title=artifact.title,
            content=artifact.content,
            source_plan_id=artifact.source_plan_id,
            source_step_id=artifact.source_step_id,
            created_at=artifact.created_at,
            metadata=dict(artifact.metadata),
        )


class TaskRuntimeEvaluationReportResponse(BaseModel):
    """任务验收报告响应 DTO。"""

    model_config = ConfigDict(extra="forbid")

    report_id: str
    task_id: str | None = None
    success: bool = False
    overall_score: float = 0.0
    summary: str = ""
    satisfied_criteria: list[str] = Field(default_factory=list)
    missing_criteria: list[str] = Field(default_factory=list)
    risks: list[str] = Field(default_factory=list)
    recommendations: list[str] = Field(default_factory=list)
    created_at: str
    metadata: dict[str, Any] = Field(default_factory=dict)

    @classmethod
    def from_report(cls, report: TaskEvaluationReport) -> "TaskRuntimeEvaluationReportResponse":
        return cls(
            report_id=report.report_id,
            task_id=report.task_id,
            success=report.success,
            overall_score=report.overall_score,
            summary=report.summary,
            satisfied_criteria=list(report.satisfied_criteria),
            missing_criteria=list(report.missing_criteria),
            risks=list(report.risks),
            recommendations=list(report.recommendations),
            created_at=report.created_at,
            metadata=dict(report.metadata),
        )


class TaskRuntimeTerminationResponse(BaseModel):
    """任务终止结果响应 DTO。"""

    model_config = ConfigDict(extra="forbid")

    status: str
    reason: str
    final_output: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)

    @classmethod
    def from_termination(cls, termination: TerminationDecision) -> "TaskRuntimeTerminationResponse":
        return cls(
            status=termination.status,
            reason=termination.reason,
            final_output=termination.final_output,
            metadata=dict(termination.metadata),
        )


class TaskRuntimeExecutionSummaryResponse(BaseModel):
    """任务执行摘要响应 DTO。"""

    model_config = ConfigDict(extra="forbid")

    task_id: str | None = None
    request_id: str
    execution_id: str
    status: TaskExecutionStatus = "pending"
    checkpoint_id: str | None = None
    current_plan_id: str | None = None
    current_step_id: str | None = None
    created_at: str | None = None
    updated_at: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)

    @classmethod
    def from_record(cls, record: TaskExecutionRecord) -> "TaskRuntimeExecutionSummaryResponse":
        return cls(
            task_id=record.task_id,
            request_id=record.request_id,
            execution_id=record.execution_id,
            status=record.status,
            checkpoint_id=record.checkpoint_id,
            current_plan_id=record.current_plan_id,
            current_step_id=record.current_step_id,
            created_at=record.created_at,
            updated_at=record.updated_at,
            metadata=dict(record.metadata),
        )


class TaskRuntimePrepareResponse(TaskRuntimeExecutionSummaryResponse):
    """同步准备接口响应 DTO。"""

    goal: TaskRuntimeGoalResponse
    plan: TaskRuntimePlanResponse
    evaluation_report: TaskRuntimeEvaluationReportResponse | None = None

    @classmethod
    def from_preparation(cls, preparation: TaskRuntimePreparation) -> "TaskRuntimePrepareResponse":
        return cls(
            task_id=preparation.task_id,
            request_id=preparation.request_id,
            execution_id=preparation.execution_id,
            status=preparation.status,
            checkpoint_id=preparation.checkpoint_id,
            created_at=preparation.created_at,
            updated_at=preparation.updated_at,
            metadata=dict(preparation.metadata),
            goal=TaskRuntimeGoalResponse.from_goal(preparation.goal),
            plan=TaskRuntimePlanResponse.from_plan(preparation.plan),
            evaluation_report=(
                TaskRuntimeEvaluationReportResponse.from_report(preparation.evaluation_report)
                if preparation.evaluation_report is not None
                else None
            ),
        )


class TaskRuntimeStatusResponse(TaskRuntimeExecutionSummaryResponse):
    """任务状态接口响应 DTO。"""

    goal: TaskRuntimeGoalResponse | None = None
    current_plan: TaskRuntimePlanResponse | None = None
    termination: TaskRuntimeTerminationResponse | None = None
    latest_checkpoint: TaskRuntimeCheckpointResponse | None = None
    artifacts: list[TaskRuntimeArtifactResponse] = Field(default_factory=list)
    evaluation_report: TaskRuntimeEvaluationReportResponse | None = None


class TaskRuntimeActionResponse(TaskRuntimeExecutionSummaryResponse):
    """任务生命周期动作响应 DTO。"""

    action: TaskLifecycleAction
    accepted: bool = True
    detail_message: str = ""

