"""工具配置访问层。

该模块对底层配置中心做了一层轻量封装，目的是：
1. 统一工具相关配置的读取入口。
2. 避免业务代码到处拼接配置路径。
3. 为工具注册表、启用状态和单工具配置提供集中访问方式。

这里采用单例方式，确保整个进程共享同一个工具配置访问对象。
"""

from __future__ import annotations

from typing import Any, Optional

from backend.core.config_manager import get_config_manager


class ToolConfig:
    """工具配置管理器。"""

    _instance: Optional["ToolConfig"] = None

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._initialized = False
        return cls._instance

    def __init__(self):
        if self._initialized:
            return
        self.config_manager = get_config_manager()
        self._runtime_overrides: dict[str, dict[str, Any]] = {}
        self._initialized = True

    def get(self, tool_name: str, key: str, default: Any = None) -> Any:
        """读取指定工具下某个配置项的值。"""

        if tool_name in self._runtime_overrides and key in self._runtime_overrides[tool_name]:
            return self._runtime_overrides[tool_name][key]
        return self.config_manager.get(f"tools.{tool_name}.{key}", default)

    def get_all(self, tool_name: str) -> dict[str, Any]:
        """读取某个工具的全部配置，不存在时返回空字典。"""

        file_config = self.config_manager.get_tool_config(tool_name, {}) or {}
        runtime_config = self._runtime_overrides.get(tool_name, {})
        if not isinstance(file_config, dict):
            file_config = {}
        return {**file_config, **runtime_config}

    def get_registry(self) -> dict[str, dict[str, Any]]:
        """读取工具注册表配置。"""

        registry = self.config_manager.get_tool_config("registry", {}) or {}
        return registry if isinstance(registry, dict) else {}

    def get_enabled_tool_names(
        self,
        tool_type: Optional[str] = None,
        expose_to_agent_only: bool = False,
    ) -> list[str]:
        """返回满足过滤条件的已启用工具名称列表。"""

        enabled_names: list[str] = []
        for tool_name, entry in self.get_registry().items():
            if not isinstance(entry, dict) or not entry.get("enabled", True):
                continue
            if tool_type and entry.get("type") != tool_type:
                continue
            if expose_to_agent_only and not entry.get("expose_to_agent", True):
                continue
            enabled_names.append(tool_name)
        return enabled_names

    def set(self, tool_name: str, key: str, value: Any) -> None:
        """在当前运行时内存中动态设置工具配置项。"""

        tool_override = self._runtime_overrides.setdefault(tool_name, {})
        tool_override[key] = value

    def validate_config(self, tool_name: str) -> tuple[bool, Optional[str]]:
        """对指定工具的关键配置做基础校验。"""

        config = self.get_all(tool_name)
        if config and not isinstance(config, dict):
            return False, f"工具 {tool_name} 的配置必须是对象类型"

        entry = self.get_registry().get(tool_name)
        if not entry:
            return True, None
        if not isinstance(entry, dict):
            return False, f"工具 {tool_name} 的注册配置必须是对象类型"
        if entry.get("enabled", True) and not entry.get("class_path"):
            return False, f"工具 {tool_name} 缺少 class_path 配置"
        timeout = config.get("timeout")
        if timeout is not None and (not isinstance(timeout, int) or timeout <= 0):
            return False, f"工具 {tool_name} 的 timeout 必须是正整数"
        return True, None

    def __repr__(self) -> str:
        return f"ToolConfig(tools={list(self.get_registry().keys())})"


_tool_config: Optional[ToolConfig] = None


def get_tool_config() -> ToolConfig:
    """获取全局唯一的工具配置实例。"""

    global _tool_config
    if _tool_config is None:
        _tool_config = ToolConfig()
    return _tool_config
