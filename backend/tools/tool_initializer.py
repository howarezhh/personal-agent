"""Tool runtime initializer.

运行时工具注册统一走标准 MCP discovery：
- initialize
- notifications/initialized
- tools/list
- tools/call

`tools.registry` 是唯一权威来源；host 不再按 `class_path` 直接导入并注册工具，
而是只消费 MCP server 暴露出来的标准 tools list，再注册为 `MCPProxyTool`。
"""

from __future__ import annotations

import asyncio
import logging
from threading import Lock, Thread
from typing import Any, Awaitable

from backend.tools.mcp.proxy_tool import MCPProxyTool
from backend.tools.mcp.server_manager import get_mcp_server_manager
from backend.tools.tool_config import get_tool_config
from backend.tools.tool_registry import get_tool_registry, register_tool


logger = logging.getLogger(__name__)
_initialized = False
_initialization_lock = Lock()


def _collect_origin_metrics(all_tools) -> dict[str, int]:
    tools = list(all_tools)
    mcp_transport_count = len([tool for tool in tools if tool.get_transport_protocol() == "mcp"])
    local_origin_count = len([tool for tool in tools if tool.get_tool_origin() == "local"])
    external_origin_count = len([tool for tool in tools if tool.get_tool_origin() == "external"])
    return {
        "registered_count": len(tools),
        "mcp_transport_count": mcp_transport_count,
        "local_origin_count": local_origin_count,
        "external_origin_count": external_origin_count,
        "local_count": local_origin_count,
        "mcp_count": mcp_transport_count,
    }


def _build_report(registry) -> dict[str, Any]:
    metrics = _collect_origin_metrics(registry.get_all_tools().values())
    return {
        "initialized": True,
        **metrics,
        "failures": [],
        "skipped": registry.get_tool_names(),
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


def _get_enabled_registry_tools(config) -> dict[str, dict[str, Any]]:
    return {
        tool_name: entry
        for tool_name, entry in config.get_registry().items()
        if isinstance(entry, dict) and entry.get("enabled", True)
    }


async def _discover_and_register_tools(strict: bool = False) -> dict[str, Any]:
    config = get_tool_config()
    registry = get_tool_registry()
    configured_tools = _get_enabled_registry_tools(config)

    if not configured_tools:
        logger.warning("No enabled tools configured in tools.registry")
        return {
            "initialized": True,
            "registered_count": 0,
            "mcp_transport_count": 0,
            "local_origin_count": 0,
            "external_origin_count": 0,
            "local_count": 0,
            "mcp_count": 0,
            "failures": [],
            "skipped": [],
        }

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
        message = "No enabled MCP servers configured in tools.mcp.servers"
        logger.error(message)
        failure = {"tool_name": "__mcp_servers__", "reason": message}
        failures.append(failure)
        if strict:
            raise RuntimeError(message)
        return {
            "initialized": True,
            "registered_count": 0,
            "mcp_transport_count": 0,
            "local_origin_count": 0,
            "external_origin_count": 0,
            "local_count": 0,
            "mcp_count": 0,
            "failures": failures,
            "skipped": skipped,
        }

    logger.info("Initializing tools via MCP discovery")
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
                    logger.warning("MCP tool missing name: server=%s", server_name)
                    continue

                registry_entry = configured_tools.get(tool_name)
                if registry_entry is None:
                    skipped.append(f"{server_name}:{tool_name}")
                    logger.warning(
                        "MCP tool not declared in tools.registry: server=%s tool=%s",
                        server_name,
                        tool_name,
                    )
                    continue

                bound_server = registry_entry.get("mcp_server")
                if bound_server and bound_server != server_name:
                    skipped.append(f"{server_name}:{tool_name}")
                    logger.warning(
                        "MCP tool bound to different server: expected=%s actual=%s tool=%s",
                        bound_server,
                        server_name,
                        tool_name,
                    )
                    continue

                is_valid, config_error = config.validate_config(tool_name)
                if not is_valid:
                    failure = {"tool_name": tool_name, "reason": config_error or "invalid config"}
                    failures.append(failure)
                    logger.error("Tool config invalid: %s", failure)
                    if strict:
                        raise RuntimeError(failure["reason"])
                    continue

                if registry.is_tool_available(tool_name):
                    skipped.append(tool_name)
                    logger.debug("Tool already registered, skip duplicate: %s", tool_name)
                    continue

                input_schema = tool_info.get("inputSchema")
                if not isinstance(input_schema, dict):
                    input_schema = {"type": "object", "properties": {}}

                description = str(tool_info.get("description") or registry_entry.get("description") or "")
                annotations = tool_info.get("annotations") if isinstance(tool_info.get("annotations"), dict) else {}
                tool_category = str(annotations.get("category") or registry_entry.get("category") or "general")
                transport_protocol = str(
                    annotations.get("transport_protocol")
                    or registry_entry.get("transport_protocol")
                    or "mcp"
                )
                tool_origin = str(
                    annotations.get("tool_origin")
                    or registry_entry.get("tool_origin")
                    or "local"
                )
                tool_timeout = annotations.get("timeout")
                if not isinstance(tool_timeout, int) or tool_timeout <= 0:
                    tool_timeout = mcp_timeout

                proxy_tool = MCPProxyTool(
                    server_name=server_name,
                    server_config=server_config,
                    tool_name=tool_name,
                    description=description,
                    input_schema=input_schema,
                    category=tool_category,
                    transport_protocol=transport_protocol,
                    tool_origin=tool_origin,
                    timeout=tool_timeout,
                )
                register_tool(proxy_tool)
                registered_tool_names.add(tool_name)
                logger.info(
                    "MCP proxy tool registered: server=%s tool=%s category=%s transport=%s origin=%s",
                    server_name,
                    tool_name,
                    tool_category,
                    transport_protocol,
                    tool_origin,
                )
        except Exception:
            raise
        finally:
            await client.close()

    missing_tools = sorted(set(configured_tools.keys()) - registered_tool_names)
    for tool_name in missing_tools:
        if registry.is_tool_available(tool_name):
            continue
        failure = {"tool_name": tool_name, "reason": "tool not returned by MCP tools/list"}
        failures.append(failure)
        logger.error("Configured tool missing from MCP discovery: %s", failure)

    metrics = _collect_origin_metrics(registry.get_all_tools().values())
    report = {
        "initialized": True,
        **metrics,
        "failures": failures,
        "skipped": skipped,
    }

    logger.info(
        "Tool initialization finished: registered=%s mcp_transport=%s local_origin=%s external_origin=%s failures=%s",
        report["registered_count"],
        report["mcp_transport_count"],
        report["local_origin_count"],
        report["external_origin_count"],
        len(report["failures"]),
    )

    if strict and failures:
        first_failure = failures[0]
        raise RuntimeError(f"tool initialization failed: {first_failure['tool_name']} - {first_failure['reason']}")

    return report


def initialize_tools(force: bool = False, strict: bool = False) -> dict[str, Any]:
    global _initialized

    with _initialization_lock:
        registry = get_tool_registry()

        if force:
            _run_async(close_initialized_tool_clients())
            registry.clear()
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
