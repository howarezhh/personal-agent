from __future__ import annotations

import logging
from abc import ABC, abstractmethod
from typing import Any, AsyncGenerator, Optional

from backend.contracts.tools import (
    ToolCallContext,
    ToolDescriptor,
    ToolLifecycleStatus,
    ToolResult,
    ToolStreamEvent,
)


class BaseToolAdapter(ABC):
    """Tool 运行时适配器抽象基类。"""

    def __init__(self, descriptor: ToolDescriptor):
        self._descriptor = descriptor
        self._lifecycle_status = ToolLifecycleStatus.DECLARED.value
        self.logger = logging.getLogger(self.__class__.__name__)

    @property
    def descriptor(self) -> ToolDescriptor:
        return self._descriptor

    @property
    def lifecycle_status(self) -> str:
        return self._lifecycle_status

    def set_lifecycle_status(self, status: ToolLifecycleStatus | str) -> None:
        """统一记录生命周期变化，便于观测与测试。"""

        next_status = str(status)
        previous_status = self._lifecycle_status
        self._lifecycle_status = next_status
        if previous_status != next_status:
            self.logger.info(
                "[TOOL-LIFECYCLE] tool=%s status=%s previous=%s transport=%s mcp_server=%s",
                self.get_name(),
                next_status,
                previous_status,
                self.get_transport_protocol(),
                self.get_mcp_server(),
            )

    def get_name(self) -> str:
        return self._descriptor.name

    def get_transport_protocol(self) -> str:
        return self._descriptor.transport_protocol

    def get_tool_origin(self) -> str:
        return self._descriptor.tool_origin

    def get_mcp_server(self) -> Optional[str]:
        return self._descriptor.mcp_server

    def get_descriptor(self) -> ToolDescriptor:
        return self._descriptor

    @abstractmethod
    async def initialize(self) -> None:
        raise NotImplementedError

    @abstractmethod
    async def invoke(self, payload: dict[str, Any], context: Optional[ToolCallContext] = None) -> ToolResult:
        raise NotImplementedError

    @abstractmethod
    async def invoke_stream(
        self,
        payload: dict[str, Any],
        context: Optional[ToolCallContext] = None,
    ) -> AsyncGenerator[ToolStreamEvent, None]:
        raise NotImplementedError

    @abstractmethod
    async def close(self) -> None:
        raise NotImplementedError
