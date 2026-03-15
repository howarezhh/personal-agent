"""`backend.workflows` 包导出入口。

该模块统一暴露工作流相关的核心能力，方便上层调用方以稳定接口访问：
1. `WorkflowExecutor`：负责根据路由结果调度不同工作流；
2. `WorkflowStateGraph`：负责维护工作流状态与状态转换规则；
3. `MultiAgentWorkflow`：负责多 Agent 顺序/并行/分支协作；
4. 预置模板与构建器：用于快速拼装标准工作流配置。
"""

from backend.workflows.workflow_executor import WorkflowExecutor
from backend.workflows.state_graph import (
    WorkflowState,
    WorkflowAction,
    WorkflowStateGraph,
    get_state_graph,
)
from backend.workflows.multi_agent_workflow import (
    MultiAgentWorkflow,
    WorkflowBuilder,
    get_workflow_template,
    WORKFLOW_TEMPLATES,
)

__all__ = [
    # 工作流执行入口。
    "WorkflowExecutor",
    # 状态图相关能力。
    "WorkflowState",
    "WorkflowAction",
    "WorkflowStateGraph",
    "get_state_graph",
    # 多 Agent 工作流相关能力。
    "MultiAgentWorkflow",
    "WorkflowBuilder",
    "get_workflow_template",
    "WORKFLOW_TEMPLATES",
]