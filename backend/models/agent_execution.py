"""
智能体执行记录数据模型
对应数据库表: agent_executions
"""

from dataclasses import dataclass, field
from typing import Optional, Dict, Any, Literal
from datetime import datetime
import uuid
import json


AgentType = Literal["router", "retrieval", "generation", "tool", "file_processor"]
ExecutionStatus = Literal["success", "failed", "partial", "running"]


@dataclass
class AgentExecution:
    """
    智能体执行记录数据模型

    对应数据库表: agent_executions
    存储每次智能体执行的详细记录
    """

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
        """
        转换为字典格式

        Returns:
            字典格式的执行记录数据
        """
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
        """
        从字典创建AgentExecution对象

        Args:
            data: 字典数据

        Returns:
            AgentExecution对象
        """
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
        """
        从数据库行创建AgentExecution对象

        Args:
            row: 数据库查询结果行
            columns: 列名列表

        Returns:
            AgentExecution对象
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

    def mark_success(self, output_data: Dict[str, Any], execution_time_ms: int):
        """
        标记执行成功

        Args:
            output_data: 输出数据
            execution_time_ms: 执行时间（毫秒）
        """
        self.status = "success"
        self.output_data = output_data
        self.execution_time_ms = execution_time_ms
        self.completed_at = datetime.utcnow()

    def mark_failed(self, error_message: str, execution_time_ms: int = None):
        """
        标记执行失败

        Args:
            error_message: 错误信息
            execution_time_ms: 执行时间（毫秒）
        """
        self.status = "failed"
        self.error_message = error_message
        if execution_time_ms is not None:
            self.execution_time_ms = execution_time_ms
        self.completed_at = datetime.utcnow()

    def __repr__(self) -> str:
        return f"AgentExecution(execution_id='{self.execution_id}', agent_name='{self.agent_name}', status='{self.status}')"


@dataclass
class AgentExecutionCreate:
    """
    创建智能体执行记录的数据模型
    """

    agent_name: str
    agent_type: AgentType
    conversation_id: Optional[str] = None  # 可为空，直接工具调用时为None
    input_data: Optional[Dict[str, Any]] = None
    message_id: Optional[str] = None
    metadata: Optional[Dict[str, Any]] = None

    def to_agent_execution(self) -> AgentExecution:
        """
        转换为AgentExecution对象

        Returns:
            AgentExecution对象
        """
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
    """
    更新智能体执行记录的数据模型
    """

    output_data: Optional[Dict[str, Any]] = None
    status: Optional[ExecutionStatus] = None
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
