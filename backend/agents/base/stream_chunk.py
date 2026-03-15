
from dataclasses import dataclass, field
from typing import Optional, Dict, Any, Literal
from datetime import datetime, timezone
import uuid


ChunkType = Literal["thinking", "content", "tool_call", "result", "error", "metadata"]


@dataclass
class StreamChunk:
    chunk_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    chunk_type: ChunkType = "content"
    content: str = ""
    metadata: Optional[Dict[str, Any]] = None
    timestamp: Optional[datetime] = field(default_factory=lambda: datetime.now(timezone.utc))

    def to_dict(self) -> dict:
        return {
            "chunk_id": self.chunk_id,
            "chunk_type": self.chunk_type,
            "content": self.content,
            "metadata": self.metadata,
            "timestamp": self.timestamp.isoformat() if self.timestamp else None,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "StreamChunk":
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
        import json
        data_str = json.dumps(self.to_dict(), ensure_ascii=False)
        return f"data: {data_str}\n\n"

    @classmethod
    def create_thinking(cls, content: str, **metadata) -> "StreamChunk":
        return cls(
            chunk_type="thinking",
            content=content,
            metadata=metadata if metadata else None,
        )

    @classmethod
    def create_content(cls, content: str, **metadata) -> "StreamChunk":
        return cls(
            chunk_type="content",
            content=content,
            metadata=metadata if metadata else None,
        )

    @classmethod
    def create_tool_call(cls, tool_name: str, tool_input: Dict[str, Any], **metadata) -> "StreamChunk":
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
        return cls(
            chunk_type="result",
            content=content,
            metadata=metadata if metadata else None,
        )

    @classmethod
    def create_error(cls, error_message: str, **metadata) -> "StreamChunk":
        return cls(
            chunk_type="error",
            content=error_message,
            metadata=metadata if metadata else None,
        )

    @classmethod
    def create_metadata(cls, metadata: Dict[str, Any]) -> "StreamChunk":
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
    total_chunks: int = 0
    completed_chunks: int = 0
    current_agent: Optional[str] = None
    current_step: Optional[str] = None
    progress_percentage: float = 0.0
    estimated_time_remaining_ms: Optional[int] = None

    def to_dict(self) -> dict:
        return {
            "total_chunks": self.total_chunks,
            "completed_chunks": self.completed_chunks,
            "current_agent": self.current_agent,
            "current_step": self.current_step,
            "progress_percentage": self.progress_percentage,
            "estimated_time_remaining_ms": self.estimated_time_remaining_ms,
        }

    def update_progress(self, completed_chunks: int):
        self.completed_chunks = completed_chunks
        if self.total_chunks > 0:
            self.progress_percentage = (self.completed_chunks / self.total_chunks) * 100

    def to_stream_chunk(self) -> StreamChunk:
        return StreamChunk.create_metadata(self.to_dict())


@dataclass
class StreamSession:
    session_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    conversation_id: str = ""
    message_id: Optional[str] = None
    started_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    ended_at: Optional[datetime] = None
    total_chunks: int = 0
    is_active: bool = True

    def to_dict(self) -> dict:
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
        self.ended_at = datetime.now(timezone.utc)
        self.is_active = False

    def get_duration_ms(self) -> int:
        if self.ended_at:
            duration = self.ended_at - self.started_at
        else:
            duration = datetime.now(timezone.utc) - self.started_at
        return int(duration.total_seconds() * 1000)

    def __repr__(self) -> str:
        return f"StreamSession(session_id='{self.session_id}', conversation_id='{self.conversation_id}', active={self.is_active})"
