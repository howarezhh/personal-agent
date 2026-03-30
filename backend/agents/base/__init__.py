# -*- coding: utf-8 -*-
"""`backend.agents.base` 包的统一导出入口。

这里改为惰性导出，避免调用方仅导入输入/输出模型时，
在包初始化阶段额外拉起 `BaseAgent` 对配置与运行时的依赖。
"""

from importlib import import_module
from typing import Any


__all__ = [
    "BaseAgent",
    "AgentInput",
    "WorkflowContext",
    "RetrievalAgentInput",
    "GenerationAgentInput",
    "ToolAgentInput",
    "FileProcessorAgentInput",
    "AgentOutput",
    "ExecutionStatus",
    "RetrievalAgentOutput",
    "GenerationAgentOutput",
    "ToolAgentOutput",
    "FileProcessorAgentOutput",
    "StreamChunk",
    "ChunkType",
    "StreamProgress",
    "StreamSession",
]


_EXPORT_MAP = {
    "BaseAgent": ("backend.agents.base.base_agent", "BaseAgent"),
    "AgentInput": ("backend.agents.base.agent_input", "AgentInput"),
    "WorkflowContext": ("backend.agents.base.agent_input", "WorkflowContext"),
    "RetrievalAgentInput": ("backend.agents.base.agent_input", "RetrievalAgentInput"),
    "GenerationAgentInput": ("backend.agents.base.agent_input", "GenerationAgentInput"),
    "ToolAgentInput": ("backend.agents.base.agent_input", "ToolAgentInput"),
    "FileProcessorAgentInput": ("backend.agents.base.agent_input", "FileProcessorAgentInput"),
    "AgentOutput": ("backend.agents.base.agent_output", "AgentOutput"),
    "ExecutionStatus": ("backend.agents.base.agent_output", "ExecutionStatus"),
    "RetrievalAgentOutput": ("backend.agents.base.agent_output", "RetrievalAgentOutput"),
    "GenerationAgentOutput": ("backend.agents.base.agent_output", "GenerationAgentOutput"),
    "ToolAgentOutput": ("backend.agents.base.agent_output", "ToolAgentOutput"),
    "FileProcessorAgentOutput": ("backend.agents.base.agent_output", "FileProcessorAgentOutput"),
    "StreamChunk": ("backend.agents.base.stream_chunk", "StreamChunk"),
    "ChunkType": ("backend.agents.base.stream_chunk", "ChunkType"),
    "StreamProgress": ("backend.agents.base.stream_chunk", "StreamProgress"),
    "StreamSession": ("backend.agents.base.stream_chunk", "StreamSession"),
}


def __getattr__(name: str) -> Any:
    """按需加载基础能力导出。"""
    if name not in _EXPORT_MAP:
        raise AttributeError(f"module 'backend.agents.base' has no attribute {name!r}")
    module_name, attr_name = _EXPORT_MAP[name]
    module = import_module(module_name)
    return getattr(module, attr_name)
