"""工具初始化模块。

该模块负责在系统启动或工具子系统被显式调用时，根据配置动态加载工具类，
创建对应实例，并注册到全局工具注册表中。

核心职责：
1. 根据类路径动态导入工具类。
2. 读取配置，批量初始化已启用工具。
3. 区分本地工具与 MCP 工具，并记录初始化日志。
4. 输出初始化报告，支持幂等重复调用。
"""

from __future__ import annotations

import logging
from importlib import import_module
from typing import Any

from backend.tools.base_tool import BaseTool
from backend.tools.tool_config import get_tool_config
from backend.tools.tool_registry import get_tool_registry, register_tool


logger = logging.getLogger(__name__)
_initialized = False


def _load_tool_class(class_path: str) -> type[BaseTool]:
    """根据完整类路径动态加载工具类。"""

    module_path, class_name = class_path.rsplit(".", 1)
    module = import_module(module_path)
    tool_class = getattr(module, class_name)
    if not issubclass(tool_class, BaseTool):
        raise TypeError(f"{class_path} 不是 BaseTool 子类")
    return tool_class


def initialize_tools(force: bool = False, strict: bool = False) -> dict[str, Any]:
    """初始化并注册所有已启用工具。

    参数：
    - ``force=True`` 时，会先清空注册表，再重新初始化。
    - ``strict=True`` 时，任意工具初始化失败都会抛出异常。
    """

    global _initialized

    config = get_tool_config()
    registry = get_tool_registry()

    if force:
        registry.clear()
        _initialized = False

    if _initialized and registry.get_tool_count() > 0 and not force:
        return {
            "initialized": True,
            "local_count": len([tool for tool in registry.get_all_tools().values() if tool.get_category() != "mcp"]),
            "mcp_count": len([tool for tool in registry.get_all_tools().values() if tool.get_category() == "mcp"]),
            "failures": [],
            "skipped": registry.get_tool_names(),
        }

    configured_tools = config.get_registry()
    if not configured_tools:
        logger.warning("未找到 tools.registry 配置，跳过工具初始化")
        _initialized = True
        return {
            "initialized": True,
            "local_count": 0,
            "mcp_count": 0,
            "failures": [],
            "skipped": [],
        }

    logger.info("开始初始化所有工具")

    local_count = 0
    mcp_count = 0
    failures: list[dict[str, str]] = []
    skipped: list[str] = []

    for expected_name, entry in configured_tools.items():
        if not isinstance(entry, dict) or not entry.get("enabled", True):
            continue

        is_valid, error = config.validate_config(expected_name)
        if not is_valid:
            failure = {"tool_name": expected_name, "reason": error or "配置无效"}
            failures.append(failure)
            logger.error("工具配置校验失败: %s", failure)
            if strict:
                raise ValueError(failure["reason"])
            continue

        if registry.is_tool_available(expected_name):
            skipped.append(expected_name)
            logger.debug("工具已存在，跳过重复注册: %s", expected_name)
            continue

        class_path = entry.get("class_path")
        tool_type = entry.get("type", "local")

        try:
            tool_class = _load_tool_class(class_path)
            tool_instance = tool_class()
            actual_name = tool_instance.get_name()
            if actual_name != expected_name:
                raise ValueError(f"配置工具名 {expected_name} 与实现工具名 {actual_name} 不一致")

            register_tool(tool_instance)

            if tool_type == "mcp":
                mcp_count += 1
                logger.info("MCP工具已注册: %s", actual_name)
            else:
                local_count += 1
                logger.info("本地工具已注册: %s", actual_name)
        except Exception as exc:
            failure = {"tool_name": expected_name, "reason": str(exc)}
            failures.append(failure)
            logger.error("工具初始化失败: %s", failure, exc_info=True)
            if strict:
                raise

    _initialized = True
    report = {
        "initialized": True,
        "local_count": local_count,
        "mcp_count": mcp_count,
        "failures": failures,
        "skipped": skipped,
    }
    logger.info(
        "工具初始化完成（本地工具%s个，MCP工具%s个，失败%s个）",
        local_count,
        mcp_count,
        len(failures),
    )
    return report


def ensure_tools_initialized(strict: bool = False) -> dict[str, Any]:
    """确保工具注册表已完成初始化。"""

    registry = get_tool_registry()
    if registry.get_tool_count() > 0 and _initialized:
        return {
            "initialized": True,
            "local_count": len([tool for tool in registry.get_all_tools().values() if tool.get_category() != "mcp"]),
            "mcp_count": len([tool for tool in registry.get_all_tools().values() if tool.get_category() == "mcp"]),
            "failures": [],
            "skipped": registry.get_tool_names(),
        }
    return initialize_tools(strict=strict)
