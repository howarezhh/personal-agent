from __future__ import annotations

import asyncio
import json
import logging
import sys
from importlib import import_module
from typing import Any, Dict

from backend.tools.base_tool import BaseTool
from backend.tools.tool_config import get_tool_config


logger = logging.getLogger(__name__)
SERVER_NAME = "personal-agent-builtin-tools"
SERVER_VERSION = "1.0.0"
PROTOCOL_VERSION = "2025-11-25"


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
        class_path = tool_config.get_tool_class_path(tool_name)
        if not class_path:
            continue
        tool_class = _load_tool_class(class_path)
        tool_instance = tool_class()
        tools[tool_name] = tool_instance
    return tools


async def _dispatch(method: str, params: Dict[str, Any], tools: dict[str, BaseTool]) -> Dict[str, Any] | None:
    if method == "initialize":
        return {
            "protocolVersion": PROTOCOL_VERSION,
            "capabilities": {"tools": {"listChanged": False}},
            "serverInfo": {"name": SERVER_NAME, "version": SERVER_VERSION},
        }

    if method == "notifications/initialized":
        return None

    if method == "tools/list":
        tool_config = get_tool_config()
        return {
            "tools": [
                {
                    "name": tool_name,
                    "description": tool.get_definition().description,
                    "inputSchema": tool.get_definition().input_schema,
                    "annotations": {
                        "category": tool.get_definition().category,
                        "timeout": tool.get_definition().timeout,
                        "transport_protocol": "mcp",
                        "tool_origin": tool_config.get_tool_origin(tool_name) or "local",
                        "mcp_server": tool_config.get_registry_entry(tool_name).get("mcp_server") or "builtin",
                    },
                }
                for tool_name, tool in tools.items()
            ]
        }

    if method == "tools/call":
        tool_name = params.get("name")
        arguments = params.get("arguments") if isinstance(params.get("arguments"), dict) else {}
        if tool_name not in tools:
            return {
                "isError": True,
                "content": [{"type": "text", "text": f"Unknown tool: {tool_name}"}],
            }
        result = await tools[tool_name].safe_execute(**arguments)
        return {
            "isError": not result.get("success", False),
            "content": [{"type": "text", "text": json.dumps(result, ensure_ascii=False)}],
            "structuredContent": result,
        }

    raise ValueError(f"Method not found: {method}")


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
            try:
                message = json.loads(line)
                method = message.get("method")
                params = message.get("params") if isinstance(message.get("params"), dict) else {}
                request_id = message.get("id")
                result = loop.run_until_complete(_dispatch(method, params, tools))
                if request_id is None or result is None:
                    continue
                _write_message({"jsonrpc": "2.0", "id": request_id, "result": result})
            except Exception as error:
                request_id = None
                try:
                    request_id = message.get("id")  # type: ignore[name-defined]
                except Exception:
                    pass
                if request_id is not None:
                    _write_message(
                        {
                            "jsonrpc": "2.0",
                            "id": request_id,
                            "error": {"code": -32601, "message": str(error)},
                        }
                    )
                else:
                    logger.error("Unhandled MCP server error: %s", error, exc_info=True)
    finally:
        loop.run_until_complete(_close_tools(tools))
        loop.close()


if __name__ == "__main__":
    main()
