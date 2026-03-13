"""Tool configuration facade backed by ConfigManager."""

from typing import Any, Optional

from backend.core.config_manager import get_config_manager


class ToolConfig:
    _instance: Optional["ToolConfig"] = None

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance

    def __init__(self):
        self.config_manager = get_config_manager()

    def get(self, tool_name: str, key: str, default: Any = None) -> Any:
        return self.config_manager.get(f"tools.{tool_name}.{key}", default)

    def get_all(self, tool_name: str) -> dict[str, Any]:
        return self.config_manager.get(f"tools.{tool_name}", {}) or {}

    def get_registry(self) -> dict[str, dict[str, Any]]:
        registry = self.config_manager.get("tools.registry", {}) or {}
        return registry if isinstance(registry, dict) else {}

    def get_enabled_tool_names(self, tool_type: Optional[str] = None, expose_to_agent_only: bool = False):
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

    def set(self, tool_name: str, key: str, value: Any):
        tools_config = self.config_manager._configs.setdefault("tools", {})
        tool_config = tools_config.setdefault(tool_name, {})
        tool_config[key] = value

    def validate_config(self, tool_name: str) -> tuple[bool, Optional[str]]:
        config = self.get_all(tool_name)
        if tool_name in {"weather", "web_search"} and not config.get("api_key"):
            return False, f"{tool_name} api_key missing"
        return True, None

    def __repr__(self) -> str:
        return f"ToolConfig(tools={list(self.get_registry().keys())})"


_tool_config: Optional[ToolConfig] = None


def get_tool_config() -> ToolConfig:
    global _tool_config
    if _tool_config is None:
        _tool_config = ToolConfig()
    return _tool_config
