"""
流式输出数据块结构
定义智能体流式输出时的数据块格式
"""

from dataclasses import dataclass, field
from typing import Optional, Dict, Any, Literal
from datetime import datetime, timezone
import uuid


ChunkType = Literal["thinking", "content", "tool_call", "result", "error", "metadata"]


@dataclass
class StreamChunk:
    """
    流式输出数据块

    用于智能体流式输出时的数据传输
    """

    chunk_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    chunk_type: ChunkType = "content"
    content: str = ""
    metadata: Optional[Dict[str, Any]] = None
    timestamp: Optional[datetime] = field(default_factory=lambda: datetime.now(timezone.utc))

    def to_dict(self) -> dict:
        """
        转换为字典格式

        Returns:
            字典格式的数据块
        """
        return {
            "chunk_id": self.chunk_id,
            "chunk_type": self.chunk_type,
            "content": self.content,
            "metadata": self.metadata,
            "timestamp": self.timestamp.isoformat() if self.timestamp else None,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "StreamChunk":
        """
        从字典创建StreamChunk对象

        Args:
            data: 字典数据

        Returns:
            StreamChunk对象
        """
        # 处理datetime字段
        timestamp = data.get("timestamp")
        if isinstance(timestamp, str):
            timestamp = datetime.fromisoformat(timestamp.replace("Z", "+00:00"))

        return cls(
            chunk_id=data.get("chunk_id", str(uuid.uuid4())),
            chunk_type=data.get("chunk_type", "content"),
            content=data.get("content", ""),
            metadata=data.get("metadata"),
            timestamp=timestamp,
        )

    def to_sse_format(self) -> str:
        """
        转换为SSE (Server-Sent Events) 格式

        Returns:
            SSE格式的字符串
        """
        import json
        data_str = json.dumps(self.to_dict(), ensure_ascii=False)
        return f"data: {data_str}\n\n"

    @classmethod
    def create_thinking(cls, content: str, **metadata) -> "StreamChunk":
        """
        创建思考过程数据块

        Args:
            content: 思考内容
            **metadata: 元数据

        Returns:
            StreamChunk对象
        """
        return cls(
            chunk_type="thinking",
            content=content,
            metadata=metadata if metadata else None,
        )

    @classmethod
    def create_content(cls, content: str, **metadata) -> "StreamChunk":
        """
        创建内容数据块

        Args:
            content: 内容
            **metadata: 元数据

        Returns:
            StreamChunk对象
        """
        return cls(
            chunk_type="content",
            content=content,
            metadata=metadata if metadata else None,
        )

    @classmethod
    def create_tool_call(cls, tool_name: str, tool_input: Dict[str, Any], **metadata) -> "StreamChunk":
        """
        创建工具调用数据块

        Args:
            tool_name: 工具名称
            tool_input: 工具输入
            **metadata: 元数据

        Returns:
            StreamChunk对象
        """
        return cls(
            chunk_type="tool_call",
            content=f"调用工具: {tool_name}",
            metadata={
                "tool_name": tool_name,
                "tool_input": tool_input,
                **metadata
            },
        )

    @classmethod
    def create_result(cls, content: str, **metadata) -> "StreamChunk":
        """
        创建结果数据块

        Args:
            content: 结果内容
            **metadata: 元数据

        Returns:
            StreamChunk对象
        """
        return cls(
            chunk_type="result",
            content=content,
            metadata=metadata if metadata else None,
        )

    @classmethod
    def create_error(cls, error_message: str, **metadata) -> "StreamChunk":
        """
        创建错误数据块

        Args:
            error_message: 错误信息
            **metadata: 元数据

        Returns:
            StreamChunk对象
        """
        return cls(
            chunk_type="error",
            content=error_message,
            metadata=metadata if metadata else None,
        )

    @classmethod
    def create_metadata(cls, metadata: Dict[str, Any]) -> "StreamChunk":
        """
        创建元数据块

        Args:
            metadata: 元数据

        Returns:
            StreamChunk对象
        """
        return cls(
            chunk_type="metadata",
            content="",
            metadata=metadata,
        )

    def __repr__(self) -> str:
        content_text = str(self.content)
        preview = content_text[:50] + "..." if len(content_text) > 50 else content_text
        return f"StreamChunk(type='{self.chunk_type}', content='{preview}')"


@dataclass
class StreamProgress:
    """
    流式输出进度信息

    用于跟踪流式输出的进度
    """

    total_chunks: int = 0
    completed_chunks: int = 0
    current_agent: Optional[str] = None
    current_step: Optional[str] = None
    progress_percentage: float = 0.0
    estimated_time_remaining_ms: Optional[int] = None

    def to_dict(self) -> dict:
        """
        转换为字典格式

        Returns:
            字典格式的进度信息
        """
        return {
            "total_chunks": self.total_chunks,
            "completed_chunks": self.completed_chunks,
            "current_agent": self.current_agent,
            "current_step": self.current_step,
            "progress_percentage": self.progress_percentage,
            "estimated_time_remaining_ms": self.estimated_time_remaining_ms,
        }

    def update_progress(self, completed_chunks: int):
        """
        更新进度

        Args:
            completed_chunks: 已完成的数据块数量
        """
        self.completed_chunks = completed_chunks
        if self.total_chunks > 0:
            self.progress_percentage = (self.completed_chunks / self.total_chunks) * 100

    def to_stream_chunk(self) -> StreamChunk:
        """
        转换为StreamChunk对象

        Returns:
            StreamChunk对象
        """
        return StreamChunk.create_metadata(self.to_dict())


@dataclass
class StreamSession:
    """
    流式输出会话

    用于管理一次完整的流式输出过程
    """

    session_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    conversation_id: str = ""
    message_id: Optional[str] = None
    started_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    ended_at: Optional[datetime] = None
    total_chunks: int = 0
    is_active: bool = True

    def to_dict(self) -> dict:
        """
        转换为字典格式

        Returns:
            字典格式的会话信息
        """
        return {
            "session_id": self.session_id,
            "conversation_id": self.conversation_id,
            "message_id": self.message_id,
            "started_at": self.started_at.isoformat() if self.started_at else None,
            "ended_at": self.ended_at.isoformat() if self.ended_at else None,
            "total_chunks": self.total_chunks,
            "is_active": self.is_active,
        }

    def end_session(self):
        """
        结束会话
        """
        self.ended_at = datetime.now(timezone.utc)
        self.is_active = False

    def get_duration_ms(self) -> int:
        """
        获取会话持续时间（毫秒）

        Returns:
            持续时间（毫秒）
        """
        if self.ended_at:
            duration = self.ended_at - self.started_at
        else:
            duration = datetime.now(timezone.utc) - self.started_at
        return int(duration.total_seconds() * 1000)

    def __repr__(self) -> str:
        return f"StreamSession(session_id='{self.session_id}', conversation_id='{self.conversation_id}', active={self.is_active})"
