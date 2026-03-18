"""工具配置访问层。

统一把工具注册表收敛为以下规范字段：
- `transport_protocol`: 当前运行时工具协议
- `tool_origin`: 工具来源，区分 `local` / `external`
- `mcp_server`: 绑定的 MCP Server
- `implementation.class_path`: builtin server 内部真实实现类

访问层只读取和返回规范字段，不再承担历史配置兼容职责。
"""

from __future__ import annotations

from copy import deepcopy
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
        if tool_name in self._runtime_overrides and key in self._runtime_overrides[tool_name]:
            return self._runtime_overrides[tool_name][key]
        return self.config_manager.get(f"tools.{tool_name}.{key}", default)

    def get_all(self, tool_name: str) -> dict[str, Any]:
        file_config = self.config_manager.get_tool_config(tool_name, {}) or {}
        runtime_config = self._runtime_overrides.get(tool_name, {})
        if not isinstance(file_config, dict):
            file_config = {}
        return {**file_config, **runtime_config}

    def normalize_registry_entry(self, tool_name: str, entry: Any) -> dict[str, Any]:
        if not isinstance(entry, dict):
            return {}

        normalized = deepcopy(entry)
        implementation = normalized.get("implementation") if isinstance(normalized.get("implementation"), dict) else {}
        class_path = implementation.get("class_path")
        transport_protocol = normalized.get("transport_protocol") or "mcp"
        tool_origin = normalized.get("tool_origin") or "local"
        mcp_server = normalized.get("mcp_server") or "builtin"

        normalized["enabled"] = bool(normalized.get("enabled", True))
        normalized["expose_to_agent"] = bool(normalized.get("expose_to_agent", True))
        normalized["transport_protocol"] = str(transport_protocol)
        normalized["tool_origin"] = str(tool_origin)
        normalized["mcp_server"] = str(mcp_server)
        normalized["implementation"] = {
            **implementation,
            **({"class_path": class_path} if class_path else {}),
        }
        return normalized

    def get_registry(self) -> dict[str, dict[str, Any]]:
        registry = self.config_manager.get_tool_config("registry", {}) or {}
        if not isinstance(registry, dict):
            return {}
        return {
            tool_name: self.normalize_registry_entry(tool_name, entry)
            for tool_name, entry in registry.items()
        }

    def get_registry_entry(self, tool_name: str) -> dict[str, Any]:
        entry = self.get_registry().get(tool_name, {})
        return entry if isinstance(entry, dict) else {}

    def get_tool_transport_protocol(self, tool_name: str) -> Optional[str]:
        entry = self.get_registry_entry(tool_name)
        protocol = entry.get("transport_protocol")
        return str(protocol) if protocol else None

    def get_tool_origin(self, tool_name: str) -> Optional[str]:
        entry = self.get_registry_entry(tool_name)
        origin = entry.get("tool_origin")
        return str(origin) if origin else None

    def get_tool_class_path(self, tool_name: str) -> Optional[str]:
        entry = self.get_registry_entry(tool_name)
        implementation = entry.get("implementation") if isinstance(entry.get("implementation"), dict) else {}
        class_path = implementation.get("class_path")
        return str(class_path) if class_path else None

    def get_mcp_settings(self) -> dict[str, Any]:
        settings = self.config_manager.get_tool_config("mcp", {}) or {}
        return settings if isinstance(settings, dict) else {}

    def get_mcp_servers(self) -> dict[str, dict[str, Any]]:
        servers = self.get_mcp_settings().get("servers", {})
        return servers if isinstance(servers, dict) else {}

    def is_tool_enabled(self, tool_name: str) -> bool:
        entry = self.get_registry_entry(tool_name)
        return bool(entry) and bool(entry.get("enabled", True))

    def is_tool_exposed_to_agent(self, tool_name: str) -> bool:
        entry = self.get_registry_entry(tool_name)
        if not entry:
            return False
        if not entry.get("enabled", True):
            return False
        return bool(entry.get("expose_to_agent", True))

    def get_enabled_tool_names(
        self,
        tool_type: Optional[str] = None,
        expose_to_agent_only: bool = False,
    ) -> list[str]:
        enabled_names: list[str] = []
        for tool_name, entry in self.get_registry().items():
            if not isinstance(entry, dict) or not entry.get("enabled", True):
                continue
            if tool_type:
                if tool_type not in {entry.get("transport_protocol"), entry.get("tool_origin")}:
                    continue
            if expose_to_agent_only and not entry.get("expose_to_agent", True):
                continue
            enabled_names.append(tool_name)
        return enabled_names

    def set(self, tool_name: str, key: str, value: Any) -> None:
        tool_override = self._runtime_overrides.setdefault(tool_name, {})
        tool_override[key] = value

    def validate_config(self, tool_name: str) -> tuple[bool, Optional[str]]:
        config = self.get_all(tool_name)
        if config and not isinstance(config, dict):
            return False, f"工具 {tool_name} 的配置必须是对象类型"

        entry = self.get_registry_entry(tool_name)
        if not entry:
            return True, None
        if not isinstance(entry, dict):
            return False, f"工具 {tool_name} 的注册配置必须是对象类型"
        if entry.get("enabled", True) and entry.get("transport_protocol") != "mcp":
            return False, f"工具 {tool_name} transport_protocol 必须为 mcp"
        if entry.get("enabled", True) and not entry.get("mcp_server"):
            return False, f"工具 {tool_name} 缺少 mcp_server 配置"
        if entry.get("enabled", True) and not self.get_tool_class_path(tool_name):
            return False, f"工具 {tool_name} 缺少 implementation.class_path 配置"
        timeout = config.get("timeout")
        if timeout is not None and (not isinstance(timeout, int) or timeout <= 0):
            return False, f"工具 {tool_name} 的 timeout 必须是正整数"
        return True, None

    def __repr__(self) -> str:
        return f"ToolConfig(tools={list(self.get_registry().keys())})"


_tool_config: Optional[ToolConfig] = None


def get_tool_config() -> ToolConfig:
    global _tool_config
    if _tool_config is None:
        _tool_config = ToolConfig()
    return _tool_config
