from __future__ import annotations

from copy import deepcopy
from typing import Any, Optional

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from backend.contracts.sse import utc_now_iso
from backend.contracts.tools.tool_enums import (
    ToolCapability,
    ToolLifecycleStatus,
    ToolOrigin,
    ToolStreamEventType,
    ToolTransportProtocol,
)
from backend.contracts.tools.tool_errors import ToolErrorCode


class ToolError(BaseModel):
    """统一 Tool 错误契约。"""

    model_config = ConfigDict(extra="forbid")

    message: str = Field(..., description="错误消息")
    error_code: str = Field(..., description="稳定错误码")
    error_type: str = Field(..., description="错误类型")
    metadata: dict[str, Any] = Field(default_factory=dict, description="扩展元数据")


class ToolResult(BaseModel):
    """统一 Tool 调用结果契约。"""

    model_config = ConfigDict(extra="allow")

    success: bool = Field(..., description="是否成功")
    data: Any = Field(default=None, description="成功结果数据")
    error: Optional[str] = Field(default=None, description="失败消息")
    error_code: Optional[str] = Field(default=None, description="稳定错误码")
    error_type: Optional[str] = Field(default=None, description="错误类型")
    metadata: dict[str, Any] = Field(default_factory=dict, description="扩展元数据")

    @model_validator(mode="after")
    def _validate_failure_contract(self) -> "ToolResult":
        if not self.success:
            if not self.error:
                raise ValueError("ToolResult 失败时必须包含 error")
            if not self.error_code:
                raise ValueError("ToolResult 失败时必须包含 error_code")
            if not self.error_type:
                raise ValueError("ToolResult 失败时必须包含 error_type")
        return self

    @classmethod
    def success_result(cls, data: Any = None, metadata: Optional[dict[str, Any]] = None) -> "ToolResult":
        return cls(success=True, data=data, error=None, error_code=None, error_type=None, metadata=metadata or {})

    @classmethod
    def failure_result(
        cls,
        *,
        error: str,
        error_code: str,
        error_type: str,
        data: Any = None,
        metadata: Optional[dict[str, Any]] = None,
    ) -> "ToolResult":
        return cls(
            success=False,
            data=data,
            error=error,
            error_code=error_code,
            error_type=error_type,
            metadata=metadata or {},
        )

    @classmethod
    def from_mapping(cls, payload: Any) -> "ToolResult":
        if isinstance(payload, ToolResult):
            return payload
        if not isinstance(payload, dict):
            return cls.success_result(data=payload)
        return cls.model_validate(payload)

    def to_dict(self) -> dict[str, Any]:
        return self.model_dump()


class ToolCallContext(BaseModel):
    """统一 Tool 调用上下文契约。"""

    model_config = ConfigDict(extra="allow")

    request_id: Optional[str] = None
    user_id: Optional[str] = None
    conversation_id: Optional[str] = None
    message_id: Optional[str] = None
    execution_id: Optional[str] = None
    tool_call_id: Optional[str] = None
    tool_name: Optional[str] = None
    transport_protocol: Optional[str] = None
    mcp_server: Optional[str] = None
    metadata: dict[str, Any] = Field(default_factory=dict)

    def to_observability_metadata(self) -> dict[str, Any]:
        return {
            "request_id": self.request_id,
            "user_id": self.user_id,
            "conversation_id": self.conversation_id,
            "message_id": self.message_id,
            "execution_id": self.execution_id,
            "tool_call_id": self.tool_call_id,
            "tool_name": self.tool_name,
            "transport_protocol": self.transport_protocol,
            "mcp_server": self.mcp_server,
            **deepcopy(self.metadata),
        }


class ToolCallRequest(BaseModel):
    """统一 Tool 调用请求契约。"""

    model_config = ConfigDict(extra="forbid")

    tool_name: str
    payload: dict[str, Any] = Field(default_factory=dict)
    context: ToolCallContext = Field(default_factory=ToolCallContext)


class ToolStreamEvent(BaseModel):
    """统一 Tool 流式事件契约。"""

    model_config = ConfigDict(extra="allow")

    event_type: str = Field(..., description="流式事件类型")
    content: Any = Field(default=None, description="增量内容")
    data: Any = Field(default=None, description="结构化数据")
    error: Optional[str] = Field(default=None, description="错误消息")
    error_code: Optional[str] = Field(default=None, description="稳定错误码")
    metadata: dict[str, Any] = Field(default_factory=dict, description="扩展元数据")
    timestamp: str = Field(default_factory=utc_now_iso, description="事件时间")

    @field_validator("event_type")
    @classmethod
    def _normalize_event_type(cls, value: str) -> str:
        return str(value)

    @model_validator(mode="after")
    def _validate_error_contract(self) -> "ToolStreamEvent":
        if self.event_type == ToolStreamEventType.ERROR.value and not self.error_code:
            raise ValueError("ToolStreamEvent 错误事件必须包含 error_code")
        return self

    @classmethod
    def from_legacy_event(cls, payload: dict[str, Any]) -> "ToolStreamEvent":
        event_type = str(payload.get("event_type") or payload.get("type") or ToolStreamEventType.CONTENT.value)
        event_error_code = payload.get("error_code")
        if event_type == ToolStreamEventType.ERROR.value and not event_error_code:
            event_error_code = ToolErrorCode.TOOL_EXECUTION_ERROR.value
        return cls(
            event_type=event_type,
            content=payload.get("content"),
            data=payload.get("data"),
            error=payload.get("error"),
            error_code=event_error_code,
            metadata=deepcopy(payload.get("metadata") or {}),
            timestamp=str(payload.get("timestamp") or utc_now_iso()),
        )

    def to_legacy_event(self) -> dict[str, Any]:
        return {
            "type": self.event_type,
            "content": self.content,
            "data": self.data,
            "error": self.error,
            "error_code": self.error_code,
            "metadata": deepcopy(self.metadata),
            "timestamp": self.timestamp,
        }


class ToolDescriptor(BaseModel):
    """统一 Tool 描述契约。"""

    model_config = ConfigDict(extra="forbid")

    name: str
    description: str
    category: str = "general"
    version: str = "1.0.0"
    input_schema: dict[str, Any] = Field(default_factory=dict)
    output_schema: dict[str, Any] = Field(default_factory=dict)
    timeout: int = 30
    capabilities: list[str] = Field(default_factory=list)
    transport_protocol: str = ToolTransportProtocol.LOCAL_DIRECT.value
    tool_origin: str = ToolOrigin.LOCAL.value
    mcp_server: Optional[str] = None

    @field_validator("timeout")
    @classmethod
    def _validate_timeout(cls, value: int) -> int:
        if int(value) <= 0:
            raise ValueError("ToolDescriptor.timeout 必须大于 0")
        return int(value)

    @field_validator("capabilities")
    @classmethod
    def _normalize_capabilities(cls, value: list[str]) -> list[str]:
        normalized: list[str] = []
        for capability in value:
            normalized_capability = str(capability)
            ToolCapability(normalized_capability)
            if normalized_capability not in normalized:
                normalized.append(normalized_capability)
        return normalized

    @field_validator("transport_protocol")
    @classmethod
    def _validate_transport_protocol(cls, value: str) -> str:
        return ToolTransportProtocol(str(value)).value

    @field_validator("tool_origin")
    @classmethod
    def _validate_tool_origin(cls, value: str) -> str:
        return ToolOrigin(str(value)).value

    def supports(self, capability: ToolCapability | str) -> bool:
        return str(capability) in set(self.capabilities)

    def with_updates(self, **kwargs: Any) -> "ToolDescriptor":
        return self.model_copy(update=kwargs)

    def to_dict(self) -> dict[str, Any]:
        return self.model_dump()


__all__ = [
    "ToolCallContext",
    "ToolCallRequest",
    "ToolDescriptor",
    "ToolError",
    "ToolResult",
    "ToolStreamEvent",
    "ToolCapability",
    "ToolLifecycleStatus",
    "ToolOrigin",
    "ToolStreamEventType",
    "ToolTransportProtocol",
]
