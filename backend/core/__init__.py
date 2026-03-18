# -*- coding: utf-8 -*-
"""`backend.core` 对外稳定导出入口。

这里改为惰性导出，避免调用方只导入某个子模块时，
在包初始化阶段就连带加载配置、LLM 等重依赖模块。
"""

from importlib import import_module
from typing import Any


__all__ = [
    "ConfigManager",
    "get_config_manager",
    "PromptManager",
    "get_prompt_manager",
    "LangChainModelManager",
    "get_langchain_model_manager",
    "load_environment",
    "validate_required_env_vars",
    "get_env",
]


_EXPORT_MAP = {
    "ConfigManager": ("backend.core.config_manager", "ConfigManager"),
    "get_config_manager": ("backend.core.config_manager", "get_config_manager"),
    "PromptManager": ("backend.core.prompt_manager", "PromptManager"),
    "get_prompt_manager": ("backend.core.prompt_manager", "get_prompt_manager"),
    "LangChainModelManager": ("backend.core.llm_manager", "LangChainModelManager"),
    "get_langchain_model_manager": ("backend.core.llm_manager", "get_langchain_model_manager"),
    "load_environment": ("backend.core.env_loader", "load_environment"),
    "validate_required_env_vars": ("backend.core.env_loader", "validate_required_env_vars"),
    "get_env": ("backend.core.env_loader", "get_env"),
}


def __getattr__(name: str) -> Any:
    """按需加载公开符号。"""
    if name not in _EXPORT_MAP:
        raise AttributeError(f"module 'backend.core' has no attribute {name!r}")
    module_name, attr_name = _EXPORT_MAP[name]
    module = import_module(module_name)
    return getattr(module, attr_name)
