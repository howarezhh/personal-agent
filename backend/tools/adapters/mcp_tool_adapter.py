from __future__ import annotations

import asyncio
import json
from typing import Any, AsyncGenerator, Optional

from backend.contracts.tools import (
    ToolCallContext,
    ToolCapability,
    ToolDescriptor,
    ToolLifecycleStatus,
    ToolResult,
    ToolStreamEvent,
    ToolStreamEventType,
)
from backend.contracts.tools.tool_errors import ToolErrorCode, ToolErrorType
from backend.infrastructure.mcp import MCPProtocolError, get_mcp_server_manager
from backend.tools.adapters.base_adapter import BaseToolAdapter
from backend.tools.base_tool import ToolDefinition, ToolParameter


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


class MCPToolAdapter(BaseToolAdapter):
    """MCP 代理 Tool 适配器。"""

    client_timeout_buffer_seconds = 5

    def __init__(self, descriptor: ToolDescriptor, server_name: str, server_config: dict[str, Any]):
        self._server_name = server_name
        self._server_config = dict(server_config)
        super().__init__(descriptor)

    def get_definition(self) -> ToolDefinition:
        descriptor = self.get_descriptor()
        return ToolDefinition(
            name=descriptor.name,
            description=descriptor.description,
            parameters=_build_parameters_from_schema(descriptor.input_schema),
            category=descriptor.category,
            version=descriptor.version,
            timeout=descriptor.timeout,
            strict_validation=not bool(descriptor.input_schema.get("additionalProperties", True)),
        )

    async def initialize(self) -> None:
        self.set_lifecycle_status(ToolLifecycleStatus.AVAILABLE)

    def _merge_context_metadata(
        self,
        context: Optional[ToolCallContext],
        metadata: Optional[dict[str, Any]] = None,
    ) -> dict[str, Any]:
        merged = dict(metadata or {})
        if context is not None:
            merged.update({key: value for key, value in context.to_observability_metadata().items() if value is not None})
        merged["mcp_server"] = self._server_name
        merged["transport_protocol"] = self.get_transport_protocol()
        merged["tool_origin"] = self.get_tool_origin()
        merged["lifecycle_status"] = self.lifecycle_status
        return merged

    def _resolve_client_timeout(self) -> int:
        tool_timeout = int(self.descriptor.timeout or 30)
        configured_buffer = self._server_config.get("client_timeout_buffer_seconds")
        try:
            buffer_seconds = int(configured_buffer) if configured_buffer is not None else self.client_timeout_buffer_seconds
        except (TypeError, ValueError):
            buffer_seconds = self.client_timeout_buffer_seconds
        return tool_timeout + max(1, buffer_seconds)

    @staticmethod
    def _try_parse_json_text(text_payload: str) -> Any:
        try:
            return json.loads(text_payload)
        except json.JSONDecodeError:
            return text_payload

    @staticmethod
    def _looks_like_tool_result(payload: dict[str, Any]) -> bool:
        return isinstance(payload.get("success"), bool) and "metadata" in payload

    @classmethod
    def _normalize_content_payload(cls, content: Any) -> Any:
        # 中文说明：保留完整 content 列表，避免图片、资源、多段文本在适配层被丢弃。
        if not isinstance(content, list):
            return content
        if len(content) == 1 and isinstance(content[0], dict) and content[0].get("type") == "text":
            text_value = content[0].get("text")
            if isinstance(text_value, str):
                return cls._try_parse_json_text(text_value)
        return content

    @staticmethod
    def _stringify_error_payload(payload: Any) -> str:
        if isinstance(payload, str):
            return payload
        try:
            return json.dumps(payload, ensure_ascii=False)
        except TypeError:
            return str(payload)

    def _normalize_call_result(self, result: dict[str, Any], context: Optional[ToolCallContext] = None) -> ToolResult:
        # 中文说明：兼容标准 MCP result、项目内 ToolResult，以及第三方 MCP 的普通业务对象返回。
        structured_content = result.get("structuredContent")
        if isinstance(structured_content, dict):
            if self._looks_like_tool_result(structured_content):
                normalized = ToolResult.from_mapping(structured_content)
            else:
                normalized = ToolResult.success_result(data=structured_content)
            normalized.metadata = self._merge_context_metadata(context, normalized.metadata)
            self.set_lifecycle_status(ToolLifecycleStatus.COMPLETED if normalized.success else ToolLifecycleStatus.FAILED)
            normalized.metadata["lifecycle_status"] = self.lifecycle_status
            return normalized

        content_payload = self._normalize_content_payload(result.get("content"))
        if content_payload is None:
            raw_payload = {
                key: value
                for key, value in result.items()
                if key not in {"content", "structuredContent", "isError"}
            }
            content_payload = raw_payload or None

        is_error = bool(result.get("isError", False))
        if is_error:
            normalized = ToolResult.failure_result(
                error=self._stringify_error_payload(content_payload or f"MCP tool {self.descriptor.name} execution failed"),
                error_code=ToolErrorCode.TOOL_EXECUTION_ERROR.value,
                error_type=ToolErrorType.EXECUTION_ERROR.value,
                data=None,
                metadata=self._merge_context_metadata(context),
            )
        else:
            normalized = ToolResult.success_result(data=content_payload, metadata=self._merge_context_metadata(context))

        self.set_lifecycle_status(ToolLifecycleStatus.COMPLETED if normalized.success else ToolLifecycleStatus.FAILED)
        normalized.metadata["lifecycle_status"] = self.lifecycle_status
        return normalized

    def _build_stream_event_from_notification(
        self,
        notification: dict[str, Any],
        context: Optional[ToolCallContext] = None,
    ) -> Optional[ToolStreamEvent]:
        method = notification.get("method")
        params = notification.get("params") if isinstance(notification.get("params"), dict) else {}
        if not isinstance(method, str):
            return None

        metadata = self._merge_context_metadata(
            context,
            {
                "notification_method": method,
                "notification_params": params,
                "stream_mode": "protocol_notifications",
            },
        )

        if method.endswith("/error") or params.get("error"):
            return ToolStreamEvent(
                event_type=ToolStreamEventType.ERROR.value,
                error=str(params.get("error") or f"MCP stream notification error: {method}"),
                error_code=str(params.get("error_code") or ToolErrorCode.TOOL_EXECUTION_ERROR.value),
                metadata=metadata,
            )

        if method.endswith("/done") or params.get("done") is True:
            return ToolStreamEvent(event_type=ToolStreamEventType.DONE.value, metadata=metadata)

        content_value = params.get("content")
        if content_value is None:
            content_value = params.get("text") or params.get("delta") or params.get("message")

        return ToolStreamEvent(
            event_type=ToolStreamEventType.CONTENT.value,
            content=content_value,
            data=params.get("data"),
            metadata=metadata,
        )

    async def invoke(self, payload: dict[str, Any], context: Optional[ToolCallContext] = None) -> ToolResult:
        await self.initialize()
        self.set_lifecycle_status(ToolLifecycleStatus.INVOKING)
        manager = get_mcp_server_manager()
        client_timeout = self._resolve_client_timeout()
        try:
            client = await manager.connect(self._server_name, self._server_config, timeout=client_timeout)
            result = await client.call_tool(self.descriptor.name, payload)
        except MCPProtocolError as error:
            self.set_lifecycle_status(ToolLifecycleStatus.FAILED)
            return ToolResult.failure_result(
                error=str(error),
                error_code=ToolErrorCode.TOOL_PROTOCOL_ERROR.value,
                error_type=ToolErrorType.PROTOCOL_ERROR.value,
                metadata=self._merge_context_metadata(context),
            )
        except Exception as error:
            self.set_lifecycle_status(ToolLifecycleStatus.FAILED)
            return ToolResult.failure_result(
                error=str(error),
                error_code=ToolErrorCode.TOOL_UPSTREAM_ERROR.value,
                error_type=ToolErrorType.UPSTREAM_ERROR.value,
                metadata=self._merge_context_metadata(context),
            )
        finally:
            disconnect_method = getattr(manager, "disconnect")
            try:
                await disconnect_method(self._server_name, client_timeout)
            except TypeError:
                await disconnect_method(self._server_name)

        return self._normalize_call_result(result, context=context)

    async def invoke_stream(
        self,
        payload: dict[str, Any],
        context: Optional[ToolCallContext] = None,
    ) -> AsyncGenerator[ToolStreamEvent, None]:
        descriptor = self.get_descriptor()
        if not descriptor.supports(ToolCapability.STREAM):
            raise MCPProtocolError(f"MCP Tool {descriptor.name} does not support stream capability")

        self.set_lifecycle_status(ToolLifecycleStatus.STREAMING)
        base_metadata = self._merge_context_metadata(context, {"stream_mode": "protocol_notifications"})
        yield ToolStreamEvent(
            event_type=ToolStreamEventType.START.value,
            metadata=base_metadata,
        )
        manager = get_mcp_server_manager()
        client_timeout = self._resolve_client_timeout()
        terminal_event_emitted = False
        client = await manager.open_session(self._server_name, self._server_config, timeout=client_timeout)
        call_task = asyncio.create_task(client.call_tool(self.descriptor.name, payload))
        try:
            while not call_task.done():
                try:
                    notification = await asyncio.wait_for(client.next_notification(), timeout=0.1)
                except asyncio.TimeoutError:
                    continue

                event = self._build_stream_event_from_notification(notification, context=context)
                if event is None:
                    continue
                if event.event_type in {ToolStreamEventType.ERROR.value, ToolStreamEventType.DONE.value}:
                    terminal_event_emitted = True
                yield event

            # 中文说明：收尾阶段再短暂 drain 一次，避免结果返回前最后一批通知被漏掉。
            while True:
                try:
                    notification = await asyncio.wait_for(client.next_notification(), timeout=0.01)
                except asyncio.TimeoutError:
                    break

                event = self._build_stream_event_from_notification(notification, context=context)
                if event is None:
                    continue
                if event.event_type in {ToolStreamEventType.ERROR.value, ToolStreamEventType.DONE.value}:
                    terminal_event_emitted = True
                yield event

            result = self._normalize_call_result(await call_task, context=context)
            event_metadata = self._merge_context_metadata(
                context,
                {
                    **(result.metadata if isinstance(result.metadata, dict) else {}),
                    "stream_mode": "protocol_notifications",
                },
            )
            if result.success:
                yield ToolStreamEvent(
                    event_type=ToolStreamEventType.RESULT.value,
                    data=result.data,
                    metadata=event_metadata,
                )
                if not terminal_event_emitted:
                    yield ToolStreamEvent(
                        event_type=ToolStreamEventType.DONE.value,
                        metadata=event_metadata,
                    )
                self.set_lifecycle_status(ToolLifecycleStatus.COMPLETED)
                return

            self.set_lifecycle_status(ToolLifecycleStatus.FAILED)
            if not terminal_event_emitted:
                yield ToolStreamEvent(
                    event_type=ToolStreamEventType.ERROR.value,
                    error=result.error or f"MCP tool {descriptor.name} streaming failed",
                    error_code=result.error_code or ToolErrorCode.TOOL_EXECUTION_ERROR.value,
                    metadata=event_metadata,
                )
        except MCPProtocolError as error:
            self.set_lifecycle_status(ToolLifecycleStatus.FAILED)
            yield ToolStreamEvent(
                event_type=ToolStreamEventType.ERROR.value,
                error=str(error),
                error_code=ToolErrorCode.TOOL_PROTOCOL_ERROR.value,
                metadata=self._merge_context_metadata(context, {"stream_mode": "protocol_notifications"}),
            )
        except Exception as error:
            self.set_lifecycle_status(ToolLifecycleStatus.FAILED)
            yield ToolStreamEvent(
                event_type=ToolStreamEventType.ERROR.value,
                error=str(error),
                error_code=ToolErrorCode.TOOL_UPSTREAM_ERROR.value,
                metadata=self._merge_context_metadata(context, {"stream_mode": "protocol_notifications"}),
            )
        finally:
            if not call_task.done():
                call_task.cancel()
            await client.close()

    async def close(self) -> None:
        self.set_lifecycle_status(ToolLifecycleStatus.CLOSED)

    async def safe_execute(self, **kwargs) -> dict[str, Any]:
        return (await self.invoke(kwargs)).to_dict()
