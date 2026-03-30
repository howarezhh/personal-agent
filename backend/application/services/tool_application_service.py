from __future__ import annotations

import re
import time
from uuid import uuid4
from typing import Any, Dict, Optional

from backend.contracts.tools import ToolCallContext, ToolResult
from backend.contracts.tools.tool_errors import ToolErrorCode, ToolErrorType
from backend.models.agent_execution import AgentExecutionCreate, AgentExecutionUpdate
from backend.models.tool_call import ToolCallCreate, ToolCallUpdate
from backend.utils.logger import get_logger
from backend.utils.time_utils import utc_now


class ToolAccessDeniedError(PermissionError):
    """Raised when the current caller cannot access a tool."""


class ToolNotAvailableError(LookupError):
    """Raised when a tool is unavailable, disabled, or not registered."""


_SENSITIVE_PATTERNS = (
    re.compile(r"(?i)\b(api[_-]?key|token|password|secret)\b\s*[:=]\s*([^\s,;]+)"),
    re.compile(r"(?i)\bbearer\s+[a-z0-9._\-]+"),
)


class ToolApplicationService:
    """Centralize tool visibility, querying, and audited execution."""

    def __init__(
        self,
        *,
        execution_repo,
        tool_call_repo,
        tool_registry,
        tool_resolver,
        tool_catalog_provider,
        tool_config,
    ):
        self.logger = get_logger(self.__class__.__name__)
        self.execution_repo = execution_repo
        self.tool_call_repo = tool_call_repo
        self.tool_registry = tool_registry
        self.tool_resolver = tool_resolver
        self.tool_catalog_provider = tool_catalog_provider
        self.tool_config = tool_config

    @staticmethod
    def _sanitize_text(value: Any, fallback: str = "") -> str:
        text = str(value or "")
        for pattern in _SENSITIVE_PATTERNS:
            text = pattern.sub("[REDACTED]", text)
        sanitized = text.strip()
        return sanitized or fallback

    def _summarize_payload(self, payload: Any) -> str:
        if payload is None:
            return "None"
        if isinstance(payload, dict):
            keys = list(payload.keys())
            return f"dict(keys={keys[:8]}{'...' if len(keys) > 8 else ''})"
        if isinstance(payload, list):
            return f"list(len={len(payload)})"
        text = self._sanitize_text(payload)
        return text[:120] + ("..." if len(text) > 120 else "")

    def is_tool_visible(self, tool_name: str, *, is_admin: bool) -> bool:
        if is_admin:
            return self.tool_config.is_tool_enabled(tool_name)
        return self.tool_config.is_tool_exposed_to_agent(tool_name)

    def ensure_tool_access(self, tool_name: str, *, is_admin: bool) -> Any:
        if not self.tool_config.is_tool_enabled(tool_name):
            raise ToolNotAvailableError(f"Tool is disabled: {tool_name}")

        tool = self.tool_resolver(tool_name)
        if tool is None:
            raise ToolNotAvailableError(f"Tool is not registered: {tool_name}")

        if not self.tool_config.is_tool_exposed_to_agent(tool_name) and not is_admin:
            raise ToolAccessDeniedError(f"Tool access denied: {tool_name}")

        return tool

    @staticmethod
    def _serialize_tool_parameter(parameter: Any) -> dict[str, Any]:
        return {
            "name": parameter.name,
            "type": parameter.type,
            "description": parameter.description,
            "required": parameter.required,
            "default": parameter.default,
            "enum": parameter.enum,
            "minimum": parameter.minimum,
            "maximum": parameter.maximum,
            "min_length": parameter.min_length,
            "max_length": parameter.max_length,
            "pattern": parameter.pattern,
            "items": parameter.items,
            "properties": parameter.properties,
            "additional_properties": parameter.additional_properties,
        }

    def _serialize_tool_info(self, tool_instance: Any) -> dict[str, Any]:
        definition = tool_instance.get_definition()
        descriptor = tool_instance.get_descriptor()
        return {
            "name": definition.name,
            "description": definition.description,
            "category": definition.category,
            "capabilities": list(descriptor.capabilities),
            "transport_protocol": tool_instance.get_transport_protocol(),
            "tool_origin": tool_instance.get_tool_origin(),
            "mcp_server": tool_instance.get_mcp_server(),
            "parameters": [self._serialize_tool_parameter(parameter) for parameter in definition.parameters],
            "timeout": definition.timeout,
        }

    def _get_visible_tools(self, *, is_admin: bool) -> dict[str, Any]:
        return {
            tool_name: tool_instance
            for tool_name, tool_instance in self.tool_catalog_provider().items()
            if self.is_tool_visible(tool_name, is_admin=is_admin)
        }

    def list_tools(self, *, is_admin: bool, category: Optional[str] = None) -> list[dict[str, Any]]:
        visible_tools = self._get_visible_tools(is_admin=is_admin)
        tools: list[dict[str, Any]] = []
        for tool_name in sorted(visible_tools):
            tool_info = self._serialize_tool_info(visible_tools[tool_name])
            if category and tool_info["category"] != category:
                continue
            tools.append(tool_info)
        return tools

    def list_tool_categories(self, *, is_admin: bool) -> list[dict[str, Any]]:
        categories: dict[str, dict[str, Any]] = {}
        for tool_info in self.list_tools(is_admin=is_admin):
            category = tool_info["category"]
            category_entry = categories.setdefault(category, {"category": category, "count": 0, "tools": []})
            category_entry["count"] += 1
            category_entry["tools"].append(tool_info["name"])
        return [categories[category] for category in sorted(categories)]

    def get_tool_detail(self, *, tool_name: str, is_admin: bool) -> dict[str, Any]:
        if not self.is_tool_visible(tool_name, is_admin=is_admin):
            raise ToolNotAvailableError(f"Tool is not visible: {tool_name}")

        tool_instance = self.tool_resolver(tool_name)
        if tool_instance is None or not self.tool_config.is_tool_enabled(tool_name):
            raise ToolNotAvailableError(f"Tool is not available: {tool_name}")

        return self._serialize_tool_info(tool_instance)

    async def execute_tool(
        self,
        *,
        tool_name: str,
        parameters: Dict[str, Any],
        user_id: str,
        is_admin: bool,
        conversation_id: Optional[str] = None,
        message_id: Optional[str] = None,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        tool = self.ensure_tool_access(tool_name, is_admin=is_admin)
        execution_repo = self.execution_repo
        tool_call_repo = self.tool_call_repo

        execution = execution_repo.create_execution(
            AgentExecutionCreate(
                conversation_id=conversation_id,
                message_id=message_id,
                agent_name=tool_name,
                agent_type="tool",
                input_data={"tool_name": tool_name, "params": parameters, "user_id": user_id},
                metadata=metadata or {},
            )
        )
        tool_call = tool_call_repo.create_tool_call(
            ToolCallCreate(
                execution_id=execution.execution_id,
                tool_name=tool_name,
                tool_type=tool.get_transport_protocol(),
                tool_input=parameters,
                metadata={
                    **(metadata or {}),
                    "tool_origin": tool.get_tool_origin(),
                    "mcp_server": tool.get_mcp_server(),
                },
            )
        )

        start_time = time.time()
        request_id = str((metadata or {}).get("request_id") or uuid4())
        context = ToolCallContext(
            request_id=request_id,
            user_id=user_id,
            conversation_id=conversation_id,
            message_id=message_id,
            execution_id=execution.execution_id,
            tool_call_id=tool_call.call_id,
            tool_name=tool_name,
            transport_protocol=tool.get_transport_protocol(),
            mcp_server=tool.get_mcp_server(),
            metadata={
                **(metadata or {}),
                "tool_origin": tool.get_tool_origin(),
            },
        )
        try:
            self.logger.info(
                "[TOOL-SVC] execute_start: request_id=%s tool_name=%s user_id=%s transport=%s mcp_server=%s payload=%s",
                request_id,
                tool_name,
                user_id,
                tool.get_transport_protocol(),
                tool.get_mcp_server(),
                self._summarize_payload(parameters),
            )
            result_model = await tool.invoke(parameters, context=context)
            result = result_model.to_dict() if isinstance(result_model, ToolResult) else ToolResult.from_mapping(result_model).to_dict()
        except Exception as error:
            result = {
                "success": False,
                "data": None,
                "error": self._sanitize_text(error, fallback="Tool execution failed"),
                "error_code": ToolErrorCode.TOOL_EXECUTION_ERROR.value,
                "error_type": ToolErrorType.EXECUTION_ERROR.value,
                "metadata": {
                    "tool_name": tool_name,
                    "request_id": request_id,
                    "transport_protocol": tool.get_transport_protocol(),
                    "mcp_server": tool.get_mcp_server(),
                },
            }

        execution_time_ms = int((time.time() - start_time) * 1000)
        result_metadata = result.get("metadata") if isinstance(result.get("metadata"), dict) else {}
        safe_error = self._sanitize_text(result.get("error"), fallback="Tool execution failed") if not result.get("success") else None
        status = "success" if result.get("success") else (
            "timeout" if result.get("error_code") == ToolErrorCode.TOOL_TIMEOUT.value else "failed"
        )

        tool_call_update = ToolCallUpdate(
            tool_output=result,
            status=status,
            error_message=safe_error,
            execution_time_ms=execution_time_ms,
            completed_at=utc_now(),
            metadata=result_metadata,
        )
        tool_call_repo.update_tool_call(tool_call.call_id, tool_call_update)

        execution_update = AgentExecutionUpdate(
            output_data=result,
            status="success" if result.get("success") else "failed",
            error_message=safe_error,
            execution_time_ms=execution_time_ms,
            completed_at=utc_now(),
            metadata={
                **(metadata or {}),
                "request_id": request_id,
                "tool_name": tool_name,
                "tool_call_id": tool_call.call_id,
                "transport_protocol": tool.get_transport_protocol(),
                "mcp_server": tool.get_mcp_server(),
                "error_code": result.get("error_code"),
            },
        )
        execution_repo.update_execution(execution.execution_id, execution_update)

        final_metadata = {
            **result_metadata,
            "request_id": request_id,
            "execution_id": execution.execution_id,
            "tool_call_id": tool_call.call_id,
            "tool_name": tool_name,
            "transport_protocol": tool.get_transport_protocol(),
            "mcp_server": tool.get_mcp_server(),
        }
        result["metadata"] = final_metadata

        self.logger.info(
            "[TOOL-SVC] execute_done: request_id=%s tool_name=%s success=%s execution_id=%s tool_call_id=%s cost_ms=%s error_code=%s",
            request_id,
            tool_name,
            result.get("success"),
            execution.execution_id,
            tool_call.call_id,
            execution_time_ms,
            result.get("error_code"),
        )
        return result
