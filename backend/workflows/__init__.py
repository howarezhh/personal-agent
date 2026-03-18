"""`backend.workflows` 包导出入口。

这里改为惰性导出，避免导入单个工作流模块时把其它执行器与 Agent 依赖一并拉起。
"""

from importlib import import_module
from typing import Any


__all__ = [
    "WorkflowExecutor",
    "WorkflowState",
    "WorkflowAction",
    "WorkflowStateGraph",
    "get_state_graph",
    "MultiAgentWorkflow",
    "WorkflowBuilder",
    "get_workflow_template",
    "WORKFLOW_TEMPLATES",
]


_EXPORT_MAP = {
    "WorkflowExecutor": ("backend.workflows.workflow_executor", "WorkflowExecutor"),
    "WorkflowState": ("backend.workflows.state_graph", "WorkflowState"),
    "WorkflowAction": ("backend.workflows.state_graph", "WorkflowAction"),
    "WorkflowStateGraph": ("backend.workflows.state_graph", "WorkflowStateGraph"),
    "get_state_graph": ("backend.workflows.state_graph", "get_state_graph"),
    "MultiAgentWorkflow": ("backend.workflows.multi_agent_workflow", "MultiAgentWorkflow"),
    "WorkflowBuilder": ("backend.workflows.multi_agent_workflow", "WorkflowBuilder"),
    "get_workflow_template": ("backend.workflows.multi_agent_workflow", "get_workflow_template"),
    "WORKFLOW_TEMPLATES": ("backend.workflows.multi_agent_workflow", "WORKFLOW_TEMPLATES"),
}


def __getattr__(name: str) -> Any:
    """按需导出工作流能力。"""
    if name not in _EXPORT_MAP:
        raise AttributeError(f"module 'backend.workflows' has no attribute {name!r}")
    module_name, attr_name = _EXPORT_MAP[name]
    module = import_module(module_name)
    return getattr(module, attr_name)
