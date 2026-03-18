# -*- coding: utf-8 -*-
"""Agent 输出模型定义。

本模块统一定义多 Agent 体系中的标准输出结构，作用包括：
- 固化所有 Agent 共享的运行时输出字段；
- 为不同类型的 Agent 提供专用输出扩展；
- 统一字典序列化与安全读取逻辑；
- 为上层 API、工作流和日志系统提供稳定数据载体。

说明：
- 协议字段、默认值和序列化规则统一以下沉到 `backend.contracts.agent_io` 为准；
- 本文件只保留运行时 dataclass 与便捷行为方法。
"""

from copy import deepcopy
from dataclasses import asdict, dataclass, field, fields
from typing import Any, Dict, List, Optional
import uuid

from backend.contracts.agent_io import (
    AGENT_IO_PROTOCOL_VERSION,
    AgentExecutionStatus as ExecutionStatus,
    normalize_agent_output_payload,
)


@dataclass
class AgentOutput:
    """所有 Agent 共享的标准输出基类。"""

    protocol_version: str = AGENT_IO_PROTOCOL_VERSION
    execution_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    agent_name: str = ""
    agent_type: str = ""
    content: str = ""
    status: ExecutionStatus = "success"
    error_message: Optional[str] = None
    execution_time_ms: int = 0
    request_id: Optional[str] = None
    conversation_id: Optional[str] = None
    message_id: Optional[str] = None
    knowledge_base_id: Optional[str] = None
    document_id: Optional[str] = None
    route_decision: Optional[Dict[str, Any]] = None
    retrieval_results: Optional[List[Dict[str, Any]]] = None
    tool_result: Optional[Dict[str, Any]] = None
    metadata: Optional[Dict[str, Any]] = None

    def to_dict(self) -> dict:
        """将输出对象转换为统一协议字典。"""
        return normalize_agent_output_payload(asdict(self), type(self))

    @classmethod
    def from_dict(cls, data: dict) -> "AgentOutput":
        """从字典恢复输出对象。"""
        if not isinstance(data, dict):
            raise TypeError(f"{cls.__name__}.from_dict expects a dict")

        normalized = normalize_agent_output_payload(data, cls)
        init_data: Dict[str, Any] = {}
        for field_info in fields(cls):
            if field_info.name not in normalized:
                continue
            init_data[field_info.name] = deepcopy(normalized.get(field_info.name))
        return cls(**init_data)

    def to_payload(self) -> Dict[str, Any]:
        """提取适合继续传递给后续步骤的载荷字段。"""
        payload = self.to_dict()
        excluded_fields = {
            "protocol_version",
            "agent_name",
            "agent_type",
            "status",
            "error_message",
            "execution_time_ms",
            "metadata",
        }
        return {
            key: value
            for key, value in payload.items()
            if key not in excluded_fields and value is not None
        }

    def set_metadata(self, key: str, value: Any):
        """写入单个 metadata 字段。"""
        if self.metadata is None:
            self.metadata = {}
        self.metadata[key] = value

    def get_metadata(self, key: str, default: Any = None) -> Any:
        """读取单个 metadata 字段。"""
        if self.metadata is None:
            return default
        return self.metadata.get(key, default)

    def get_route_decision(self) -> Optional[Dict[str, Any]]:
        """返回路由决策的深拷贝。"""
        if isinstance(self.route_decision, dict):
            return deepcopy(self.route_decision)
        return None

    def get_retrieval_results(self) -> Optional[List[Dict[str, Any]]]:
        """返回检索结果列表的深拷贝。"""
        if isinstance(self.retrieval_results, list):
            return deepcopy(self.retrieval_results)
        return None

    def get_tool_result(self) -> Optional[Dict[str, Any]]:
        """返回工具结果的深拷贝。"""
        if isinstance(self.tool_result, dict):
            return deepcopy(self.tool_result)
        return None

    def is_success(self) -> bool:
        """判断当前输出是否为成功态。"""
        return self.status == "success"

    def is_failed(self) -> bool:
        """判断当前输出是否为失败态。"""
        return self.status == "failed"

    def __repr__(self) -> str:
        """返回带内容摘要的调试文本。"""
        preview = self.content[:50] + "..." if len(self.content) > 50 else self.content
        return f"AgentOutput(agent_name='{self.agent_name}', status='{self.status}', content='{preview}')"


@dataclass
class RouterAgentOutput(AgentOutput):
    """路由 Agent 的输出模型。"""

    confidence: Optional[float] = None
    reasoning: Optional[str] = None
    suggested_agents: Optional[List[str]] = None
    suggested_tools: Optional[List[str]] = None


@dataclass
class RetrievalAgentOutput(AgentOutput):
    """检索 Agent 的输出模型。"""

    rewrite_info: Optional[Dict[str, Any]] = None


@dataclass
class GenerationAgentOutput(AgentOutput):
    """生成 Agent 的输出模型。"""

    citations: Optional[List[Dict[str, Any]]] = None
    sources: Optional[List[Dict[str, Any]]] = None
    has_hallucination: bool = False
    token_count: Optional[int] = None


@dataclass
class ToolAgentOutput(AgentOutput):
    """工具 Agent 的输出模型。"""

    tool_name: Optional[str] = None
    tool_params: Optional[Dict[str, Any]] = None
    interpreted_result: Optional[Dict[str, Any]] = None
    tool_call_id: Optional[str] = None
    tool_calls: List[Dict[str, Any]] = field(default_factory=list)
    no_tool_needed: Optional[bool] = None
    reasoning: Optional[str] = None
    route_action: Optional[str] = None
    total_calls: int = 0
    successful_calls: int = 0
    failed_calls: int = 0


@dataclass
class FileProcessorAgentOutput(AgentOutput):
    """文件处理 Agent 的输出模型。"""

    file_id: Optional[str] = None
    chunk_count: Optional[int] = None
    summary: Optional[str] = None
    extracted_text: str = ""
    extracted_images: Optional[List[str]] = None
    extracted_tables: Optional[List[Dict[str, Any]]] = None
    file_metadata: Optional[Dict[str, Any]] = None
    page_count: Optional[int] = None
