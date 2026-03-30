from __future__ import annotations

from typing import Protocol

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


class GoalParser(Protocol):
    """目标解析器接口。"""

    async def parse_goal(self, request: TaskControllerRequest) -> TaskGoal:
        """把用户输入解析为明确任务目标。"""


class Planner(Protocol):
    """规划器接口。"""

    async def create_plan(self, goal: TaskGoal, state: TaskRuntimeState) -> TaskPlan:
        """根据目标与当前状态生成新计划。"""


class StepExecutor(Protocol):
    """步骤执行器接口。"""

    async def execute_step(self, step: TaskPlanStep, state: TaskRuntimeState) -> StepObservation:
        """执行单个步骤并返回执行观测。"""


class StepEvaluator(Protocol):
    """步骤评估器接口。"""

    async def evaluate_step(
        self,
        step: TaskPlanStep,
        observation: StepObservation,
        goal: TaskGoal,
        state: TaskRuntimeState,
    ) -> StepEvaluation:
        """评估单个步骤是否完成、是否需要重试或重规划。"""


class GoalJudge(Protocol):
    """目标判定器接口。"""

    async def evaluate_goal(self, goal: TaskGoal, state: TaskRuntimeState) -> GoalEvaluation:
        """判断整体目标是否已经完成。"""


class Replanner(Protocol):
    """重规划器接口。"""

    async def decide_replan(
        self,
        goal: TaskGoal,
        state: TaskRuntimeState,
        *,
        goal_evaluation: GoalEvaluation | None = None,
        step_evaluation: StepEvaluation | None = None,
    ) -> ReplanDecision:
        """根据目标评估或步骤评估决定是否生成新计划。"""

