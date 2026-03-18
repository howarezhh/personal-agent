"""`backend.agents.tool` 模块导出入口。

该文件的职责非常单一：
1. 统一暴露工具代理层的核心类，便于外部模块按稳定路径导入。
2. 避免调用方直接依赖子模块文件名，降低导入路径耦合。
3. 通过 `__all__` 明确当前包的公共接口范围。
"""

from backend.agents.tool.result_interpreter import ResultInterpreter
from backend.agents.tool.tool_agent import ToolAgent
from backend.agents.tool.tool_selector import ToolSelector

# `__all__` 用于声明当前包对外公开的符号列表。
# 调用方使用 `from backend.agents.tool import *` 时，只会导出这里列出的类。
__all__ = [
    "ToolAgent",
    "ToolSelector",
    "ResultInterpreter",
]
