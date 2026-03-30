"""Tool 注册表。

中文说明：
1. 统一保存 `ToolDescriptor -> RuntimeAdapter` 的映射。
2. 对外仍保留兼容方法，避免大面积改动调用方。
3. 注册阶段只负责声明进入注册表，不负责初始化依赖。
"""

from __future__ import annotations

import logging
from threading import RLock
from typing import Any, Optional

from backend.contracts.tools import ToolDescriptor, ToolLifecycleStatus
from backend.tools.adapters.base_adapter import BaseToolAdapter


class ToolRegistry:
    """统一 Tool 注册表。"""

    _instance: Optional["ToolRegistry"] = None

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._initialized = False
        return cls._instance

    def __init__(self):
        if self._initialized:
            return
        self.logger = logging.getLogger("ToolRegistry")
        self._tools: dict[str, BaseToolAdapter] = {}
        self._descriptors: dict[str, ToolDescriptor] = {}
        self._lock = RLock()
        self._initialized = True

    @staticmethod
    def _validate_adapter(adapter: BaseToolAdapter) -> None:
        if not isinstance(adapter, BaseToolAdapter):
            raise TypeError("只允许注册 BaseToolAdapter 实例")
        descriptor = adapter.get_descriptor()
        if not isinstance(descriptor, ToolDescriptor):
            raise TypeError("运行时适配器必须暴露 ToolDescriptor")
        if not descriptor.name:
            raise ValueError("ToolDescriptor.name 不能为空")
        if descriptor.timeout <= 0:
            raise ValueError(f"ToolDescriptor.timeout 必须大于 0: {descriptor.name}")

    def register(self, adapter: BaseToolAdapter) -> None:
        """注册 Tool 运行时适配器。"""

        self._validate_adapter(adapter)
        descriptor = adapter.get_descriptor()
        with self._lock:
            self._tools[descriptor.name] = adapter
            self._descriptors[descriptor.name] = descriptor
            adapter.set_lifecycle_status(ToolLifecycleStatus.REGISTERED)
        self.logger.info("Tool registered: %s", descriptor.name)

    def unregister(self, tool_name: str) -> bool:
        with self._lock:
            existed = tool_name in self._tools
            self._tools.pop(tool_name, None)
            self._descriptors.pop(tool_name, None)
        if existed:
            self.logger.info("Tool unregistered: %s", tool_name)
        return existed

    def get_tool(self, tool_name: str) -> Optional[BaseToolAdapter]:
        return self._tools.get(tool_name)

    def get_all_tools(self) -> dict[str, BaseToolAdapter]:
        with self._lock:
            return self._tools.copy()

    def get_tool_names(self) -> list[str]:
        with self._lock:
            return list(self._tools.keys())

    def get_tools_by_category(self, category: str) -> list[BaseToolAdapter]:
        with self._lock:
            return [tool for tool in self._tools.values() if tool.get_descriptor().category == category]

    def get_tool_descriptor(self, tool_name: str) -> Optional[ToolDescriptor]:
        return self._descriptors.get(tool_name)

    def get_tool_descriptors(self) -> list[ToolDescriptor]:
        with self._lock:
            return list(self._descriptors.values())

    def get_tool_definition(self, tool_name: str) -> Optional[dict[str, Any]]:
        tool = self.get_tool(tool_name)
        if tool is None:
            return None
        definition = tool.get_definition().to_dict()
        descriptor = tool.get_descriptor()
        definition.update(
            {
                "capabilities": list(descriptor.capabilities),
                "transport_protocol": descriptor.transport_protocol,
                "tool_origin": descriptor.tool_origin,
                "mcp_server": descriptor.mcp_server,
            }
        )
        return definition

    def get_tool_definitions(self) -> list[dict[str, Any]]:
        with self._lock:
            return [self.get_tool_definition(tool_name) for tool_name in self._tools.keys() if self.get_tool_definition(tool_name)]

    def is_tool_available(self, tool_name: str) -> bool:
        tool = self.get_tool(tool_name)
        if tool is None:
            return False
        return tool.lifecycle_status in {
            ToolLifecycleStatus.AVAILABLE.value,
            ToolLifecycleStatus.COMPLETED.value,
        }

    def clear(self) -> None:
        with self._lock:
            self._tools.clear()
            self._descriptors.clear()
        self.logger.info("All tools cleared")

    def get_tool_count(self) -> int:
        return len(self._tools)

    def __repr__(self) -> str:
        return f"<ToolRegistry(tools={len(self._tools)})>"


_tool_registry = ToolRegistry()


def get_tool_registry() -> ToolRegistry:
    return _tool_registry


def register_tool(tool: BaseToolAdapter) -> None:
    _tool_registry.register(tool)


def get_tool(tool_name: str) -> Optional[BaseToolAdapter]:
    return _tool_registry.get_tool(tool_name)


def get_all_tools() -> dict[str, BaseToolAdapter]:
    return _tool_registry.get_all_tools()


def get_tool_definitions() -> list[dict[str, Any]]:
    return _tool_registry.get_tool_definitions()
