"""
工具注册表
管理所有可用工具的注册和获取（包括本地工具和MCP工具）
"""

from typing import Dict, List, Optional
from backend.tools.base_tool import BaseTool, ToolDefinition
import logging


class ToolRegistry:
    """
    统一工具注册表

    单例模式，管理所有可用工具（本地工具和MCP工具）
    """

    _instance = None
    _tools: Dict[str, BaseTool] = {}

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance.logger = logging.getLogger("ToolRegistry")
        return cls._instance

    def register(self, tool: BaseTool) -> None:
        """
        注册工具

        Args:
            tool: 工具实例
        """
        tool_name = tool.get_name()

        if tool_name in self._tools:
            self.logger.warning(f"工具 '{tool_name}' 已注册，正在覆盖")

        self._tools[tool_name] = tool
        self.logger.info(f"工具已注册: {tool_name}")

    def unregister(self, tool_name: str) -> bool:
        """
        注销工具

        Args:
            tool_name: 工具名称

        Returns:
            是否成功注销
        """
        if tool_name in self._tools:
            del self._tools[tool_name]
            self.logger.info(f"工具已注销: {tool_name}")
            return True
        return False

    def get_tool(self, tool_name: str) -> Optional[BaseTool]:
        """
        获取工具实例

        Args:
            tool_name: 工具名称

        Returns:
            工具实例，如果不存在返回None
        """
        return self._tools.get(tool_name)

    def get_all_tools(self) -> Dict[str, BaseTool]:
        """
        获取所有工具

        Returns:
            工具字典 {tool_name: tool_instance}
        """
        return self._tools.copy()

    def get_tool_names(self) -> List[str]:
        """
        获取所有工具名称

        Returns:
            工具名称列表
        """
        return list(self._tools.keys())

    def get_tools_by_category(self, category: str) -> List[BaseTool]:
        """
        根据分类获取工具

        Args:
            category: 工具分类

        Returns:
            工具列表
        """
        return [
            tool for tool in self._tools.values()
            if tool.get_category() == category
        ]

    def get_tool_definitions(self) -> List[dict]:
        """
        获取所有工具的定义（用于LLM）

        Returns:
            工具定义列表
        """
        return [
            tool.get_definition().to_dict()
            for tool in self._tools.values()
        ]

    def get_tool_definition(self, tool_name: str) -> Optional[dict]:
        """
        获取指定工具的定义

        Args:
            tool_name: 工具名称

        Returns:
            工具定义字典，如果不存在返回None
        """
        tool = self.get_tool(tool_name)
        if tool:
            return tool.get_definition().to_dict()
        return None

    def is_tool_available(self, tool_name: str) -> bool:
        """
        检查工具是否可用

        Args:
            tool_name: 工具名称

        Returns:
            是否可用
        """
        return tool_name in self._tools

    def clear(self) -> None:
        """
        清空所有工具（主要用于测试）
        """
        self._tools.clear()
        self.logger.info("所有工具已清空")

    def get_tool_count(self) -> int:
        """
        获取工具数量

        Returns:
            工具数量
        """
        return len(self._tools)

    def __repr__(self) -> str:
        return f"<ToolRegistry(tools={len(self._tools)})>"


# 全局工具注册表实例
_tool_registry = ToolRegistry()


def get_tool_registry() -> ToolRegistry:
    """
    获取全局工具注册表实例

    Returns:
        工具注册表实例
    """
    return _tool_registry


def register_tool(tool: BaseTool) -> None:
    """
    注册工具到全局注册表

    Args:
        tool: 工具实例
    """
    _tool_registry.register(tool)


def get_tool(tool_name: str) -> Optional[BaseTool]:
    """
    从全局注册表获取工具

    Args:
        tool_name: 工具名称

    Returns:
        工具实例
    """
    return _tool_registry.get_tool(tool_name)


def get_all_tools() -> Dict[str, BaseTool]:
    """
    获取所有工具

    Returns:
        工具字典
    """
    return _tool_registry.get_all_tools()


def get_tool_definitions() -> List[dict]:
    """
    获取所有工具定义

    Returns:
        工具定义列表
    """
    return _tool_registry.get_tool_definitions()
