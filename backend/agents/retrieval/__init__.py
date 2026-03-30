# -*- coding: utf-8 -*-

from __future__ import annotations

"""`backend.agents.retrieval` 包的统一导出入口。

本文件本身不承载检索业务逻辑，
主要作用是统一维护对外导出的检索能力入口，
避免上层模块直接依赖子文件路径，降低导入耦合。

同时这里必须避免包初始化阶段的提前导入：
- `backend.utils.vector_db_client` 会导入 `keyword_retriever`
- 导入 `backend.agents.retrieval.keyword_retriever` 时，Python 会先执行本包的 `__init__`
- 如果这里立刻导入 `retrieval_agent`，而 `retrieval_agent` 又反向依赖 `vector_db_client`
- 就会形成循环导入

因此这里改为“惰性导出”：
只有外部真正访问 `RetrievalAgent` 时，才执行实际导入。
"""

from typing import TYPE_CHECKING, Any


# 类型检查阶段保留显式导入，方便 IDE 与静态分析识别导出类型。
if TYPE_CHECKING:
    from backend.agents.retrieval.retrieval_agent import RetrievalAgent


def __getattr__(name: str) -> Any:
    """按需导出检索 Agent，避免包初始化阶段触发循环导入。"""

    # 只有外部真正访问 `RetrievalAgent` 时，才执行实际导入。
    if name == "RetrievalAgent":
        from backend.agents.retrieval.retrieval_agent import RetrievalAgent

        return RetrievalAgent

    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


# `__all__`：显式声明当前包对外公开的对象，避免无关实现细节泄露。
__all__ = [
    "RetrievalAgent",
]
