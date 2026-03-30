# -*- coding: utf-8 -*-
"""Router Agent 包导出。

当前项目的主聊天链路已经切到 task-runtime，
这里补齐标准 `router` Agent 源码，确保注册表中的标准 Agent 类型完整可用。
"""

from backend.agents.router.router_agent import RouterAgent

__all__ = ["RouterAgent"]
