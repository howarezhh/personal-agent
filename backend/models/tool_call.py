
from dataclasses import dataclass, field
from typing import Optional, Dict, Any, Literal
from datetime import datetime
import uuid
import json

from backend.utils.time_utils import utc_now


ToolCallStatus = Literal["success", "failed", "timeout", "running"]


@dataclass
class ToolCall:
    call_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    execution_id: str = ""
    tool_name: str = ""
    tool_type: Optional[str] = None
    tool_input: Optional[Dict[str, Any]] = None
    tool_output: Optional[Dict[str, Any]] = None
    status: ToolCallStatus = "running"
    error_message: Optional[str] = None
    execution_time_ms: Optional[int] = None
    created_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None
    metadata: Optional[Dict[str, Any]] = None

    def to_dict(self) -> dict:
        return {
            "call_id": self.call_id,
            "execution_id": self.execution_id,
            "tool_name": self.tool_name,
            "tool_type": self.tool_type,
            "tool_input": self.tool_input,
            "tool_output": self.tool_output,
            "status": self.status,
            "error_message": self.error_message,
            "execution_time_ms": self.execution_time_ms,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "completed_at": self.completed_at.isoformat() if self.completed_at else None,
            "metadata": self.metadata,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "ToolCall":
        # 处理datetime字段
        if isinstance(data.get("created_at"), str):
            data["created_at"] = datetime.fromisoformat(data["created_at"].replace("Z", "+00:00"))
        if isinstance(data.get("completed_at"), str):
            data["completed_at"] = datetime.fromisoformat(data["completed_at"].replace("Z", "+00:00"))

        # 处理JSON字段（如果是字符串，解析为字典）
        for field_name in ["tool_input", "tool_output", "metadata"]:
            if isinstance(data.get(field_name), str):
                try:
                    data[field_name] = json.loads(data[field_name])
                except json.JSONDecodeError:
                    data[field_name] = None

        return cls(**data)

    @classmethod
    def from_db_row(cls, row: tuple, columns: list) -> "ToolCall":
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

    def mark_success(self, tool_output: Dict[str, Any], execution_time_ms: int):
        self.status = "success"
        self.tool_output = tool_output
        self.execution_time_ms = execution_time_ms
        self.completed_at = utc_now()

    def mark_failed(self, error_message: str, execution_time_ms: int = None):
        self.status = "failed"
        self.error_message = error_message
        if execution_time_ms is not None:
            self.execution_time_ms = execution_time_ms
        self.completed_at = utc_now()

    def mark_timeout(self, execution_time_ms: int):
        self.status = "timeout"
        self.error_message = "Tool call timeout"
        self.execution_time_ms = execution_time_ms
        self.completed_at = utc_now()

    def __repr__(self) -> str:
        return f"ToolCall(call_id='{self.call_id}', tool_name='{self.tool_name}', status='{self.status}')"


@dataclass
class ToolCallCreate:
    execution_id: str
    tool_name: str
    tool_input: Optional[Dict[str, Any]] = None
    tool_type: Optional[str] = None
    metadata: Optional[Dict[str, Any]] = None

    def to_tool_call(self) -> ToolCall:
        return ToolCall(
            execution_id=self.execution_id,
            tool_name=self.tool_name,
            tool_type=self.tool_type,
            tool_input=self.tool_input,
            metadata=self.metadata,
            status="running",
            created_at=utc_now(),
        )

    def validate(self) -> tuple[bool, Optional[str]]:
        if not self.execution_id:
            return False, "执行ID不能为空"
        if not self.tool_name:
            return False, "工具名称不能为空"
        return True, None


@dataclass
class ToolCallUpdate:
    tool_output: Optional[Dict[str, Any]] = None
    status: Optional[ToolCallStatus] = None
    error_message: Optional[str] = None
    execution_time_ms: Optional[int] = None
    completed_at: Optional[datetime] = None
    metadata: Optional[Dict[str, Any]] = None

    def to_dict(self) -> dict:
        data = {}
        if self.tool_output is not None:
            data["tool_output"] = json.dumps(self.tool_output, ensure_ascii=False)
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


@dataclass
class ToolCallSummary:
    call_id: str
    tool_name: str
    status: ToolCallStatus
    execution_time_ms: Optional[int]
    error_message: Optional[str] = None

    def to_dict(self) -> dict:
        return {
            "call_id": self.call_id,
            "tool_name": self.tool_name,
            "status": self.status,
            "execution_time_ms": self.execution_time_ms,
            "error_message": self.error_message,
        }

    @classmethod
    def from_tool_call(cls, tool_call: ToolCall) -> "ToolCallSummary":
        return cls(
            call_id=tool_call.call_id,
            tool_name=tool_call.tool_name,
            status=tool_call.status,
            execution_time_ms=tool_call.execution_time_ms,
            error_message=tool_call.error_message,
        )
