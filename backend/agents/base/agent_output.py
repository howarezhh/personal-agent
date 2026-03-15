
from dataclasses import dataclass, field
from typing import Optional, Dict, Any, List, Literal
from datetime import datetime
import uuid


ExecutionStatus = Literal["success", "failed", "partial"]


@dataclass
class AgentOutput:
    execution_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    agent_name: str = ""
    agent_type: str = ""
    content: str = ""
    status: ExecutionStatus = "success"
    error_message: Optional[str] = None
    execution_time_ms: int = 0
    metadata: Optional[Dict[str, Any]] = None

    def to_dict(self) -> dict:
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
        if self.metadata is None:
            self.metadata = {}
        self.metadata[key] = value

    def get_metadata(self, key: str, default: Any = None) -> Any:
        if self.metadata is None:
            return default
        return self.metadata.get(key, default)

    def is_success(self) -> bool:
        return self.status == "success"

    def is_failed(self) -> bool:
        return self.status == "failed"

    def __repr__(self) -> str:
        preview = self.content[:50] + "..." if len(self.content) > 50 else self.content
        return f"AgentOutput(agent_name='{self.agent_name}', status='{self.status}', content='{preview}')"


@dataclass
class RouterAgentOutput(AgentOutput):
    decision_type: str = ""
    confidence: float = 0.0
    reasoning: str = ""
    suggested_agents: Optional[List[str]] = None
    suggested_tools: Optional[List[str]] = None

    def to_dict(self) -> dict:
        data = super().to_dict()
        data["decision_type"] = self.decision_type
        data["confidence"] = self.confidence
        data["reasoning"] = self.reasoning
        data["suggested_agents"] = self.suggested_agents
        data["suggested_tools"] = self.suggested_tools
        return data

    @classmethod
    def from_dict(cls, data: dict) -> "RouterAgentOutput":
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
    retrieval_results: List[Dict[str, Any]] = field(default_factory=list)
    total_results: int = 0
    reranked: bool = False

    def to_dict(self) -> dict:
        data = super().to_dict()
        data["retrieval_results"] = self.retrieval_results
        data["total_results"] = self.total_results
        data["reranked"] = self.reranked
        return data

    @classmethod
    def from_dict(cls, data: dict) -> "RetrievalAgentOutput":
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
    sources: Optional[List[str]] = None
    has_hallucination: bool = False
    token_count: Optional[int] = None

    def to_dict(self) -> dict:
        data = super().to_dict()
        data["sources"] = self.sources
        data["has_hallucination"] = self.has_hallucination
        data["token_count"] = self.token_count
        return data

    @classmethod
    def from_dict(cls, data: dict) -> "GenerationAgentOutput":
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
    tool_calls: List[Dict[str, Any]] = field(default_factory=list)
    total_calls: int = 0
    successful_calls: int = 0
    failed_calls: int = 0

    def to_dict(self) -> dict:
        data = super().to_dict()
        data["tool_calls"] = self.tool_calls
        data["total_calls"] = self.total_calls
        data["successful_calls"] = self.successful_calls
        data["failed_calls"] = self.failed_calls
        return data

    @classmethod
    def from_dict(cls, data: dict) -> "ToolAgentOutput":
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
    extracted_text: str = ""
    extracted_images: Optional[List[str]] = None
    extracted_tables: Optional[List[Dict[str, Any]]] = None
    file_metadata: Optional[Dict[str, Any]] = None
    page_count: Optional[int] = None

    def to_dict(self) -> dict:
        data = super().to_dict()
        data["extracted_text"] = self.extracted_text
        data["extracted_images"] = self.extracted_images
        data["extracted_tables"] = self.extracted_tables
        data["file_metadata"] = self.file_metadata
        data["page_count"] = self.page_count
        return data

    @classmethod
    def from_dict(cls, data: dict) -> "FileProcessorAgentOutput":
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
