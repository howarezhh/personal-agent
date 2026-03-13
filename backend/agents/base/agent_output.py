"""
智能体输出数据结构
定义智能体执行后的输出格式
"""

from dataclasses import dataclass, field
from typing import Optional, Dict, Any, List, Literal
from datetime import datetime
import uuid


ExecutionStatus = Literal["success", "failed", "partial"]


@dataclass
class AgentOutput:
    """
    智能体输出数据结构

    所有智能体的统一输出格式
    """

    execution_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    agent_name: str = ""
    agent_type: str = ""
    content: str = ""
    status: ExecutionStatus = "success"
    error_message: Optional[str] = None
    execution_time_ms: int = 0
    metadata: Optional[Dict[str, Any]] = None

    def to_dict(self) -> dict:
        """
        转换为字典格式

        Returns:
            字典格式的输出数据
        """
        return {
            "execution_id": self.execution_id,
            "agent_name": self.agent_name,
            "agent_type": self.agent_type,
            "content": self.content,
            "status": self.status,
            "error_message": self.error_message,
            "execution_time_ms": self.execution_time_ms,
            "metadata": self.metadata,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "AgentOutput":
        """
        从字典创建AgentOutput对象

        Args:
            data: 字典数据

        Returns:
            AgentOutput对象
        """
        return cls(
            execution_id=data.get("execution_id", str(uuid.uuid4())),
            agent_name=data.get("agent_name", ""),
            agent_type=data.get("agent_type", ""),
            content=data.get("content", ""),
            status=data.get("status", "success"),
            error_message=data.get("error_message"),
            execution_time_ms=data.get("execution_time_ms", 0),
            metadata=data.get("metadata"),
        )

    def set_metadata(self, key: str, value: Any):
        """
        设置元数据

        Args:
            key: 元数据键
            value: 元数据值
        """
        if self.metadata is None:
            self.metadata = {}
        self.metadata[key] = value

    def get_metadata(self, key: str, default: Any = None) -> Any:
        """
        获取元数据

        Args:
            key: 元数据键
            default: 默认值

        Returns:
            元数据值
        """
        if self.metadata is None:
            return default
        return self.metadata.get(key, default)

    def is_success(self) -> bool:
        """
        判断执行是否成功

        Returns:
            是否成功
        """
        return self.status == "success"

    def is_failed(self) -> bool:
        """
        判断执行是否失败

        Returns:
            是否失败
        """
        return self.status == "failed"

    def __repr__(self) -> str:
        preview = self.content[:50] + "..." if len(self.content) > 50 else self.content
        return f"AgentOutput(agent_name='{self.agent_name}', status='{self.status}', content='{preview}')"


@dataclass
class RouterAgentOutput(AgentOutput):
    """
    路由智能体专用输出数据结构

    继承自AgentOutput，添加路由决策相关字段
    """

    decision_type: str = ""
    confidence: float = 0.0
    reasoning: str = ""
    suggested_agents: Optional[List[str]] = None
    suggested_tools: Optional[List[str]] = None

    def to_dict(self) -> dict:
        """
        转换为字典格式

        Returns:
            字典格式的输出数据
        """
        data = super().to_dict()
        data["decision_type"] = self.decision_type
        data["confidence"] = self.confidence
        data["reasoning"] = self.reasoning
        data["suggested_agents"] = self.suggested_agents
        data["suggested_tools"] = self.suggested_tools
        return data

    @classmethod
    def from_dict(cls, data: dict) -> "RouterAgentOutput":
        """
        从字典创建RouterAgentOutput对象

        Args:
            data: 字典数据

        Returns:
            RouterAgentOutput对象
        """
        base_output = AgentOutput.from_dict(data)
        return cls(
            execution_id=base_output.execution_id,
            agent_name=base_output.agent_name,
            agent_type=base_output.agent_type,
            content=base_output.content,
            status=base_output.status,
            error_message=base_output.error_message,
            execution_time_ms=base_output.execution_time_ms,
            metadata=base_output.metadata,
            decision_type=data.get("decision_type", ""),
            confidence=data.get("confidence", 0.0),
            reasoning=data.get("reasoning", ""),
            suggested_agents=data.get("suggested_agents"),
            suggested_tools=data.get("suggested_tools"),
        )


@dataclass
class RetrievalAgentOutput(AgentOutput):
    """
    检索智能体专用输出数据结构

    继承自AgentOutput，添加检索结果相关字段
    """

    retrieval_results: List[Dict[str, Any]] = field(default_factory=list)
    total_results: int = 0
    reranked: bool = False

    def to_dict(self) -> dict:
        """
        转换为字典格式

        Returns:
            字典格式的输出数据
        """
        data = super().to_dict()
        data["retrieval_results"] = self.retrieval_results
        data["total_results"] = self.total_results
        data["reranked"] = self.reranked
        return data

    @classmethod
    def from_dict(cls, data: dict) -> "RetrievalAgentOutput":
        """
        从字典创建RetrievalAgentOutput对象

        Args:
            data: 字典数据

        Returns:
            RetrievalAgentOutput对象
        """
        base_output = AgentOutput.from_dict(data)
        return cls(
            execution_id=base_output.execution_id,
            agent_name=base_output.agent_name,
            agent_type=base_output.agent_type,
            content=base_output.content,
            status=base_output.status,
            error_message=base_output.error_message,
            execution_time_ms=base_output.execution_time_ms,
            metadata=base_output.metadata,
            retrieval_results=data.get("retrieval_results", []),
            total_results=data.get("total_results", 0),
            reranked=data.get("reranked", False),
        )


@dataclass
class GenerationAgentOutput(AgentOutput):
    """
    生成智能体专用输出数据结构

    继承自AgentOutput，添加生成相关字段
    """

    sources: Optional[List[str]] = None
    has_hallucination: bool = False
    token_count: Optional[int] = None

    def to_dict(self) -> dict:
        """
        转换为字典格式

        Returns:
            字典格式的输出数据
        """
        data = super().to_dict()
        data["sources"] = self.sources
        data["has_hallucination"] = self.has_hallucination
        data["token_count"] = self.token_count
        return data

    @classmethod
    def from_dict(cls, data: dict) -> "GenerationAgentOutput":
        """
        从字典创建GenerationAgentOutput对象

        Args:
            data: 字典数据

        Returns:
            GenerationAgentOutput对象
        """
        base_output = AgentOutput.from_dict(data)
        return cls(
            execution_id=base_output.execution_id,
            agent_name=base_output.agent_name,
            agent_type=base_output.agent_type,
            content=base_output.content,
            status=base_output.status,
            error_message=base_output.error_message,
            execution_time_ms=base_output.execution_time_ms,
            metadata=base_output.metadata,
            sources=data.get("sources"),
            has_hallucination=data.get("has_hallucination", False),
            token_count=data.get("token_count"),
        )


@dataclass
class ToolAgentOutput(AgentOutput):
    """
    工具智能体专用输出数据结构

    继承自AgentOutput，添加工具调用相关字段
    """

    tool_calls: List[Dict[str, Any]] = field(default_factory=list)
    total_calls: int = 0
    successful_calls: int = 0
    failed_calls: int = 0

    def to_dict(self) -> dict:
        """
        转换为字典格式

        Returns:
            字典格式的输出数据
        """
        data = super().to_dict()
        data["tool_calls"] = self.tool_calls
        data["total_calls"] = self.total_calls
        data["successful_calls"] = self.successful_calls
        data["failed_calls"] = self.failed_calls
        return data

    @classmethod
    def from_dict(cls, data: dict) -> "ToolAgentOutput":
        """
        从字典创建ToolAgentOutput对象

        Args:
            data: 字典数据

        Returns:
            ToolAgentOutput对象
        """
        base_output = AgentOutput.from_dict(data)
        return cls(
            execution_id=base_output.execution_id,
            agent_name=base_output.agent_name,
            agent_type=base_output.agent_type,
            content=base_output.content,
            status=base_output.status,
            error_message=base_output.error_message,
            execution_time_ms=base_output.execution_time_ms,
            metadata=base_output.metadata,
            tool_calls=data.get("tool_calls", []),
            total_calls=data.get("total_calls", 0),
            successful_calls=data.get("successful_calls", 0),
            failed_calls=data.get("failed_calls", 0),
        )


@dataclass
class FileProcessorAgentOutput(AgentOutput):
    """
    文件处理智能体专用输出数据结构

    继承自AgentOutput，添加文件处理相关字段
    """

    extracted_text: str = ""
    extracted_images: Optional[List[str]] = None
    extracted_tables: Optional[List[Dict[str, Any]]] = None
    file_metadata: Optional[Dict[str, Any]] = None
    page_count: Optional[int] = None

    def to_dict(self) -> dict:
        """
        转换为字典格式

        Returns:
            字典格式的输出数据
        """
        data = super().to_dict()
        data["extracted_text"] = self.extracted_text
        data["extracted_images"] = self.extracted_images
        data["extracted_tables"] = self.extracted_tables
        data["file_metadata"] = self.file_metadata
        data["page_count"] = self.page_count
        return data

    @classmethod
    def from_dict(cls, data: dict) -> "FileProcessorAgentOutput":
        """
        从字典创建FileProcessorAgentOutput对象

        Args:
            data: 字典数据

        Returns:
            FileProcessorAgentOutput对象
        """
        base_output = AgentOutput.from_dict(data)
        return cls(
            execution_id=base_output.execution_id,
            agent_name=base_output.agent_name,
            agent_type=base_output.agent_type,
            content=base_output.content,
            status=base_output.status,
            error_message=base_output.error_message,
            execution_time_ms=base_output.execution_time_ms,
            metadata=base_output.metadata,
            extracted_text=data.get("extracted_text", ""),
            extracted_images=data.get("extracted_images"),
            extracted_tables=data.get("extracted_tables"),
            file_metadata=data.get("file_metadata"),
            page_count=data.get("page_count"),
        )
