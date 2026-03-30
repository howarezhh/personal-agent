# -*- coding: utf-8 -*-
"""Agent 输入模型定义。

本模块负责统一定义多 Agent 体系中的标准输入结构，目标是：
- 固化跨 Agent 共享的公共字段；
- 为不同类型的 Agent 提供专用扩展输入；
- 提供安全的字典互转与深拷贝能力；
- 在输入进入业务逻辑前完成基础校验。

说明：
- 这里的模型属于 Agent 运行时输入载体，不再自带协议定义；
- 标准字段、默认值、序列化规范统一以 `backend.contracts.agent_io` 为准；
- 各个 getter 方法统一返回拷贝结果，避免调用方无意修改原始输入对象。
"""

from copy import deepcopy
from dataclasses import asdict, dataclass, field, fields
from typing import Any, Dict, List, Optional

from backend.contracts.agent_io import (
    AGENT_IO_PROTOCOL_VERSION,
    normalize_agent_input_payload,
    normalize_workflow_context_payload,
)


@dataclass
class WorkflowContext:
    """工作流上下文。"""

    step_results: Dict[str, Any] = field(default_factory=dict)
    step_config: Dict[str, Any] = field(default_factory=dict)
    previous_output: Optional[Dict[str, Any]] = None

    def to_dict(self) -> dict:
        """将工作流上下文转换为统一协议字典。"""
        return normalize_workflow_context_payload(asdict(self)) or {}

    @classmethod
    def from_dict(cls, data: Any) -> Optional["WorkflowContext"]:
        """从任意输入恢复 `WorkflowContext`。"""
        if data is None:
            return None
        if isinstance(data, cls):
            return cls(
                step_results=deepcopy(data.step_results),
                step_config=deepcopy(data.step_config),
                previous_output=deepcopy(data.previous_output),
            )

        normalized = normalize_workflow_context_payload(data)
        if normalized is None:
            return None

        return cls(
            step_results=deepcopy(normalized.get("step_results", {})),
            step_config=deepcopy(normalized.get("step_config", {})),
            previous_output=deepcopy(normalized.get("previous_output")),
        )


@dataclass
class AgentInput:
    """所有 Agent 共享的标准输入基类。"""

    user_id: str
    conversation_id: str
    content: str
    protocol_version: str = AGENT_IO_PROTOCOL_VERSION
    message_id: Optional[str] = None
    request_id: Optional[str] = None
    execution_id: Optional[str] = None
    knowledge_base_id: Optional[str] = None
    document_id: Optional[str] = None
    enable_knowledge_base: Optional[bool] = None
    conversation_history: Optional[List[Dict[str, Any]]] = None
    retrieval_results: Optional[List[Dict[str, Any]]] = None
    tool_results: Optional[List[Dict[str, Any]]] = None
    metadata: Optional[Dict[str, Any]] = None
    workflow_context: Optional[WorkflowContext] = None

    def to_dict(self) -> dict:
        """将输入对象转换为统一协议字典。"""
        return normalize_agent_input_payload(asdict(self), type(self))

    @classmethod
    def from_dict(cls, data: dict) -> "AgentInput":
        """从字典恢复输入对象。"""
        if not isinstance(data, dict):
            raise TypeError("AgentInput.from_dict expects a dict")

        normalized = normalize_agent_input_payload(data, cls)
        init_data: Dict[str, Any] = {}
        for field_info in fields(cls):
            if field_info.name not in normalized:
                continue
            value = normalized.get(field_info.name)
            if field_info.name == "workflow_context":
                init_data[field_info.name] = WorkflowContext.from_dict(value)
                continue
            init_data[field_info.name] = deepcopy(value)

        return cls(**init_data)

    @classmethod
    def from_agent_input(cls, agent_input: "AgentInput", **overrides: Any) -> "AgentInput":
        """基于已有输入对象创建新对象，并允许覆盖部分字段。"""
        data = agent_input.to_dict()
        for key, value in overrides.items():
            data[key] = deepcopy(value)
        return cls.from_dict(data)

    def clone_with(self, **overrides: Any) -> "AgentInput":
        """返回当前输入对象的克隆版本，并应用指定字段覆盖。"""
        return type(self).from_agent_input(self, **overrides)

    def set_metadata(self, key: str, value: Any):
        """设置单个 metadata 字段。"""
        if self.metadata is None:
            self.metadata = {}
        self.metadata[key] = value

    def get_metadata(self, key: str, default: Any = None) -> Any:
        """读取单个 metadata 字段，不存在时返回默认值。"""
        if self.metadata is None:
            return default
        return self.metadata.get(key, default)

    def get_request_id(self) -> Optional[str]:
        """返回请求 ID。"""
        return self.request_id

    def get_execution_id(self) -> Optional[str]:
        """返回执行 ID。"""
        return self.execution_id

    def get_knowledge_base_id(self) -> Optional[str]:
        """返回知识库 ID。"""
        return self.knowledge_base_id

    def get_document_id(self) -> Optional[str]:
        """返回文档 ID。"""
        return self.document_id

    def is_knowledge_enabled(self, default: bool = True) -> bool:
        """判断当前输入是否启用知识库能力。"""
        if self.enable_knowledge_base is None:
            return bool(default)
        return bool(self.enable_knowledge_base)

    def get_conversation_history(self) -> List[Dict[str, Any]]:
        """返回历史会话列表的深拷贝。"""
        if isinstance(self.conversation_history, list):
            return deepcopy(self.conversation_history)
        return []

    def get_retrieval_results(self) -> Optional[List[Dict[str, Any]]]:
        """返回检索结果列表的深拷贝。"""
        if isinstance(self.retrieval_results, list):
            return deepcopy(self.retrieval_results)
        return None

    def get_tool_results(self) -> Optional[List[Dict[str, Any]]]:
        """返回工具调用结果列表的深拷贝。"""
        if isinstance(self.tool_results, list):
            return deepcopy(self.tool_results)
        return None

    def get_latest_tool_result(self) -> Optional[Dict[str, Any]]:
        """返回最近一次工具调用结果。"""
        tool_results = self.get_tool_results()
        if not tool_results:
            return None
        latest_result = tool_results[-1]
        return deepcopy(latest_result) if isinstance(latest_result, dict) else None

    def get_available_tools(self) -> Optional[List[str]]:
        """返回可用工具列表。"""
        available_tools = getattr(self, "available_tools", None)
        if isinstance(available_tools, list):
            return deepcopy(available_tools)
        return None

    def get_workflow_context(self) -> Optional[WorkflowContext]:
        """返回工作流上下文对象的安全副本。"""
        return WorkflowContext.from_dict(self.workflow_context)

    def validate(self) -> tuple[bool, Optional[str]]:
        """执行基础输入校验。"""
        if self.protocol_version != AGENT_IO_PROTOCOL_VERSION:
            return False, f"unsupported protocol_version: {self.protocol_version}"
        if not self.user_id:
            return False, "user_id is required"
        if not self.conversation_id:
            return False, "conversation_id is required"

        has_content = bool(self.content)
        has_tool_input = bool(getattr(self, "tool_name", None))
        has_file_input = bool(getattr(self, "file_id", None) or getattr(self, "file_path", None))
        if not (has_content or has_tool_input or has_file_input):
            return False, "content is required"

        if self.metadata is not None and not isinstance(self.metadata, dict):
            return False, "metadata must be a dict"
        if self.conversation_history is not None and not isinstance(self.conversation_history, list):
            return False, "conversation_history must be a list"
        if self.retrieval_results is not None and not isinstance(self.retrieval_results, list):
            return False, "retrieval_results must be a list"
        if self.tool_results is not None and not isinstance(self.tool_results, list):
            return False, "tool_results must be a list"

        return True, None

    def __repr__(self) -> str:
        """返回带内容摘要的调试文本。"""
        preview = self.content[:50] + "..." if len(self.content) > 50 else self.content
        return (
            f"AgentInput(user_id='{self.user_id}', conversation_id='{self.conversation_id}', "
            f"content='{preview}')"
        )


@dataclass
class RetrievalAgentInput(AgentInput):
    """检索 Agent 的输入模型。"""

    vector_search_filter: Optional[Dict[str, Any]] = None
    top_k: int = 5
    enable_rerank: bool = True
    rerank_top_k: Optional[int] = None
    keyword_top_k: Optional[int] = None
    enable_exact_phrase: Optional[bool] = None
    enable_sparse_keyword: Optional[bool] = None
    enable_dense_vector: Optional[bool] = None
    enable_fusion_rank: Optional[bool] = None
    enable_hybrid_retrieval: Optional[bool] = None

    def validate(self) -> tuple[bool, Optional[str]]:
        """校验检索场景特有字段。"""
        is_valid, error_message = super().validate()
        if not is_valid:
            return is_valid, error_message
        if self.vector_search_filter is not None and not isinstance(self.vector_search_filter, dict):
            return False, "vector_search_filter must be a dict"
        if self.top_k <= 0:
            return False, "top_k must be greater than 0"
        if self.rerank_top_k is not None and self.rerank_top_k <= 0:
            return False, "rerank_top_k must be greater than 0"
        if self.keyword_top_k is not None and self.keyword_top_k <= 0:
            return False, "keyword_top_k must be greater than 0"
        return True, None


@dataclass
class GenerationAgentInput(AgentInput):
    """生成 Agent 的输入模型。"""

    context: Optional[str] = None
    sources: Optional[List[Dict[str, Any]]] = None

    def validate(self) -> tuple[bool, Optional[str]]:
        """校验生成场景特有字段。"""
        is_valid, error_message = super().validate()
        if not is_valid:
            return is_valid, error_message
        if self.sources is not None and not isinstance(self.sources, list):
            return False, "sources must be a list"
        return True, None


@dataclass
class ToolAgentInput(AgentInput):
    """工具 Agent 的输入模型。"""

    available_tools: Optional[List[str]] = None
    tool_timeout: Optional[int] = None
    tool_name: Optional[str] = None
    tool_params: Optional[Dict[str, Any]] = None

    def validate(self) -> tuple[bool, Optional[str]]:
        """校验工具场景特有字段。"""
        is_valid, error_message = super().validate()
        if not is_valid:
            return is_valid, error_message
        if self.available_tools is not None and not isinstance(self.available_tools, list):
            return False, "available_tools must be a list"
        if self.tool_params is not None and not isinstance(self.tool_params, dict):
            return False, "tool_params must be a dict"
        if self.tool_timeout is not None and self.tool_timeout <= 0:
            return False, "tool_timeout must be greater than 0"
        return True, None


@dataclass
class FileProcessorAgentInput(AgentInput):
    """文件处理 Agent 的输入模型。"""

    file_id: Optional[str] = None
    file_path: Optional[str] = None
    file_type: Optional[str] = None
    file_metadata: Optional[Dict[str, Any]] = None

    def validate(self) -> tuple[bool, Optional[str]]:
        """校验文件处理场景特有字段。"""
        is_valid, error_message = super().validate()
        if not is_valid:
            return is_valid, error_message
        if self.file_metadata is not None and not isinstance(self.file_metadata, dict):
            return False, "file_metadata must be a dict"
        return True, None
