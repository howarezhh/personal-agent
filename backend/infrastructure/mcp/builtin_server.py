from __future__ import annotations

import asyncio
import json
import logging
import sys
from importlib import import_module
from typing import Any

from backend.contracts.tools import ToolCapability
from backend.contracts.tools.tool_errors import ToolErrorCode, ToolErrorType
from backend.infrastructure.mcp.protocol import MCP_PROTOCOL_VERSION, MCP_SERVER_NAME, MCP_SERVER_VERSION
from backend.tools.base_tool import BaseTool
from backend.tools.tool_config import get_tool_config


logger = logging.getLogger(__name__)
MCP_TOOL_META_NAMESPACE = "personal-agent"


class MCPBuiltinServerError(Exception):
    """builtin MCP server 协议层错误。"""

    def __init__(self, code: int, message: str, data: dict[str, Any] | None = None):
        super().__init__(message)
        self.code = code
        self.message = message
        self.data = data or {}


def _load_tool_class(class_path: str) -> type[BaseTool]:
    module_path, class_name = class_path.rsplit(".", 1)
    module = import_module(module_path)
    tool_class = getattr(module, class_name)
    if not issubclass(tool_class, BaseTool):
        raise TypeError(f"{class_path} is not a BaseTool subclass")
    return tool_class


def _load_tools() -> dict[str, BaseTool]:
    tool_config = get_tool_config()
    tools: dict[str, BaseTool] = {}
    for tool_name, entry in tool_config.get_registry().items():
        if not isinstance(entry, dict) or not entry.get("enabled", True):
            continue
        if entry.get("transport_protocol") != "mcp":
            continue
        if entry.get("mcp_server") != "builtin":
            continue
        class_path = tool_config.get_tool_class_path(tool_name)
        if not class_path:
            continue
        tool_class = _load_tool_class(class_path)
        tools[tool_name] = tool_class()
    return tools


async def _initialize_tools(tools: dict[str, BaseTool]) -> None:
    for tool in tools.values():
        initialize_method = getattr(tool, "initialize", None)
        if callable(initialize_method):
            result = initialize_method()
            if asyncio.iscoroutine(result):
                await result


def _build_protocol_error_payload(error: MCPBuiltinServerError) -> dict[str, Any]:
    payload: dict[str, Any] = {"code": error.code, "message": error.message}
    if error.data:
        payload["data"] = error.data
    return payload


async def _dispatch(method: str, params: dict[str, Any], tools: dict[str, BaseTool]) -> dict[str, Any] | None:
    if method == "initialize":
        await _initialize_tools(tools)
        return {
            "protocolVersion": MCP_PROTOCOL_VERSION,
            "capabilities": {"tools": {"listChanged": False}},
            "serverInfo": {"name": MCP_SERVER_NAME, "version": MCP_SERVER_VERSION},
        }

    if method == "notifications/initialized":
        return None

    if method == "tools/list":
        tool_config = get_tool_config()
        tool_items = []
        for tool_name, tool in tools.items():
            descriptor = tool.get_descriptor()
            definition = tool.get_definition()
            capabilities = [ToolCapability.INVOKE.value, ToolCapability.MCP_PROXY.value]
            if descriptor.supports(ToolCapability.STREAM):
                capabilities.append(ToolCapability.STREAM.value)
            tool_runtime_meta = {
                "category": definition.category,
                "version": getattr(definition, "version", "1.0.0"),
                "timeout": definition.timeout,
                "capabilities": capabilities,
                "transport_protocol": "mcp",
                "tool_origin": tool_config.get_tool_origin(tool_name) or "local",
                "mcp_server": tool_config.get_registry_entry(tool_name).get("mcp_server") or "builtin",
            }
            tool_items.append(
                {
                    "name": tool_name,
                    "description": definition.description,
                    "inputSchema": definition.input_schema,
                    "outputSchema": definition.output_schema,
                    "_meta": {
                        MCP_TOOL_META_NAMESPACE: tool_runtime_meta,
                    },
                }
            )
        return {"tools": tool_items}

    if method == "tools/call":
        tool_name = params.get("name")
        arguments = params.get("arguments") if isinstance(params.get("arguments"), dict) else {}
        if not tool_name or not isinstance(tool_name, str):
            raise MCPBuiltinServerError(-32602, "Invalid params: name is required")
        if tool_name not in tools:
            return {
                "isError": True,
                "content": [{"type": "text", "text": f"Unknown tool: {tool_name}"}],
                "structuredContent": {
                    "success": False,
                    "data": None,
                    "error": f"Unknown tool: {tool_name}",
                    "error_code": ToolErrorCode.TOOL_EXECUTION_ERROR.value,
                    "error_type": ToolErrorType.EXECUTION_ERROR.value,
                    "metadata": {"tool_name": tool_name},
                },
            }
        result = await tools[tool_name].safe_execute(**arguments)
        return {
            "isError": not result.get("success", False),
            "content": [{"type": "text", "text": json.dumps(result, ensure_ascii=False)}],
            "structuredContent": result,
        }

    raise MCPBuiltinServerError(-32601, f"Method not found: {method}")


def _write_message(message: dict[str, Any]) -> None:
    sys.stdout.write(json.dumps(message, ensure_ascii=False) + "\n")
    sys.stdout.flush()


async def _close_tools(tools: dict[str, BaseTool]) -> None:
    for tool in tools.values():
        close_method = getattr(tool, "close", None)
        if callable(close_method):
            close_result = close_method()
            if asyncio.iscoroutine(close_result):
                await close_result


def main() -> None:
    logging.disable(logging.CRITICAL)
    logging.basicConfig(level=logging.CRITICAL)
    tools = _load_tools()
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    try:
        for raw_line in sys.stdin:
            line = raw_line.strip()
            if not line:
                continue
            message: dict[str, Any] = {}
            try:
                message = json.loads(line)
                method = message.get("method")
                params = message.get("params") if isinstance(message.get("params"), dict) else {}
                request_id = message.get("id")
                result = loop.run_until_complete(_dispatch(method, params, tools))
                if request_id is None or result is None:
                    continue
                _write_message({"jsonrpc": "2.0", "id": request_id, "result": result})
            except MCPBuiltinServerError as error:
                request_id = message.get("id")
                if request_id is not None:
                    _write_message({"jsonrpc": "2.0", "id": request_id, "error": _build_protocol_error_payload(error)})
            except Exception:
                request_id = message.get("id")
                if request_id is not None:
                    _write_message(
                        {
                            "jsonrpc": "2.0",
                            "id": request_id,
                            "error": {"code": -32000, "message": "MCP builtin server internal error"},
                        }
                    )
                else:
                    logger.error("Unhandled MCP server error", exc_info=True)
    finally:
        loop.run_until_complete(_close_tools(tools))
        loop.close()


if __name__ == "__main__":
    main()
