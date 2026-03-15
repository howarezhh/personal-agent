
from dataclasses import dataclass, field
from typing import Optional, Dict, Any, Literal
from datetime import datetime
import uuid
import json


AgentType = Literal["router", "retrieval", "generation", "tool", "file_processor"]
ExecutionStatus = Literal["success", "failed", "partial", "running"]


@dataclass
class AgentExecution:
    execution_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    conversation_id: Optional[str] = None  # 可为空，直接工具调用时为None
    message_id: Optional[str] = None
    agent_name: str = ""
    agent_type: AgentType = "generation"
    input_data: Optional[Dict[str, Any]] = None
    output_data: Optional[Dict[str, Any]] = None
    status: ExecutionStatus = "running"
    error_message: Optional[str] = None
    execution_time_ms: Optional[int] = None
    created_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None
    metadata: Optional[Dict[str, Any]] = None

    def to_dict(self) -> dict:
        return {
            "execution_id": self.execution_id,
            "conversation_id": self.conversation_id,
            "message_id": self.message_id,
            "agent_name": self.agent_name,
            "agent_type": self.agent_type,
            "input_data": self.input_data,
            "output_data": self.output_data,
            "status": self.status,
            "error_message": self.error_message,
            "execution_time_ms": self.execution_time_ms,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "completed_at": self.completed_at.isoformat() if self.completed_at else None,
            "metadata": self.metadata,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "AgentExecution":
        # 处理datetime字段
        if isinstance(data.get("created_at"), str):
            data["created_at"] = datetime.fromisoformat(data["created_at"].replace("Z", "+00:00"))
        if isinstance(data.get("completed_at"), str):
            data["completed_at"] = datetime.fromisoformat(data["completed_at"].replace("Z", "+00:00"))

        # 处理JSON字段（如果是字符串，解析为字典）
        for field_name in ["input_data", "output_data", "metadata"]:
            if isinstance(data.get(field_name), str):
                try:
                    data[field_name] = json.loads(data[field_name])
                except json.JSONDecodeError:
                    data[field_name] = None

        return cls(**data)

    @classmethod
    def from_db_row(cls, row: tuple, columns: list) -> "AgentExecution":
        data = dict(zip(columns, row))
        return cls.from_dict(data)

    def set_metadata(self, key: str, value: Any):
        if self.metadata is None:
            self.metadata = {}
        self.metadata[key] = value

    def get_metadata(self, key: str, default: Any = None) -> Any:
        if self.metadata is None:
            return default
        return self.metadata.get(key, default)

    def mark_success(self, output_data: Dict[str, Any], execution_time_ms: int):
        self.status = "success"
        self.output_data = output_data
        self.execution_time_ms = execution_time_ms
        self.completed_at = datetime.utcnow()

    def mark_failed(self, error_message: str, execution_time_ms: int = None):
        self.status = "failed"
        self.error_message = error_message
        if execution_time_ms is not None:
            self.execution_time_ms = execution_time_ms
        self.completed_at = datetime.utcnow()

    def __repr__(self) -> str:
        return f"AgentExecution(execution_id='{self.execution_id}', agent_name='{self.agent_name}', status='{self.status}')"


@dataclass
class AgentExecutionCreate:
    agent_name: str
    agent_type: AgentType
    conversation_id: Optional[str] = None  # 可为空，直接工具调用时为None
    input_data: Optional[Dict[str, Any]] = None
    message_id: Optional[str] = None
    metadata: Optional[Dict[str, Any]] = None

    def to_agent_execution(self) -> AgentExecution:
        return AgentExecution(
            conversation_id=self.conversation_id,
            message_id=self.message_id,
            agent_name=self.agent_name,
            agent_type=self.agent_type,
            input_data=self.input_data,
            metadata=self.metadata,
            status="running",
            created_at=datetime.utcnow(),
        )


@dataclass
class AgentExecutionUpdate:
    output_data: Optional[Dict[str, Any]] = None
    status: Optional[ExecutionStatus] = None
    error_message: Optional[str] = None
    execution_time_ms: Optional[int] = None
    completed_at: Optional[datetime] = None
    metadata: Optional[Dict[str, Any]] = None

    def to_dict(self) -> dict:
        data = {}
        if self.output_data is not None:
            data["output_data"] = json.dumps(self.output_data, ensure_ascii=False)
        if self.status is not None:
            data["status"] = self.status
        if self.error_message is not None:
            data["error_message"] = self.error_message
        if self.execution_time_ms is not None:
            data["execution_time_ms"] = self.execution_time_ms
        if self.completed_at is not None:
            data["completed_at"] = self.completed_at
        if self.metadata is not None:
            data["metadata"] = json.dumps(self.metadata, ensure_ascii=False)
        return data
