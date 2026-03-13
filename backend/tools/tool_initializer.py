"""
工具初始化模块
统一注册所有可用工具（本地工具和MCP工具）
"""

from importlib import import_module

from backend.tools.tool_config import get_tool_config
from backend.tools.tool_registry import get_tool_registry, register_tool

import logging

logger = logging.getLogger(__name__)

DEFAULT_TOOL_REGISTRY = {
    "calculator": {
        "enabled": True,
        "type": "local",
        "class_path": "backend.tools.calculator.calculator_tool.CalculatorTool",
    },
    "web_search": {
        "enabled": True,
        "type": "local",
        "class_path": "backend.tools.web_search.web_search_tool.WebSearchTool",
    },
    "database_query": {
        "enabled": True,
        "type": "local",
        "class_path": "backend.tools.database_query.database_query_tool.DatabaseQueryTool",
    },
    "translation": {
        "enabled": True,
        "type": "local",
        "class_path": "backend.tools.translation.translation_tool.TranslationTool",
    },
    "datetime": {
        "enabled": True,
        "type": "local",
        "class_path": "backend.tools.datetime.datetime_tool.DateTimeTool",
    },
    "novel_generator": {
        "enabled": True,
        "type": "local",
        "class_path": "backend.tools.novel_generator.novel_generator_tool.NovelGeneratorTool",
    },
    "script_generator": {
        "enabled": True,
        "type": "local",
        "class_path": "backend.tools.script_generator.script_generator_tool.ScriptGeneratorTool",
    },
    "content_optimizer": {
        "enabled": True,
        "type": "local",
        "class_path": "backend.tools.content_optimizer.content_optimizer_tool.ContentOptimizerTool",
    },
    "weather_mcp": {
        "enabled": True,
        "type": "mcp",
        "class_path": "backend.tools.mcp.weather_mcp.WeatherMCP",
    },
    "news_mcp": {
        "enabled": True,
        "type": "mcp",
        "class_path": "backend.tools.mcp.news_mcp.NewsMCP",
    },
    "wikipedia_mcp": {
        "enabled": True,
        "type": "mcp",
        "class_path": "backend.tools.mcp.wikipedia_mcp.WikipediaMCP",
    },
    "exchange_rate_mcp": {
        "enabled": True,
        "type": "mcp",
        "class_path": "backend.tools.mcp.exchange_rate_mcp.ExchangeRateMCP",
    },
    "ip_lookup_mcp": {
        "enabled": True,
        "type": "mcp",
        "class_path": "backend.tools.mcp.ip_lookup_mcp.IPLookupMCP",
    },
}


_initialized = False


def _load_tool_class(class_path: str):
    module_path, class_name = class_path.rsplit(".", 1)
    module = import_module(module_path)
    return getattr(module, class_name)


def initialize_tools(force: bool = False):
    """
    初始化并注册所有工具（本地工具和MCP工具）
    """
    global _initialized

    try:
        logger.info("开始初始化所有工具")

        config = get_tool_config()
        registry = get_tool_registry()
        configured_tools = config.get_registry() or DEFAULT_TOOL_REGISTRY

        if force:
            registry.clear()
            _initialized = False

        local_count = 0
        mcp_count = 0
        existing_tools = set(registry.get_tool_names())

        for expected_name, entry in configured_tools.items():
            if not isinstance(entry, dict) or not entry.get("enabled", True):
                continue

            if expected_name in existing_tools:
                logger.debug(f"工具已存在，跳过重复注册: {expected_name}")
                if entry.get("type") == "mcp":
                    mcp_count += 1
                else:
                    local_count += 1
                continue

            class_path = entry.get("class_path")
            if not class_path:
                logger.warning(f"工具 {expected_name} 缺少 class_path，已跳过")
                continue

            tool_class = _load_tool_class(class_path)
            tool_instance = tool_class()
            register_tool(tool_instance)

            tool_type = entry.get("type") or ("mcp" if tool_instance.get_category() == "mcp" else "local")
            if tool_type == "mcp":
                mcp_count += 1
                logger.info(f"MCP工具已注册: {tool_instance.get_name()}")
            else:
                local_count += 1
                logger.info(f"本地工具已注册: {tool_instance.get_name()}")

        _initialized = True
        logger.info(f"所有工具初始化成功（本地工具{local_count}个，MCP工具{mcp_count}个）")

    except Exception as e:
        logger.error(f"工具初始化失败: {str(e)}", exc_info=True)
        raise


# 自动初始化工具（当模块被导入时）
initialize_tools()
