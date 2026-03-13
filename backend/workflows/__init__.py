"""
工作流模块
提供Agent工作流执行和协调功能
"""

from backend.workflows.workflow_executor import WorkflowExecutor
from backend.workflows.state_graph import (
    WorkflowState,
    WorkflowAction,
    WorkflowStateGraph,
    get_state_graph
)
from backend.workflows.multi_agent_workflow import (
    MultiAgentWorkflow,
    WorkflowBuilder,
    get_workflow_template,
    WORKFLOW_TEMPLATES
)

__all__ = [
    # 工作流执行器
    "WorkflowExecutor",

    # 状态图
    "WorkflowState",
    "WorkflowAction",
    "WorkflowStateGraph",
    "get_state_graph",

    # 多Agent工作流
    "MultiAgentWorkflow",
    "WorkflowBuilder",
    "get_workflow_template",
    "WORKFLOW_TEMPLATES",
]
