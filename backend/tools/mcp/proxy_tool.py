from __future__ import annotations

import json
from copy import deepcopy
from typing import Any, Dict

from backend.tools.base_tool import BaseTool, ToolDefinition, ToolParameter
from backend.tools.mcp.server_manager import get_mcp_server_manager


def _build_parameters_from_schema(input_schema: dict[str, Any]) -> list[ToolParameter]:
    properties = input_schema.get("properties") if isinstance(input_schema, dict) else {}
    required = set(input_schema.get("required") or []) if isinstance(input_schema, dict) else set()
    parameters: list[ToolParameter] = []
    for name, schema in (properties or {}).items():
        schema = schema if isinstance(schema, dict) else {}
        parameters.append(
            ToolParameter(
                name=name,
                type=str(schema.get("type", "string")),
                description=str(schema.get("description", "")),
                required=name in required,
                default=schema.get("default"),
                enum=schema.get("enum"),
                minimum=schema.get("minimum"),
                maximum=schema.get("maximum"),
                min_length=schema.get("minLength"),
                max_length=schema.get("maxLength"),
                pattern=schema.get("pattern"),
                items=schema.get("items"),
                properties=schema.get("properties"),
                additional_properties=schema.get("additionalProperties"),
            )
        )
    return parameters


class MCPProxyTool(BaseTool):
    def __init__(
        self,
        *,
        server_name: str,
        server_config: dict[str, Any],
        tool_name: str,
        description: str,
        input_schema: dict[str, Any],
        category: str = "mcp",
        transport_protocol: str = "mcp",
        tool_origin: str = "local",
        timeout: int = 30,
    ):
        self._server_name = server_name
        self._server_config = deepcopy(server_config)
        self._tool_name = tool_name
        self._tool_description = description
        self._input_schema = input_schema or {"type": "object", "properties": {}}
        self._tool_category = category
        self._transport_protocol = transport_protocol
        self._tool_origin = tool_origin
        self._proxy_timeout = timeout
        super().__init__()

    def _create_definition(self) -> ToolDefinition:
        return ToolDefinition(
            name=self._tool_name,
            description=self._tool_description,
            parameters=_build_parameters_from_schema(self._input_schema),
            category=self._tool_category,
            version="1.0.0",
            timeout=self._proxy_timeout,
            strict_validation=not bool(self._input_schema.get("additionalProperties", True)),
        )

    async def execute(self, **kwargs) -> Dict[str, Any]:
        manager = get_mcp_server_manager()
        client = None
        try:
            client = await manager.connect(self._server_name, self._server_config, timeout=self._proxy_timeout)
            result = await client.call_tool(self._tool_name, kwargs)
        finally:
            await manager.disconnect(self._server_name)

        structured_content = result.get("structuredContent")
        if isinstance(structured_content, dict):
            metadata = structured_content.get("metadata") if isinstance(structured_content.get("metadata"), dict) else {}
            structured_content["metadata"] = {
                **metadata,
                "mcp_server": self._server_name,
                "tool_name": self._tool_name,
            }
            return structured_content

        content = result.get("content")
        text_payload = None
        if isinstance(content, list) and content:
            text_payload = next((item.get("text") for item in content if isinstance(item, dict) and item.get("type") == "text"), None)

        parsed_payload: Any = text_payload
        if isinstance(text_payload, str):
            try:
                parsed_payload = json.loads(text_payload)
            except json.JSONDecodeError:
                parsed_payload = text_payload

        is_error = bool(result.get("isError", False))
        return {
            "success": not is_error,
            "data": None if is_error else parsed_payload,
            "error": parsed_payload if is_error else None,
            "error_code": "TOOL_EXECUTION_ERROR" if is_error else None,
            "error_type": "execution_error" if is_error else None,
            "metadata": {
                "mcp_server": self._server_name,
                "tool_name": self._tool_name,
            },
        }

    def get_transport_protocol(self) -> str:
        return self._transport_protocol

    def get_tool_origin(self) -> str:
        return self._tool_origin

    def get_mcp_server(self) -> str:
        return self._server_name
