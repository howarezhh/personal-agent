# -*- coding: utf-8 -*-
"""流式输出数据结构定义。

本模块用于统一描述：
- 流式消息块 `StreamChunk`
- 流式进度 `StreamProgress`
- 流式会话 `StreamSession`

说明：
- 流式契约字段、类型与序列化规范统一以下沉到 `backend.contracts.sse` 为准；
- 本文件仅保留运行时 dataclass 与辅助行为方法。
"""

from dataclasses import dataclass, field
from datetime import datetime, timezone
import json
import uuid
from typing import Any, Dict, Optional

from backend.contracts.errors import ErrorCode
from backend.contracts.sse import ChunkType, normalize_stream_chunk_payload, parse_sse_timestamp
from backend.utils.error_utils import build_error_metadata, sanitize_error_message


@dataclass
class StreamChunk:
    """标准流式输出块。"""

    chunk_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    chunk_type: ChunkType = "content"
    content: Any = ""
    metadata: Optional[Dict[str, Any]] = None
    timestamp: Optional[datetime] = field(default_factory=lambda: datetime.now(timezone.utc))

    def to_dict(self) -> dict:
        """将分块转换为统一协议字典。"""
        return normalize_stream_chunk_payload(
            {
                "chunk_id": self.chunk_id,
                "chunk_type": self.chunk_type,
                "content": self.content,
                "metadata": self.metadata,
                "timestamp": self.timestamp,
            }
        )

    @classmethod
    def from_dict(cls, data: dict) -> "StreamChunk":
        """从字典恢复流式分块。"""
        if not isinstance(data, dict):
            raise TypeError("StreamChunk.from_dict expects a dict")

        normalized = normalize_stream_chunk_payload(data)
        return cls(
            chunk_id=normalized["chunk_id"],
            chunk_type=normalized["chunk_type"],
            content=normalized.get("content", ""),
            metadata=normalized.get("metadata"),
            timestamp=parse_sse_timestamp(normalized.get("timestamp")),
        )

    def to_sse_format(self) -> str:
        """转换为原始 SSE 文本格式。"""
        data_str = json.dumps(self.to_dict(), ensure_ascii=False)
        return f"data: {data_str}\n\n"

    @classmethod
    def create_thinking(cls, content: str, **metadata) -> "StreamChunk":
        """创建思考类分块。"""
        return cls(chunk_type="thinking", content=content, metadata=metadata if metadata else None)

    @classmethod
    def create_content(cls, content: str, **metadata) -> "StreamChunk":
        """创建正文内容分块。"""
        return cls(chunk_type="content", content=content, metadata=metadata if metadata else None)

    @classmethod
    def create_tool_call(cls, tool_name: str, tool_input: Dict[str, Any], **metadata) -> "StreamChunk":
        """创建工具调用分块。"""
        return cls(
            chunk_type="tool_call",
            content=f"调用工具: {tool_name}",
            metadata={
                "tool_name": tool_name,
                "tool_input": tool_input,
                **metadata,
            },
        )

    @classmethod
    def create_result(cls, content: Any, **metadata) -> "StreamChunk":
        """创建结果分块。"""
        return cls(chunk_type="result", content=content, metadata=metadata if metadata else None)

    @classmethod
    def create_done(cls, content: Any = None, **metadata) -> "StreamChunk":
        """创建结束分块。"""
        return cls(chunk_type="done", content=content, metadata=metadata if metadata else None)

    @classmethod
    def create_error(cls, error_message: str, **metadata) -> "StreamChunk":
        """创建错误分块。"""
        safe_metadata = build_error_metadata(
            error_code=metadata.get("error_code", ErrorCode.SYSTEM_INTERNAL_ERROR.value),
            error_type=metadata.get("error_type", "execution_error"),
            metadata=metadata,
        )
        return cls(
            chunk_type="error",
            content=sanitize_error_message(error_message, fallback="execution failed"),
            metadata=safe_metadata,
        )

    @classmethod
    def create_metadata(cls, metadata: Dict[str, Any]) -> "StreamChunk":
        """创建 metadata 分块。"""
        return cls(chunk_type="metadata", content="", metadata=metadata)

    def __repr__(self) -> str:
        """返回简短调试文本。"""
        content_text = str(self.content)
        preview = content_text[:50] + "..." if len(content_text) > 50 else content_text
        return f"StreamChunk(type='{self.chunk_type}', content='{preview}')"


@dataclass
class StreamProgress:
    """流式执行进度对象。"""

    total_chunks: int = 0
    completed_chunks: int = 0
    current_agent: Optional[str] = None
    current_step: Optional[str] = None
    progress_percentage: float = 0.0
    estimated_time_remaining_ms: Optional[int] = None

    def to_dict(self) -> dict:
        """转为字典。"""
        return {
            "total_chunks": self.total_chunks,
            "completed_chunks": self.completed_chunks,
            "current_agent": self.current_agent,
            "current_step": self.current_step,
            "progress_percentage": self.progress_percentage,
            "estimated_time_remaining_ms": self.estimated_time_remaining_ms,
        }

    def update_progress(self, completed_chunks: int):
        """更新完成块数并重算百分比。"""
        self.completed_chunks = completed_chunks
        if self.total_chunks > 0:
            self.progress_percentage = (self.completed_chunks / self.total_chunks) * 100

    def to_stream_chunk(self) -> StreamChunk:
        """将进度对象包装成 metadata 分块。"""
        return StreamChunk.create_metadata(self.to_dict())


@dataclass
class StreamSession:
    """一次流式会话的状态对象。"""

    session_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    conversation_id: str = ""
    message_id: Optional[str] = None
    started_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    ended_at: Optional[datetime] = None
    total_chunks: int = 0
    is_active: bool = True

    def to_dict(self) -> dict:
        """转为字典，便于持久化和调试输出。"""
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
        """结束当前流式会话。"""
        self.ended_at = datetime.now(timezone.utc)
        self.is_active = False

    def get_duration_ms(self) -> int:
        """计算会话持续时间，单位毫秒。"""
        if self.ended_at:
            duration = self.ended_at - self.started_at
        else:
            duration = datetime.now(timezone.utc) - self.started_at
        return int(duration.total_seconds() * 1000)

    def __repr__(self) -> str:
        """返回简洁调试信息。"""
        return f"StreamSession(session_id='{self.session_id}', conversation_id='{self.conversation_id}', active={self.is_active})"
