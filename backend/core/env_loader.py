"""环境变量加载模块。

该模块只负责：
1. 自动定位项目根目录下的 `.env` 文件；
2. 在进程启动早期加载环境变量；
3. 提供基础的环境变量校验与访问工具；
4. 通过全局标记避免重复加载 `.env` 文件。

说明：
- 配置文件的读取与解析唯一归口到 `backend.core.config_manager.ConfigManager`；
- 本模块不再直接读取 `config/*.yaml`，仅负责 `.env` 生命周期管理。
"""

import logging
import os
import sys
from pathlib import Path
from typing import List, Optional

logger = logging.getLogger(__name__)
_env_loaded = False


def load_environment(validate: bool = False) -> bool:
    """加载项目根目录中的 `.env` 文件。"""
    global _env_loaded

    if _env_loaded:
        return True

    from backend.utils.path_utils import find_project_root

    try:
        project_root = find_project_root(Path(__file__).parent)
        env_path = project_root / ".env"
    except FileNotFoundError as error:
        logger.error("[ENV] 无法找到项目根目录: %s", error)
        print(f"[ENV] 错误: 无法找到项目根目录: {error}", file=sys.stderr)
        return False

    if not env_path.exists():
        logger.warning("[ENV] .env file not found at: %s", env_path)
        print(f"[ENV] WARNING: .env file not found at: {env_path}", file=sys.stderr)
        return False

    try:
        from dotenv import load_dotenv

        load_dotenv(dotenv_path=env_path, override=True)
        _env_loaded = True
        logger.info("[ENV] Environment variables loaded from: %s", env_path)
        print(f"[ENV] Environment variables loaded from: {env_path}", file=sys.stderr)

        if validate:
            _validate_environment_variables()

        return True

    except ImportError:
        error_msg = "[ENV] ERROR: python-dotenv not installed. Please install it: pip install python-dotenv"
        logger.error(error_msg)
        print(error_msg, file=sys.stderr)
        sys.exit(1)
    except Exception as error:
        logger.error("[ENV] ERROR: Failed to load environment variables: %s", error)
        print(f"[ENV] ERROR: Failed to load environment variables: {error}", file=sys.stderr)
        return False


def _validate_environment_variables() -> None:
    """根据统一配置管理器声明的 env 键名校验环境变量是否存在。"""
    try:
        from backend.core.config_manager import get_config_manager

        required_vars = get_config_manager().get_database_required_env_vars("mysql")
        missing_vars = [var for var in required_vars if not os.getenv(var)]

        if missing_vars:
            warning_msg = f"[ENV] WARNING: Missing required environment variables: {', '.join(missing_vars)}"
            logger.warning(warning_msg)
            print(warning_msg, file=sys.stderr)
        else:
            success_msg = "[ENV] All required database environment variables are set"
            logger.info(success_msg)
            print(success_msg)

    except Exception as error:
        error_msg = f"[ENV] WARNING: Failed to validate environment variables: {error}"
        logger.warning(error_msg)
        print(error_msg, file=sys.stderr)


def validate_required_env_vars(required_vars: List[str]) -> List[str]:
    """校验指定环境变量列表中哪些尚未设置。"""
    return [var for var in required_vars if not os.getenv(var)]


def get_env(key: str, default: Optional[str] = None, required: bool = False) -> Optional[str]:
    """读取单个环境变量。"""
    value = os.getenv(key, default)

    if required and value is None:
        raise ValueError(f"Required environment variable '{key}' is not set")

    return value


load_environment(validate=False)
