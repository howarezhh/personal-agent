"""
基础智能体模块

包含：
- BaseAgent: 智能体基类
- AgentInput: 智能体输入数据结构及其专用子类
- AgentOutput: 智能体输出数据结构及其专用子类
- StreamChunk: 流式数据块及相关类
- ExecutionStatus: 执行状态类型
- ChunkType: 数据块类型
"""

from backend.agents.base.base_agent import BaseAgent
from backend.agents.base.agent_input import (
    AgentInput,
    RouterAgentInput,
    RetrievalAgentInput,
    GenerationAgentInput,
    ToolAgentInput,
    FileProcessorAgentInput
)
from backend.agents.base.agent_output import (
    AgentOutput,
    ExecutionStatus,
    RouterAgentOutput,
    RetrievalAgentOutput,
    GenerationAgentOutput,
    ToolAgentOutput,
    FileProcessorAgentOutput
)
from backend.agents.base.stream_chunk import (
    StreamChunk,
    ChunkType,
    StreamProgress,
    StreamSession
)

__all__ = [
    # 基类
    "BaseAgent",

    # 输入类
    "AgentInput",
    "RouterAgentInput",
    "RetrievalAgentInput",
    "GenerationAgentInput",
    "ToolAgentInput",
    "FileProcessorAgentInput",

    # 输出类
    "AgentOutput",
    "ExecutionStatus",
    "RouterAgentOutput",
    "RetrievalAgentOutput",
    "GenerationAgentOutput",
    "ToolAgentOutput",
    "FileProcessorAgentOutput",

    # 流式类
    "StreamChunk",
    "ChunkType",
    "StreamProgress",
    "StreamSession"
]
