"""工具模块对外统一导出入口。

该文件只承担包级别的导出职责：
1. 聚合工具体系的核心类型与辅助函数。
2. 通过 ``__all__`` 明确声明对外公共 API。
3. 让外部调用方可以直接从 ``backend.tools`` 导入常用对象，
   无需感知底层文件组织细节。

这样做有助于保持调用方式稳定，也便于后续内部实现调整时减少影响面。
"""

from backend.tools.base_tool import (
    BaseTool,
    ToolDefinition,
    ToolParameter,
    ToolError,
    ToolTimeoutError,
    ToolParameterError,
    ToolExecutionError,
    ToolConfigurationError,
    ToolNetworkError
)
from backend.tools.tool_registry import (
    ToolRegistry,
    get_tool_registry,
    register_tool,
    get_tool,
    get_all_tools,
    get_tool_definitions
)
from backend.tools.tool_config import get_tool_config, ToolConfig
from backend.tools.tool_initializer import initialize_tools, ensure_tools_initialized

# 统一声明本包允许对外暴露的符号。
# 这样既能控制导出边界，也能明确哪些对象属于稳定公共接口。
__all__ = [
    "BaseTool",
    "ToolDefinition",
    "ToolParameter",
    "ToolError",
    "ToolTimeoutError",
    "ToolParameterError",
    "ToolExecutionError",
    "ToolConfigurationError",
    "ToolNetworkError",
    "ToolRegistry",
    "get_tool_registry",
    "register_tool",
    "get_tool",
    "get_all_tools",
    "get_tool_definitions",
    "get_tool_config",
    "ToolConfig",
    "initialize_tools",
    "ensure_tools_initialized",
]
