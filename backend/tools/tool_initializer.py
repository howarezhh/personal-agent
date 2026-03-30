"""Tool 运行时初始化器。"""

from __future__ import annotations

import asyncio
import importlib
import logging
from threading import Lock, Thread
from typing import Any, Awaitable

from backend.contracts.tools import ToolCapability, ToolDescriptor, ToolLifecycleStatus, ToolOrigin, ToolTransportProtocol
from backend.infrastructure.mcp import get_mcp_server_manager
from backend.tools.adapters.local_tool_adapter import LocalToolAdapter
from backend.tools.adapters.mcp_tool_adapter import MCPToolAdapter
from backend.tools.base_tool import BaseTool
from backend.tools.tool_config import get_tool_config
from backend.tools.tool_registry import get_tool_registry, register_tool


logger = logging.getLogger(__name__)
_initialized = False
_initialization_lock = Lock()
MCP_TOOL_META_NAMESPACE = "personal-agent"


def _collect_origin_metrics(all_tools) -> dict[str, int]:
    tools = list(all_tools)
    mcp_transport_count = len([tool for tool in tools if tool.get_transport_protocol() == ToolTransportProtocol.MCP.value])
    local_direct_count = len([tool for tool in tools if tool.get_transport_protocol() == ToolTransportProtocol.LOCAL_DIRECT.value])
    local_origin_count = len([tool for tool in tools if tool.get_tool_origin() == ToolOrigin.LOCAL.value])
    external_origin_count = len([tool for tool in tools if tool.get_tool_origin() == ToolOrigin.EXTERNAL.value])
    return {
        "registered_count": len(tools),
        "mcp_transport_count": mcp_transport_count,
        "local_direct_count": local_direct_count,
        "local_origin_count": local_origin_count,
        "external_origin_count": external_origin_count,
    }


def _build_report(registry) -> dict[str, Any]:
    metrics = _collect_origin_metrics(registry.get_all_tools().values())
    return {
        "initialized": True,
        "cached": True,
        **metrics,
        "failures": [],
        "skipped": [],
    }


def _run_async(coroutine: Awaitable[Any]) -> Any:
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return asyncio.run(coroutine)

    result_holder: dict[str, Any] = {}
    error_holder: dict[str, BaseException] = {}

    def _runner() -> None:
        try:
            result_holder["result"] = asyncio.run(coroutine)
        except BaseException as error:  # pragma: no cover
            error_holder["error"] = error

    thread = Thread(target=_runner, daemon=True)
    thread.start()
    thread.join()

    if "error" in error_holder:
        raise error_holder["error"]
    return result_holder.get("result")


def _load_tool_class(class_path: str) -> type[BaseTool]:
    module_path, class_name = class_path.rsplit(".", 1)
    module = importlib.import_module(module_path)
    tool_class = getattr(module, class_name)
    if not issubclass(tool_class, BaseTool):
        raise TypeError(f"{class_path} is not a BaseTool subclass")
    return tool_class


def _get_enabled_registry_tools(config) -> dict[str, dict[str, Any]]:
    return {
        tool_name: entry
        for tool_name, entry in config.get_registry().items()
        if isinstance(entry, dict) and entry.get("enabled", True)
    }


def _extract_tool_runtime_meta(tool_info: dict[str, Any]) -> dict[str, Any]:
    annotations = tool_info.get("annotations") if isinstance(tool_info.get("annotations"), dict) else {}
    meta = tool_info.get("_meta") if isinstance(tool_info.get("_meta"), dict) else {}
    namespaced_meta = meta.get(MCP_TOOL_META_NAMESPACE) if isinstance(meta.get(MCP_TOOL_META_NAMESPACE), dict) else {}
    if namespaced_meta:
        merged_meta = dict(annotations)
        merged_meta.update(namespaced_meta)
        return merged_meta
    return annotations


async def _register_local_tools(config, registry, configured_tools: dict[str, dict[str, Any]], strict: bool) -> tuple[list[dict[str, str]], list[str], set[str]]:
    failures: list[dict[str, str]] = []
    skipped: list[str] = []
    registered_tool_names: set[str] = set()

    for tool_name, entry in configured_tools.items():
        if entry.get("transport_protocol") != ToolTransportProtocol.LOCAL_DIRECT.value:
            continue
        is_valid, config_error = config.validate_config(tool_name)
        if not is_valid:
            failure = {"tool_name": tool_name, "reason": config_error or "invalid config"}
            failures.append(failure)
            if strict:
                raise RuntimeError(failure["reason"])
            continue
        if registry.is_tool_available(tool_name):
            skipped.append(tool_name)
            continue
        class_path = config.get_tool_class_path(tool_name)
        if not class_path:
            failure = {"tool_name": tool_name, "reason": "missing implementation.class_path"}
            failures.append(failure)
            if strict:
                raise RuntimeError(failure["reason"])
            continue
        try:
            tool_class = _load_tool_class(class_path)
            tool_instance = tool_class()
            adapter = LocalToolAdapter(tool_instance)
            register_tool(adapter)
            await adapter.initialize()
            adapter.set_lifecycle_status(ToolLifecycleStatus.AVAILABLE)
            registered_tool_names.add(tool_name)
            logger.info("Local tool registered: tool=%s transport=%s", tool_name, adapter.get_transport_protocol())
        except Exception as error:
            failure = {"tool_name": tool_name, "reason": f"local registration failed: {error}"}
            failures.append(failure)
            logger.error("Local tool registration failed: %s", failure, exc_info=True)
            if strict:
                raise RuntimeError(failure["reason"]) from error
    return failures, skipped, registered_tool_names


def _build_mcp_descriptor(tool_name: str, tool_info: dict[str, Any], registry_entry: dict[str, Any], server_name: str, mcp_timeout: int) -> ToolDescriptor:
    tool_runtime_meta = _extract_tool_runtime_meta(tool_info)
    capabilities = tool_runtime_meta.get("capabilities") if isinstance(tool_runtime_meta.get("capabilities"), list) else []
    if not capabilities:
        capabilities = [ToolCapability.INVOKE.value, ToolCapability.MCP_PROXY.value]
    input_schema = tool_info.get("inputSchema") if isinstance(tool_info.get("inputSchema"), dict) else {"type": "object", "properties": {}}
    output_schema = tool_info.get("outputSchema") if isinstance(tool_info.get("outputSchema"), dict) else {}
    if not output_schema:
        output_schema = tool_runtime_meta.get("output_schema") if isinstance(tool_runtime_meta.get("output_schema"), dict) else {}
    timeout = tool_runtime_meta.get("timeout") if isinstance(tool_runtime_meta.get("timeout"), int) else registry_entry.get("timeout", mcp_timeout)
    return ToolDescriptor(
        name=tool_name,
        description=str(tool_info.get("description") or registry_entry.get("description") or ""),
        category=str(tool_runtime_meta.get("category") or registry_entry.get("category") or "general"),
        version=str(tool_runtime_meta.get("version") or registry_entry.get("version") or "1.0.0"),
        input_schema=input_schema,
        output_schema=output_schema,
        timeout=int(timeout),
        capabilities=[str(item) for item in capabilities],
        transport_protocol=ToolTransportProtocol.MCP.value,
        tool_origin=str(tool_runtime_meta.get("tool_origin") or registry_entry.get("tool_origin") or ToolOrigin.LOCAL.value),
        mcp_server=str(tool_runtime_meta.get("mcp_server") or registry_entry.get("mcp_server") or server_name),
    )


def _build_dynamic_mcp_registry_entry(tool_name: str, tool_info: dict[str, Any], server_name: str, mcp_timeout: int) -> dict[str, Any]:
    tool_runtime_meta = _extract_tool_runtime_meta(tool_info)
    timeout = tool_runtime_meta.get("timeout") if isinstance(tool_runtime_meta.get("timeout"), int) else mcp_timeout
    return {
        "enabled": True,
        "transport_protocol": ToolTransportProtocol.MCP.value,
        "tool_origin": str(tool_runtime_meta.get("tool_origin") or ToolOrigin.EXTERNAL.value),
        "timeout": int(timeout),
        "retry": 0,
        "mcp_server": str(tool_runtime_meta.get("mcp_server") or server_name),
        # 中文说明：远端动态发现工具默认不直接暴露给 Agent，避免未治理能力自动扩权。
        "expose_to_agent": False,
        "implementation": {},
        "description": str(tool_info.get("description") or ""),
        "category": str(tool_runtime_meta.get("category") or "general"),
        "version": str(tool_runtime_meta.get("version") or "1.0.0"),
    }


async def _register_mcp_tools(config, registry, configured_tools: dict[str, dict[str, Any]], strict: bool) -> tuple[list[dict[str, str]], list[str], set[str]]:
    mcp_settings = config.get_mcp_settings()
    mcp_timeout = int(mcp_settings.get("timeout", 30) or 30)
    server_configs = {
        server_name: entry
        for server_name, entry in config.get_mcp_servers().items()
        if isinstance(entry, dict) and entry.get("enabled", True)
    }
    failures: list[dict[str, str]] = []
    skipped: list[str] = []
    registered_tool_names: set[str] = set()

    if not server_configs:
        return failures, skipped, registered_tool_names

    manager = get_mcp_server_manager()
    for server_name, server_config in server_configs.items():
        try:
            client = await manager.open_session(server_name, server_config, timeout=mcp_timeout)
        except Exception as error:
            failure = {"tool_name": server_name, "reason": f"MCP session open failed: {error}"}
            failures.append(failure)
            logger.error("MCP server open failed: %s", failure, exc_info=True)
            if strict:
                raise RuntimeError(failure["reason"]) from error
            continue

        try:
            discovered_tools = await client.list_tools()
            logger.info("MCP tools discovered: server=%s count=%s", server_name, len(discovered_tools))
            for tool_info in discovered_tools:
                tool_name = tool_info.get("name") if isinstance(tool_info, dict) else None
                if not tool_name:
                    skipped.append(f"{server_name}:<missing-name>")
                    continue

                registry_entry = configured_tools.get(tool_name)
                if registry_entry is None:
                    if server_name == "builtin":
                        skipped.append(f"{server_name}:{tool_name}")
                        continue
                    registry_entry = _build_dynamic_mcp_registry_entry(tool_name, tool_info, server_name, mcp_timeout)
                    config.set_registry_entry(tool_name, registry_entry)
                    configured_tools[tool_name] = registry_entry
                elif registry_entry.get("transport_protocol") != ToolTransportProtocol.MCP.value:
                    skipped.append(f"{server_name}:{tool_name}")
                    continue
                bound_server = registry_entry.get("mcp_server")
                if bound_server and bound_server != server_name:
                    skipped.append(f"{server_name}:{tool_name}")
                    continue
                is_valid, config_error = config.validate_config(tool_name)
                if not is_valid:
                    failure = {"tool_name": tool_name, "reason": config_error or "invalid config"}
                    failures.append(failure)
                    if strict:
                        raise RuntimeError(failure["reason"])
                    continue
                if registry.is_tool_available(tool_name):
                    skipped.append(tool_name)
                    continue

                descriptor = _build_mcp_descriptor(tool_name, tool_info, registry_entry, server_name, mcp_timeout)
                adapter = MCPToolAdapter(descriptor=descriptor, server_name=server_name, server_config=server_config)
                register_tool(adapter)
                await adapter.initialize()
                adapter.set_lifecycle_status(ToolLifecycleStatus.AVAILABLE)
                registered_tool_names.add(tool_name)
                logger.info("MCP tool registered: server=%s tool=%s", server_name, tool_name)
        except Exception:
            raise
        finally:
            await client.close()
    return failures, skipped, registered_tool_names


async def _discover_and_register_tools(strict: bool = False) -> dict[str, Any]:
    config = get_tool_config()
    registry = get_tool_registry()
    configured_tools = _get_enabled_registry_tools(config)

    if not configured_tools and not config.get_mcp_servers():
        logger.warning("No enabled tools configured in tools.registry")
        return {
            "initialized": True,
            "registered_count": 0,
            "mcp_transport_count": 0,
            "local_direct_count": 0,
            "local_origin_count": 0,
            "external_origin_count": 0,
            "failures": [],
            "skipped": [],
        }

    local_failures, local_skipped, local_registered = await _register_local_tools(config, registry, configured_tools, strict)
    mcp_failures, mcp_skipped, mcp_registered = await _register_mcp_tools(config, registry, configured_tools, strict)

    registered_tool_names = set(local_registered) | set(mcp_registered)
    missing_tools = sorted(set(configured_tools.keys()) - registered_tool_names)
    failures = local_failures + mcp_failures
    skipped = local_skipped + mcp_skipped
    for tool_name in missing_tools:
        if registry.is_tool_available(tool_name):
            continue
        failure = {"tool_name": tool_name, "reason": "tool not registered by runtime adapter"}
        failures.append(failure)
        logger.error("Configured tool missing from runtime registration: %s", failure)

    metrics = _collect_origin_metrics(registry.get_all_tools().values())
    report = {
        "initialized": True,
        **metrics,
        "failures": failures,
        "skipped": skipped,
    }

    if strict and failures:
        first_failure = failures[0]
        raise RuntimeError(f"tool initialization failed: {first_failure['tool_name']} - {first_failure['reason']}")
    return report


async def close_registered_tools() -> None:
    registry = get_tool_registry()
    for adapter in registry.get_all_tools().values():
        close_method = getattr(adapter, "close", None)
        if callable(close_method):
            await close_method()


def initialize_tools(force: bool = False, strict: bool = False) -> dict[str, Any]:
    global _initialized

    with _initialization_lock:
        registry = get_tool_registry()
        config = get_tool_config()
        if force:
            _run_async(close_registered_tools())
            _run_async(close_initialized_tool_clients())
            registry.clear()
            config.clear_runtime_overrides()
            config.clear_runtime_registry_overrides()
            _initialized = False

        if _initialized and registry.get_tool_count() > 0 and not force:
            return _build_report(registry)

        report = _run_async(_discover_and_register_tools(strict=strict))
        _initialized = True
        return report


def ensure_tools_initialized(strict: bool = False) -> dict[str, Any]:
    registry = get_tool_registry()
    if registry.get_tool_count() > 0 and _initialized:
        return _build_report(registry)
    return initialize_tools(strict=strict)


async def close_initialized_tool_clients() -> None:
    await get_mcp_server_manager().close_all()
