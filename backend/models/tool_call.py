"""
工具调用数据模型
对应数据库表: tool_calls
"""

from dataclasses import dataclass, field
from typing import Optional, Dict, Any, Literal
from datetime import datetime
import uuid
import json


ToolCallStatus = Literal["success", "failed", "timeout", "running"]


@dataclass
class ToolCall:
    """
    工具调用数据模型

    对应数据库表: tool_calls
    存储工具调用的详细记录
    """

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
        """
        转换为字典格式

        Returns:
            字典格式的工具调用数据
        """
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
        """
        从字典创建ToolCall对象

        Args:
            data: 字典数据

        Returns:
            ToolCall对象
        """
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
        """
        从数据库行创建ToolCall对象

        Args:
            row: 数据库查询结果行
            columns: 列名列表

        Returns:
            ToolCall对象
        """
        data = dict(zip(columns, row))
        return cls.from_dict(data)

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

    def mark_success(self, tool_output: Dict[str, Any], execution_time_ms: int):
        """
        标记调用成功

        Args:
            tool_output: 工具输出
            execution_time_ms: 执行时间（毫秒）
        """
        self.status = "success"
        self.tool_output = tool_output
        self.execution_time_ms = execution_time_ms
        self.completed_at = datetime.utcnow()

    def mark_failed(self, error_message: str, execution_time_ms: int = None):
        """
        标记调用失败

        Args:
            error_message: 错误信息
            execution_time_ms: 执行时间（毫秒）
        """
        self.status = "failed"
        self.error_message = error_message
        if execution_time_ms is not None:
            self.execution_time_ms = execution_time_ms
        self.completed_at = datetime.utcnow()

    def mark_timeout(self, execution_time_ms: int):
        """
        标记调用超时

        Args:
            execution_time_ms: 执行时间（毫秒）
        """
        self.status = "timeout"
        self.error_message = "Tool call timeout"
        self.execution_time_ms = execution_time_ms
        self.completed_at = datetime.utcnow()

    def __repr__(self) -> str:
        return f"ToolCall(call_id='{self.call_id}', tool_name='{self.tool_name}', status='{self.status}')"


@dataclass
class ToolCallCreate:
    """
    创建工具调用的数据模型
    """

    execution_id: str
    tool_name: str
    tool_input: Optional[Dict[str, Any]] = None
    tool_type: Optional[str] = None
    metadata: Optional[Dict[str, Any]] = None

    def to_tool_call(self) -> ToolCall:
        """
        转换为ToolCall对象

        Returns:
            ToolCall对象
        """
        return ToolCall(
            execution_id=self.execution_id,
            tool_name=self.tool_name,
            tool_type=self.tool_type,
            tool_input=self.tool_input,
            metadata=self.metadata,
            status="running",
            created_at=datetime.utcnow(),
        )

    def validate(self) -> tuple[bool, Optional[str]]:
        """
        验证工具调用数据

        Returns:
            (是否有效, 错误信息)
        """
        if not self.execution_id:
            return False, "执行ID不能为空"
        if not self.tool_name:
            return False, "工具名称不能为空"
        return True, None


@dataclass
class ToolCallUpdate:
    """
    更新工具调用的数据模型
    """

    tool_output: Optional[Dict[str, Any]] = None
    status: Optional[ToolCallStatus] = None
    error_message: Optional[str] = None
    execution_time_ms: Optional[int] = None
    completed_at: Optional[datetime] = None
    metadata: Optional[Dict[str, Any]] = None

    def to_dict(self) -> dict:
        """
        转换为字典格式（只包含非None的字段）

        Returns:
            字典格式的更新数据
        """
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
    """
    工具调用摘要数据模型（用于展示）
    """

    call_id: str
    tool_name: str
    status: ToolCallStatus
    execution_time_ms: Optional[int]
    error_message: Optional[str] = None

    def to_dict(self) -> dict:
        """
        转换为字典格式

        Returns:
            字典格式的工具调用摘要数据
        """
        return {
            "call_id": self.call_id,
            "tool_name": self.tool_name,
            "status": self.status,
            "execution_time_ms": self.execution_time_ms,
            "error_message": self.error_message,
        }

    @classmethod
    def from_tool_call(cls, tool_call: ToolCall) -> "ToolCallSummary":
        """
        从ToolCall对象创建ToolCallSummary对象

        Args:
            tool_call: ToolCall对象

        Returns:
            ToolCallSummary对象
        """
        return cls(
            call_id=tool_call.call_id,
            tool_name=tool_call.tool_name,
            status=tool_call.status,
            execution_time_ms=tool_call.execution_time_ms,
            error_message=tool_call.error_message,
        )
