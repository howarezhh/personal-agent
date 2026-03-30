# -*- coding: utf-8 -*-
"""LangChain 工具适配器。

负责把项目内部的 `BaseTool` / `ToolDefinition` 适配成 LangChain `StructuredTool`，
并复用 `ToolApplicationService` 统一执行工具调用、补齐上下文与结果回填。
"""

from __future__ import annotations

from typing import Any, Optional, Sequence

from langchain_core.tools import StructuredTool
from pydantic import BaseModel, ConfigDict, Field, create_model

from backend.application.service_factory import build_tool_application_service
from backend.application.services.tool_application_service import ToolApplicationService
from backend.tools.base_tool import BaseTool, ToolDefinition


class LangChainToolExecutionContext(BaseModel):
    """LangChain 工具执行上下文。"""

    user_id: Optional[str] = None
    conversation_id: Optional[str] = None
    message_id: Optional[str] = None
    is_admin: bool = False
    metadata: dict[str, Any] = Field(default_factory=dict)


class _LangChainToolArgsBase(BaseModel):
    """用于承接 LangChain 参数模型的基础类。"""

    model_config = ConfigDict(extra="allow")


class LangChainToolAdapter:
    """把项目工具适配为 LangChain `StructuredTool`。"""

    def __init__(self, tool_service: Optional[ToolApplicationService] = None):
        self.tool_service = tool_service or build_tool_application_service()

    def adapt_tools(
        self,
        tools: Sequence[BaseTool],
        *,
        execution_context: Optional[LangChainToolExecutionContext] = None,
    ) -> list[StructuredTool]:
        """批量适配多个项目工具。"""
        return [self.adapt_tool(tool, execution_context=execution_context) for tool in tools]

    def adapt_tool(
        self,
        tool: BaseTool,
        *,
        execution_context: Optional[LangChainToolExecutionContext] = None,
    ) -> StructuredTool:
        """把单个项目工具适配成 LangChain `StructuredTool`。"""
        tool_definition = tool.get_definition()
        args_schema = self._build_args_schema(tool_definition)

        async def _invoke_tool(**kwargs: Any) -> dict[str, Any]:
            return await self.execute_tool_call(
                tool=tool,
                arguments=kwargs,
                execution_context=execution_context,
            )

        return StructuredTool.from_function(
            coroutine=_invoke_tool,
            name=tool_definition.name,
            description=tool_definition.description,
            args_schema=args_schema,
            infer_schema=False,
        )

    async def execute_tool_call(
        self,
        *,
        tool: BaseTool,
        arguments: dict[str, Any],
        execution_context: Optional[LangChainToolExecutionContext] = None,
    ) -> dict[str, Any]:
        """执行工具调用并统一回填 metadata。"""
        if execution_context and execution_context.user_id:
            result = await self.tool_service.execute_tool(
                tool_name=tool.get_name(),
                parameters=arguments,
                user_id=execution_context.user_id,
                is_admin=execution_context.is_admin,
                conversation_id=execution_context.conversation_id,
                message_id=execution_context.message_id,
                metadata=dict(execution_context.metadata),
            )
        else:
            result = await tool.safe_execute(**arguments)

        normalized_metadata = result.get("metadata") if isinstance(result.get("metadata"), dict) else {}
        normalized_metadata.setdefault("tool_name", tool.get_name())
        normalized_metadata.setdefault("tool_origin", tool.get_tool_origin())
        if tool.get_mcp_server():
            normalized_metadata.setdefault("mcp_server", tool.get_mcp_server())
        result["metadata"] = normalized_metadata
        return result

    def _build_args_schema(self, tool_definition: ToolDefinition) -> type[BaseModel]:
        """根据 `ToolDefinition` 构造 LangChain 参数 Schema。"""
        model_fields: dict[str, tuple[Any, Any]] = {}
        for parameter in tool_definition.parameters:
            python_type = self._map_parameter_type(parameter.type)
            default_value = ... if parameter.required and parameter.default is None else parameter.default
            if default_value is None and not parameter.required:
                default_value = None
            schema_fragment = parameter.to_json_schema()
            json_schema_extra = {
                key: value
                for key, value in schema_fragment.items()
                if key not in {"type", "description", "default"}
            }
            field_kwargs: dict[str, Any] = {
                "default": default_value,
                "description": parameter.description,
            }
            if parameter.minimum is not None:
                field_kwargs["ge"] = parameter.minimum
            if parameter.maximum is not None:
                field_kwargs["le"] = parameter.maximum
            if parameter.min_length is not None:
                field_kwargs["min_length"] = parameter.min_length
            if parameter.max_length is not None:
                field_kwargs["max_length"] = parameter.max_length
            if parameter.pattern is not None:
                field_kwargs["pattern"] = parameter.pattern
            if json_schema_extra:
                field_kwargs["json_schema_extra"] = json_schema_extra
            model_fields[parameter.name] = (
                python_type,
                Field(**field_kwargs),
            )

        model_name = "".join(part.capitalize() for part in tool_definition.name.split("_")) + "Args"
        return create_model(model_name, __base__=_LangChainToolArgsBase, **model_fields)

    def _map_parameter_type(self, parameter_type: str) -> Any:
        """把 JSON Schema 基础类型映射为 Python 类型。"""
        if parameter_type == "string":
            return str
        if parameter_type == "integer":
            return int
        if parameter_type == "number":
            return float
        if parameter_type == "boolean":
            return bool
        if parameter_type == "array":
            return list[Any]
        if parameter_type == "object":
            return dict[str, Any]
        return Any


__all__ = [
    "LangChainToolAdapter",
    "LangChainToolExecutionContext",
]
