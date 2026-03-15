"""全局工具注册表。

该模块维护“工具名称 -> 工具实例”的全局映射关系，
统一提供注册、查询、枚举、注销等能力。

与早期实现相比，这里额外强调：
1. 共享状态只保存在实例级，避免类属性带来的测试污染。
2. 注册时显式校验工具是否满足基础契约。
3. 通过轻量锁保证并发注册/清理时的状态一致性。
"""

from __future__ import annotations

import logging
from threading import RLock
from typing import Dict, List, Optional

from backend.tools.base_tool import BaseTool, ToolDefinition


class ToolRegistry:
    """工具注册表单例。"""

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
        self._tools: Dict[str, BaseTool] = {}
        self._lock = RLock()
        self._initialized = True

    @staticmethod
    def _validate_tool_contract(tool: BaseTool) -> None:
        if not isinstance(tool, BaseTool):
            raise TypeError("只允许注册 BaseTool 子类实例")

        definition = tool.get_definition()
        if not isinstance(definition, ToolDefinition):
            raise TypeError("工具定义必须是 ToolDefinition 实例")
        if not definition.name:
            raise ValueError("工具名称不能为空")
        if definition.timeout <= 0:
            raise ValueError(f"工具 {definition.name} 的 timeout 必须大于 0")
        if not isinstance(definition.parameters, list):
            raise TypeError(f"工具 {definition.name} 的 parameters 必须是列表")

    def register(self, tool: BaseTool) -> None:
        """注册一个工具实例。"""

        self._validate_tool_contract(tool)
        tool_name = tool.get_name()

        with self._lock:
            if tool_name in self._tools:
                self.logger.warning("工具 '%s' 已注册，正在覆盖", tool_name)
            self._tools[tool_name] = tool

        self.logger.info("工具已注册: %s", tool_name)

    def unregister(self, tool_name: str) -> bool:
        """按名称注销工具，成功时返回 True。"""

        with self._lock:
            if tool_name not in self._tools:
                return False
            del self._tools[tool_name]

        self.logger.info("工具已注销: %s", tool_name)
        return True

    def get_tool(self, tool_name: str) -> Optional[BaseTool]:
        """按名称获取单个工具实例。"""

        return self._tools.get(tool_name)

    def get_all_tools(self) -> Dict[str, BaseTool]:
        """返回所有工具的浅拷贝映射。"""

        with self._lock:
            return self._tools.copy()

    def get_tool_names(self) -> List[str]:
        """返回当前所有已注册工具名称。"""

        with self._lock:
            return list(self._tools.keys())

    def get_tools_by_category(self, category: str) -> List[BaseTool]:
        """按分类筛选工具实例列表。"""

        with self._lock:
            return [
                tool for tool in self._tools.values()
                if tool.get_category() == category
            ]

    def get_tool_definitions(self) -> List[dict]:
        """返回全部工具定义信息。"""

        with self._lock:
            return [tool.get_definition().to_dict() for tool in self._tools.values()]

    def get_tool_definition(self, tool_name: str) -> Optional[dict]:
        """返回指定工具的定义信息，不存在时返回 None。"""

        tool = self.get_tool(tool_name)
        return tool.get_definition().to_dict() if tool else None

    def is_tool_available(self, tool_name: str) -> bool:
        """判断指定工具当前是否已注册可用。"""

        return tool_name in self._tools

    def clear(self) -> None:
        """清空全部已注册工具。"""

        with self._lock:
            self._tools.clear()
        self.logger.info("所有工具已清空")

    def get_tool_count(self) -> int:
        """返回当前工具数量。"""

        return len(self._tools)

    def __repr__(self) -> str:
        return f"<ToolRegistry(tools={len(self._tools)})>"


_tool_registry = ToolRegistry()


def get_tool_registry() -> ToolRegistry:
    """获取全局工具注册表实例。"""

    return _tool_registry


def register_tool(tool: BaseTool) -> None:
    """注册工具的便捷函数。"""

    _tool_registry.register(tool)


def get_tool(tool_name: str) -> Optional[BaseTool]:
    """获取单个工具的便捷函数。"""

    return _tool_registry.get_tool(tool_name)


def get_all_tools() -> Dict[str, BaseTool]:
    """获取所有工具的便捷函数。"""

    return _tool_registry.get_all_tools()


def get_tool_definitions() -> List[dict]:
    """获取所有工具定义的便捷函数。"""

    return _tool_registry.get_tool_definitions()
