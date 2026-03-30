from __future__ import annotations

import json
from collections.abc import AsyncGenerator
from typing import Any, Optional

from backend.contracts.errors import ErrorCode, internal_server_error
from backend.contracts.tools import ToolCallContext, ToolCapability
from backend.tools import get_tool


class ContentGenerationApplicationService:
    def __init__(self, *, store, tool_provider=None):
        # `tool_provider`：允许测试或上层应用显式注入工具解析器。
        # 未注入时回退到统一注册入口，保持既有兼容行为。
        self.store = store
        self.tool_provider = tool_provider or get_tool

    async def save_generation(
        self,
        *,
        user_id: str,
        content_type: str,
        action: str,
        input_params: dict,
        tool_name: str,
        conversation_id: Optional[str] = None,
    ) -> tuple[str, int]:
        return await self.store.save_generation(
            user_id=user_id,
            content_type=content_type,
            action=action,
            input_params=input_params,
            tool_name=tool_name,
            conversation_id=conversation_id,
        )

    async def update_generation_result(
        self,
        *,
        generation_id: str,
        start_time_ms: int,
        result: dict,
    ) -> None:
        await self.store.update_generation_result(
            generation_id=generation_id,
            start_time_ms=start_time_ms,
            result=result,
        )

    def _require_tool(self, tool_name: str):
        tool = self.tool_provider(tool_name)
        if tool is None:
            raise internal_server_error(
                f"Content generation tool is unavailable: {tool_name}",
                error_code=ErrorCode.CONTENT_TOOL_UNAVAILABLE,
                error="ContentToolUnavailable",
            )
        return tool

    @staticmethod
    def _extract_result_preview(data: Optional[dict[str, Any]]) -> str:
        if not data:
            return ""

        for key in ("content", "optimized_content", "check_result", "continued_content"):
            value = data.get(key)
            if isinstance(value, str) and value:
                return value

        for key in ("outline", "character", "worldview", "storyboard"):
            value = data.get(key)
            if isinstance(value, dict):
                for nested_key in ("raw_outline", "raw_character", "raw_worldview", "raw_storyboard"):
                    nested_value = value.get(nested_key)
                    if isinstance(nested_value, str) and nested_value:
                        return nested_value

        return json.dumps(data, ensure_ascii=False, indent=2)

    async def execute_generation_tool(self, *, tool_name: str, **tool_params) -> dict[str, Any]:
        tool = self._require_tool(tool_name)
        return await tool.safe_execute(**tool_params)

    async def execute_generation_stream(self, *, tool_name: str, **tool_params) -> AsyncGenerator[dict[str, Any], None]:
        """统一读取能力声明并走适配器流式接口。"""

        tool = self._require_tool(tool_name)
        descriptor = tool.get_descriptor()
        if not descriptor.supports(ToolCapability.STREAM):
            yield {
                "type": "error",
                "error": f"Tool {tool_name} does not support stream",
                "error_code": ErrorCode.CONTENT_TOOL_UNAVAILABLE.value,
            }
            return

        context = ToolCallContext(
            tool_name=tool_name,
            transport_protocol=tool.get_transport_protocol(),
            mcp_server=tool.get_mcp_server(),
        )
        async for event in tool.invoke_stream(tool_params, context=context):
            yield event.to_legacy_event()
