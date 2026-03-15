
from datetime import datetime, timezone
from typing import Any, Literal, Optional

from pydantic import BaseModel, ConfigDict, Field


SSEEventType = Literal["thinking", "content", "tool_call", "result", "done", "error"]


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


class SSEEvent(BaseModel):
    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "type": "content",
                "message": "chunk generated",
                "content": "hello",
                "metadata": {},
                "timestamp": "2024-01-01T00:00:00+00:00",
                "request_id": "req_xxx",
                "conversation_id": "conv_xxx",
                "message_id": "msg_xxx",
                "execution_id": "exec_xxx",
            }
        }
    )

    type: SSEEventType
    message: str | None = None
    content: Any = None
    metadata: dict[str, Any] = Field(default_factory=dict)
    timestamp: str = Field(default_factory=utc_now_iso)
    request_id: str | None = None
    conversation_id: str | None = None
    message_id: str | None = None
    execution_id: str | None = None


def build_sse_event(
    event_type: SSEEventType,
    content: Any = None,
    *,
    message: Optional[str] = None,
    metadata: Optional[dict[str, Any]] = None,
    request_id: Optional[str] = None,
    conversation_id: Optional[str] = None,
    message_id: Optional[str] = None,
    execution_id: Optional[str] = None,
) -> dict[str, Any]:
    return SSEEvent(
        type=event_type,
        message=message,
        content=content,
        metadata=metadata or {},
        request_id=request_id,
        conversation_id=conversation_id,
        message_id=message_id,
        execution_id=execution_id,
    ).model_dump()
