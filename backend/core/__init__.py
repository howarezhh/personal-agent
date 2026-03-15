"""`backend.core` 对外导出入口。

该文件负责统一暴露核心基础能力，方便其他模块通过稳定接口引用：
- 配置管理；
- Prompt 管理；
- 环境变量加载与读取。
"""

from backend.core.config_manager import ConfigManager, get_config_manager
from backend.core.prompt_manager import PromptManager, get_prompt_manager
from backend.core.env_loader import (
    load_environment,
    validate_required_env_vars,
    get_env,
)

__all__ = [
    # 配置管理相关导出。
    "ConfigManager",
    "get_config_manager",
    # Prompt 管理相关导出。
    "PromptManager",
    "get_prompt_manager",
    # 环境变量相关导出。
    "load_environment",
    "validate_required_env_vars",
    "get_env",
]
