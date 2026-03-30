from __future__ import annotations

import asyncio
import inspect
import logging
from typing import Any, AsyncGenerator, Optional

from backend.contracts.tools import (
    ToolCallContext,
    ToolCapability,
    ToolLifecycleStatus,
    ToolResult,
    ToolStreamEvent,
    ToolStreamEventType,
)
from backend.contracts.tools.tool_errors import ToolErrorCode, ToolErrorType
from backend.tools.adapters.base_adapter import BaseToolAdapter
from backend.tools.base_tool import BaseTool, ToolCloseError, ToolInitializationError


class LocalToolAdapter(BaseToolAdapter):
    """本地直连 Tool 适配器。"""

    def __init__(self, tool: BaseTool):
        self.tool = tool
        self.logger = logging.getLogger(self.__class__.__name__)
        super().__init__(tool.get_descriptor())
        self._initialized = False
        self._validate_declared_capabilities()

    def _validate_declared_capabilities(self) -> None:
        """校验显式能力声明与实现一致。"""

        descriptor = self.get_descriptor()
        if descriptor.supports(ToolCapability.STREAM) and not callable(getattr(self.tool, "execute_stream", None)):
            raise ToolInitializationError(f"Tool {descriptor.name} 声明了 stream 能力，但未实现 execute_stream")

    def get_definition(self):
        return self.tool.get_definition()

    async def initialize(self) -> None:
        if self._initialized:
            self.set_lifecycle_status(ToolLifecycleStatus.AVAILABLE)
            return
        self.set_lifecycle_status(ToolLifecycleStatus.INITIALIZED)
        initialize_method = getattr(self.tool, "initialize", None)
        if callable(initialize_method):
            try:
                result = initialize_method()
                if inspect.isawaitable(result):
                    await result
            except Exception as error:  # pragma: no cover
                self.set_lifecycle_status(ToolLifecycleStatus.FAILED)
                raise ToolInitializationError(f"Tool 初始化失败: {error}") from error
        self._initialized = True
        self.set_lifecycle_status(ToolLifecycleStatus.AVAILABLE)

    def _merge_context_metadata(self, context: Optional[ToolCallContext], metadata: Optional[dict[str, Any]] = None) -> dict[str, Any]:
        merged = dict(metadata or {})
        if context is not None:
            merged.update({key: value for key, value in context.to_observability_metadata().items() if value is not None})
        merged["lifecycle_status"] = self.lifecycle_status
        merged["transport_protocol"] = self.get_transport_protocol()
        merged["tool_origin"] = self.get_tool_origin()
        merged["mcp_server"] = self.get_mcp_server()
        return merged

    async def invoke(self, payload: dict[str, Any], context: Optional[ToolCallContext] = None) -> ToolResult:
        await self.initialize()
        self.set_lifecycle_status(ToolLifecycleStatus.INVOKING)
        try:
            result = ToolResult.from_mapping(await self.tool.invoke(payload))
            result.metadata = self._merge_context_metadata(context, result.metadata)
            self.set_lifecycle_status(ToolLifecycleStatus.COMPLETED if result.success else ToolLifecycleStatus.FAILED)
            result.metadata["lifecycle_status"] = self.lifecycle_status
            return result
        except Exception as error:
            self.set_lifecycle_status(ToolLifecycleStatus.FAILED)
            return ToolResult.failure_result(
                error=str(error),
                error_code=ToolErrorCode.TOOL_EXECUTION_ERROR.value,
                error_type=ToolErrorType.EXECUTION_ERROR.value,
                metadata=self._merge_context_metadata(context),
            )

    async def invoke_stream(
        self,
        payload: dict[str, Any],
        context: Optional[ToolCallContext] = None,
    ) -> AsyncGenerator[ToolStreamEvent, None]:
        await self.initialize()
        descriptor = self.get_descriptor()
        if not descriptor.supports(ToolCapability.STREAM):
            raise ToolInitializationError(f"Tool {descriptor.name} 未声明 stream 能力")

        self.set_lifecycle_status(ToolLifecycleStatus.STREAMING)
        terminal_emitted = False
        execute_stream = getattr(self.tool, "execute_stream")
        try:
            async for raw_event in execute_stream(**payload):
                event = ToolStreamEvent.from_legacy_event(raw_event if isinstance(raw_event, dict) else {})
                event.metadata = self._merge_context_metadata(context, event.metadata)
                if event.event_type in {ToolStreamEventType.ERROR.value, ToolStreamEventType.DONE.value}:
                    terminal_emitted = True
                yield event

            if not terminal_emitted:
                yield ToolStreamEvent(
                    event_type=ToolStreamEventType.DONE.value,
                    metadata=self._merge_context_metadata(context),
                )
            self.set_lifecycle_status(ToolLifecycleStatus.COMPLETED)
        except asyncio.CancelledError:
            self.set_lifecycle_status(ToolLifecycleStatus.FAILED)
            yield ToolStreamEvent(
                event_type=ToolStreamEventType.ERROR.value,
                error="Tool streaming cancelled",
                error_code=ToolErrorCode.TOOL_STREAM_CANCELLED.value,
                metadata=self._merge_context_metadata(context),
            )
            raise
        except Exception as error:
            self.set_lifecycle_status(ToolLifecycleStatus.FAILED)
            yield ToolStreamEvent(
                event_type=ToolStreamEventType.ERROR.value,
                error=str(error),
                error_code=ToolErrorCode.TOOL_EXECUTION_ERROR.value,
                metadata=self._merge_context_metadata(context),
            )

    async def close(self) -> None:
        self.set_lifecycle_status(ToolLifecycleStatus.CLOSING)
        close_method = getattr(self.tool, "close", None)
        if callable(close_method):
            try:
                result = close_method()
                if inspect.isawaitable(result):
                    await result
            except Exception as error:  # pragma: no cover
                self.set_lifecycle_status(ToolLifecycleStatus.FAILED)
                raise ToolCloseError(f"Tool 关闭失败: {error}") from error
        self.set_lifecycle_status(ToolLifecycleStatus.CLOSED)

    async def safe_execute(self, **kwargs) -> dict[str, Any]:
        return (await self.invoke(kwargs)).to_dict()

    async def execute_stream(self, **kwargs) -> AsyncGenerator[dict[str, Any], None]:
        async for event in self.invoke_stream(kwargs):
            yield event.to_legacy_event()

