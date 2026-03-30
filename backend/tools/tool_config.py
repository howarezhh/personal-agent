"""Tool 配置访问与治理层。"""

from __future__ import annotations

from copy import deepcopy
from typing import Any, Optional

from backend.contracts.tools import ToolOrigin, ToolTransportProtocol
from backend.core.config_manager import get_config_manager


class ToolConfig:
    """统一 Tool 配置读取、归一化与校验。"""

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
        self._runtime_registry_overrides: dict[str, dict[str, Any]] = {}
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

    def get_schema(self) -> dict[str, Any]:
        schema = self.config_manager.get("schema.tools", {}) or {}
        return schema if isinstance(schema, dict) else {}

    def _get_registry_entry_schema(self) -> dict[str, Any]:
        schema = self.get_schema().get("registry_entry", {})
        return schema if isinstance(schema, dict) else {}

    def _get_schema_enum(self, field_name: str, fallback: set[str]) -> set[str]:
        properties = self._get_registry_entry_schema().get("properties", {})
        if not isinstance(properties, dict):
            return fallback
        field_schema = properties.get(field_name, {})
        if not isinstance(field_schema, dict):
            return fallback
        enum_values = field_schema.get("enum")
        if not isinstance(enum_values, list) or not enum_values:
            return fallback
        return {str(item) for item in enum_values}

    def _get_schema_required_fields(self) -> set[str]:
        schema = self._get_registry_entry_schema()
        required = schema.get("required", [])
        if not isinstance(required, list):
            return set()
        return {str(item) for item in required}

    def _get_common_defaults(self) -> dict[str, Any]:
        common = self.config_manager.get_tool_config("common", {}) or {}
        return common if isinstance(common, dict) else {}

    def normalize_registry_entry(self, tool_name: str, entry: Any) -> dict[str, Any]:
        if not isinstance(entry, dict):
            return {}

        normalized = deepcopy(entry)
        implementation = normalized.get("implementation") if isinstance(normalized.get("implementation"), dict) else {}
        class_path = implementation.get("class_path")
        common_defaults = self._get_common_defaults()
        tool_runtime_config = self.get_all(tool_name)
        transport_protocol = normalized.get("transport_protocol") or ToolTransportProtocol.LOCAL_DIRECT.value
        tool_origin = normalized.get("tool_origin") or ToolOrigin.LOCAL.value
        timeout = normalized.get("timeout")
        if timeout is None:
            timeout = tool_runtime_config.get("timeout", common_defaults.get("default_timeout", 30))
        retry = normalized.get("retry")
        if retry is None:
            retry = tool_runtime_config.get("retry", common_defaults.get("max_retries", 0))

        normalized["enabled"] = bool(normalized.get("enabled", True))
        normalized["expose_to_agent"] = bool(normalized.get("expose_to_agent", True))
        normalized["transport_protocol"] = str(transport_protocol)
        normalized["tool_origin"] = str(tool_origin)
        normalized["timeout"] = int(timeout) if timeout is not None else 30
        normalized["retry"] = int(retry) if retry is not None else 0
        normalized["mcp_server"] = normalized.get("mcp_server")
        normalized["implementation"] = {
            **implementation,
            **({"class_path": class_path} if class_path else {}),
        }
        return normalized

    def get_registry(self) -> dict[str, dict[str, Any]]:
        registry = self.config_manager.get_tool_config("registry", {}) or {}
        if not isinstance(registry, dict):
            return {}
        merged_registry = {**registry, **self._runtime_registry_overrides}
        return {
            tool_name: self.normalize_registry_entry(tool_name, entry)
            for tool_name, entry in merged_registry.items()
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

    @staticmethod
    def _requires_local_implementation(entry: dict[str, Any]) -> bool:
        protocol = entry.get("transport_protocol")
        mcp_server = entry.get("mcp_server")
        if protocol == ToolTransportProtocol.LOCAL_DIRECT.value:
            return True
        if protocol == ToolTransportProtocol.MCP.value and mcp_server == "builtin":
            return True
        return False

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

    def get_enabled_tool_names(self, tool_type: Optional[str] = None, expose_to_agent_only: bool = False) -> list[str]:
        enabled_names: list[str] = []
        for tool_name, entry in self.get_registry().items():
            if not isinstance(entry, dict) or not entry.get("enabled", True):
                continue
            if tool_type and tool_type not in {entry.get("transport_protocol"), entry.get("tool_origin")}:
                continue
            if expose_to_agent_only and not entry.get("expose_to_agent", True):
                continue
            enabled_names.append(tool_name)
        return enabled_names

    def set(self, tool_name: str, key: str, value: Any) -> None:
        tool_override = self._runtime_overrides.setdefault(tool_name, {})
        tool_override[key] = value

    def set_registry_entry(self, tool_name: str, entry: dict[str, Any]) -> None:
        self._runtime_registry_overrides[tool_name] = dict(entry)

    def clear_runtime_registry_overrides(self) -> None:
        """清空运行时动态注册项，避免远端发现结果跨次初始化残留。"""

        self._runtime_registry_overrides.clear()

    def clear_runtime_overrides(self) -> None:
        """清空运行时配置覆盖项，便于 force re-init 回到文件配置基线。"""

        self._runtime_overrides.clear()

    def validate_config(self, tool_name: str) -> tuple[bool, Optional[str]]:
        entry = self.get_registry_entry(tool_name)
        if not entry:
            return True, None
        if not isinstance(entry, dict):
            return False, f"工具 {tool_name} 的注册配置必须是对象类型"

        required_fields = self._get_schema_required_fields()
        if "implementation" in required_fields and not self._requires_local_implementation(entry):
            required_fields.remove("implementation")
        for field_name in required_fields:
            if field_name not in entry:
                return False, f"工具 {tool_name} 缺少必填字段: {field_name}"

        allowed_protocols = self._get_schema_enum(
            "transport_protocol",
            {ToolTransportProtocol.MCP.value, ToolTransportProtocol.LOCAL_DIRECT.value},
        )
        allowed_origins = self._get_schema_enum(
            "tool_origin",
            {ToolOrigin.LOCAL.value, ToolOrigin.EXTERNAL.value},
        )
        protocol = entry.get("transport_protocol")
        origin = entry.get("tool_origin")
        timeout = entry.get("timeout")
        retry = entry.get("retry")

        if protocol not in allowed_protocols:
            return False, f"工具 {tool_name} transport_protocol 非法: {protocol}"
        if origin not in allowed_origins:
            return False, f"工具 {tool_name} tool_origin 非法: {origin}"
        if self._requires_local_implementation(entry) and not self.get_tool_class_path(tool_name):
            return False, f"工具 {tool_name} 缺少 implementation.class_path 配置"
        if not isinstance(timeout, int) or timeout <= 0:
            return False, f"工具 {tool_name} 的 timeout 必须是正整数"
        if not isinstance(retry, int) or retry < 0:
            return False, f"工具 {tool_name} 的 retry 必须是非负整数"
        if protocol == ToolTransportProtocol.MCP.value and not entry.get("mcp_server"):
            return False, f"工具 {tool_name} 缺少 mcp_server 配置"
        return True, None

    def __repr__(self) -> str:
        return f"ToolConfig(tools={list(self.get_registry().keys())})"


_tool_config: Optional[ToolConfig] = None


def get_tool_config() -> ToolConfig:
    global _tool_config
    if _tool_config is None:
        _tool_config = ToolConfig()
    return _tool_config
