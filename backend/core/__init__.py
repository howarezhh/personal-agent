"""
核心模块
提供配置管理、提示词管理、环境变量加载等核心功能
"""

from backend.core.config_manager import ConfigManager, get_config_manager
from backend.core.prompt_manager import PromptManager, get_prompt_manager
from backend.core.env_loader import (
    load_environment,
    validate_required_env_vars,
    get_env
)

__all__ = [
    # 配置管理
    'ConfigManager',
    'get_config_manager',

    # 提示词管理
    'PromptManager',
    'get_prompt_manager',

    # 环境变量管理
    'load_environment',
    'validate_required_env_vars',
    'get_env',
]
