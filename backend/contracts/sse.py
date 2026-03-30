from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timezone
from typing import Any, Literal, Mapping, Optional
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field


ChunkType = Literal["thinking", "content", "tool_call", "result", "done", "error", "metadata"]
SSEEventType = Literal["thinking", "content", "tool_call", "result", "done", "error"]

SSE_EVENT_TYPE_BY_CHUNK_TYPE: dict[str, SSEEventType] = {
    "thinking": "thinking",
    "content": "content",
    "tool_call": "tool_call",
    "result": "result",
    "done": "done",
    "error": "error",
    "metadata": "thinking",
}


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def normalize_sse_timestamp(value: Any) -> str:
    if isinstance(value, datetime):
        return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")
    if isinstance(value, str) and value:
        try:
            return datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone(timezone.utc).isoformat().replace("+00:00", "Z")
        except ValueError:
            return utc_now_iso()
    return utc_now_iso()


def parse_sse_timestamp(value: Any) -> Optional[datetime]:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value.astimezone(timezone.utc)
    if isinstance(value, str) and value:
        try:
            return datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone(timezone.utc)
        except ValueError:
            return None
    return None


def resolve_sse_event_type(chunk_type: Any) -> SSEEventType:
    return SSE_EVENT_TYPE_BY_CHUNK_TYPE.get(str(chunk_type or "content"), "content")


class SSEEvent(BaseModel):
    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "type": "result",
                "message": "plan generated",
                "content": {"plan_id": "plan_xxx"},
                "metadata": {
                    "stage": "planning",
                    "request_id": "req_xxx",
                    "conversation_id": "conv_xxx",
                    "message_id": "msg_xxx",
                    "execution_id": "exec_xxx",
                    "plan_id": "plan_xxx",
                    "step_id": None,
                },
                "timestamp": "2024-01-01T00:00:00Z",
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
    error_code: str | None = None
    citations: list[dict[str, Any]] | None = None


class StreamChunkSchema(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
        json_schema_extra={
            "example": {
                "chunk_id": "chunk_xxx",
                "type": "content",
                "chunk_type": "content",
                "content": "hello",
                "metadata": {"step": "generation"},
                "timestamp": "2024-01-01T00:00:00Z",
            }
        },
    )

    chunk_id: str = Field(default_factory=lambda: str(uuid4()))
    type: SSEEventType = "content"
    chunk_type: ChunkType = "content"
    content: Any = ""
    metadata: Optional[dict[str, Any]] = None
    timestamp: str = Field(default_factory=utc_now_iso)


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
    error_code: Optional[str] = None,
    citations: Optional[list[dict[str, Any]]] = None,
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
        error_code=error_code,
        citations=citations,
    ).model_dump()


def normalize_stream_chunk_payload(payload: Any) -> dict[str, Any]:
    working_payload = payload if isinstance(payload, Mapping) else {}
    chunk_type = working_payload.get("chunk_type") or working_payload.get("type") or "content"

    return StreamChunkSchema.model_validate(
        {
            "chunk_id": working_payload.get("chunk_id") or str(uuid4()),
            "type": resolve_sse_event_type(chunk_type),
            "chunk_type": chunk_type,
            "content": deepcopy(working_payload.get("content", "")),
            "metadata": deepcopy(working_payload.get("metadata")),
            "timestamp": normalize_sse_timestamp(working_payload.get("timestamp")),
        }
    ).model_dump()


__all__ = [
    "ChunkType",
    "SSEEventType",
    "SSEEvent",
    "StreamChunkSchema",
    "SSE_EVENT_TYPE_BY_CHUNK_TYPE",
    "utc_now_iso",
    "normalize_sse_timestamp",
    "parse_sse_timestamp",
    "resolve_sse_event_type",
    "build_sse_event",
    "normalize_stream_chunk_payload",
]
