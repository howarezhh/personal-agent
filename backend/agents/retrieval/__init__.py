# -*- coding: utf-8 -*-

"""`backend.agents.retrieval` 包的统一导出入口。

本文件本身不承载检索业务逻辑，
主要作用是统一维护对外导出的检索能力入口，
避免上层模块直接依赖子文件路径，降低导入耦合。
"""

from backend.agents.retrieval.retrieval_agent import RetrievalAgent

# `__all__`：显式声明当前包对外公开的对象，避免无关实现细节泄露。
__all__ = [
    "RetrievalAgent",
]
