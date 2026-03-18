# -*- coding: utf-8 -*-
"""`backend.agents.router` 包的统一导出入口。"""

from importlib import import_module
from typing import Any


__all__ = ["RouterAgent"]


def __getattr__(name: str) -> Any:
    """按需导出路由能力。"""
    if name != "RouterAgent":
        raise AttributeError(f"module 'backend.agents.router' has no attribute {name!r}")
    module = import_module("backend.agents.router.router_agent")
    return getattr(module, name)
