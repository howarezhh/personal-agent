from __future__ import annotations

from enum import StrEnum


class ToolCapability(StrEnum):
    """Tool 平台一级能力枚举。"""

    INVOKE = "invoke"
    STREAM = "stream"
    BATCH = "batch"
    MCP_PROXY = "mcp_proxy"
    LOCAL_DIRECT = "local_direct"


class ToolTransportProtocol(StrEnum):
    """Tool 运行协议枚举。"""

    MCP = "mcp"
    LOCAL_DIRECT = "local_direct"


class ToolOrigin(StrEnum):
    """Tool 来源枚举。"""

    LOCAL = "local"
    EXTERNAL = "external"


class ToolLifecycleStatus(StrEnum):
    """Tool/MCP 统一生命周期状态枚举。"""

    DECLARED = "declared"
    REGISTERED = "registered"
    INITIALIZED = "initialized"
    AVAILABLE = "available"
    INVOKING = "invoking"
    STREAMING = "streaming"
    COMPLETED = "completed"
    FAILED = "failed"
    CLOSING = "closing"
    CLOSED = "closed"


class ToolStreamEventType(StrEnum):
    """统一 Tool 流式事件类型。"""

    START = "start"
    CONTENT = "content"
    RESULT = "result"
    DONE = "done"
    ERROR = "error"

