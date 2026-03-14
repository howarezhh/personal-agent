"""
环境变量加载模块
确保在任何模块导入之前加载环境变量
"""

import os
import sys
import logging
from pathlib import Path
from typing import List, Optional

# 配置日志
logger = logging.getLogger(__name__)

# 标记是否已加载环境变量
_env_loaded = False


def load_environment(validate: bool = False) -> bool:
    """
    加载环境变量

    这个函数会被多次调用（因为uvicorn的reload模式会创建子进程），
    但只会在第一次调用时真正加载环境变量

    Args:
        validate: 是否验证关键环境变量（默认False，避免循环依赖）

    Returns:
        是否成功加载环境变量
    """
    global _env_loaded

    if _env_loaded:
        return True

    # 动态查找项目根目录
    from backend.utils.path_utils import find_project_root

    try:
        project_root = find_project_root(Path(__file__).parent)
        env_path = project_root / ".env"
    except FileNotFoundError as e:
        logger.error(f"[ENV] 无法找到项目根目录: {e}")
        print(f"[ENV] 错误: 无法找到项目根目录: {e}")
        return False

    # 加载环境变量
    if not env_path.exists():
        logger.warning(f"[ENV] .env file not found at: {env_path}")
        print(f"[ENV] WARNING: .env file not found at: {env_path}")
        return False

    # 使用python-dotenv加载环境变量
    try:
        from dotenv import load_dotenv
        load_dotenv(dotenv_path=env_path, override=True)
        _env_loaded = True
        logger.info(f"[ENV] Environment variables loaded from: {env_path}")
        print(f"[ENV] Environment variables loaded from: {env_path}")

        # 可选的环境变量验证（避免在模块导入时执行，防止循环依赖）
        if validate:
            _validate_environment_variables(project_root)

        return True

    except ImportError:
        error_msg = "[ENV] ERROR: python-dotenv not installed. Please install it: pip install python-dotenv"
        logger.error(error_msg)
        print(error_msg)
        sys.exit(1)
    except Exception as e:
        logger.error(f"[ENV] ERROR: Failed to load environment variables: {e}")
        print(f"[ENV] ERROR: Failed to load environment variables: {e}")
        return False


def _validate_environment_variables(project_root: Path) -> None:
    """
    验证关键环境变量

    注意：此函数应该在应用启动后调用，而不是在模块导入时调用，
    以避免循环依赖问题

    Args:
        project_root: 项目根目录路径
    """
    try:
        import yaml
        config_path = project_root / "config" / "base" / "database.yaml"

        if not config_path.exists():
            logger.warning(f"[ENV] Base database config file not found at: {config_path}")
            print(f"[ENV] WARNING: Base database config file not found at: {config_path}")
            return

        with open(config_path, 'r', encoding='utf-8') as f:
            db_config = yaml.safe_load(f)

        # 从配置文件中提取MySQL环境变量名
        mysql_config = db_config.get('mysql', {})
        required_vars = [
            mysql_config.get('host_env'),
            mysql_config.get('port_env'),
            mysql_config.get('database_env'),
            mysql_config.get('username_env'),
            mysql_config.get('password_env')
        ]
        # 过滤掉None值
        required_vars = [var for var in required_vars if var]

        missing_vars = [var for var in required_vars if not os.getenv(var)]

        if missing_vars:
            warning_msg = f"[ENV] WARNING: Missing required environment variables: {', '.join(missing_vars)}"
            logger.warning(warning_msg)
            print(warning_msg)
        else:
            success_msg = "[ENV] All required database environment variables are set"
            logger.info(success_msg)
            print(success_msg)

    except Exception as e:
        error_msg = f"[ENV] WARNING: Failed to validate environment variables: {e}"
        logger.warning(error_msg)
        print(error_msg)


def validate_required_env_vars(required_vars: List[str]) -> List[str]:
    """
    验证指定的环境变量是否存在

    Args:
        required_vars: 必需的环境变量名称列表

    Returns:
        缺失的环境变量名称列表
    """
    return [var for var in required_vars if not os.getenv(var)]


def get_env(key: str, default: Optional[str] = None, required: bool = False) -> Optional[str]:
    """
    获取环境变量值

    Args:
        key: 环境变量名称
        default: 默认值
        required: 是否必需（如果必需但不存在，则抛出异常）

    Returns:
        环境变量值

    Raises:
        ValueError: 如果环境变量必需但不存在
    """
    value = os.getenv(key, default)

    if required and value is None:
        raise ValueError(f"Required environment variable '{key}' is not set")

    return value


# 立即加载环境变量（当这个模块被导入时）
# 注意：不在导入时验证，避免循环依赖
load_environment(validate=False)
