"""环境变量加载模块。

该模块负责：
1. 自动定位项目根目录下的 `.env` 文件；
2. 在进程启动早期加载环境变量；
3. 提供基础的环境变量校验与访问工具；
4. 通过全局标记避免重复加载 `.env` 文件。
"""

import logging
import os
import sys
from pathlib import Path
from typing import List, Optional

# 当前模块使用的日志记录器。
logger = logging.getLogger(__name__)

# 用于标记环境变量是否已经完成加载，防止重复执行 `load_dotenv`。
_env_loaded = False


def load_environment(validate: bool = False) -> bool:
    """加载项目根目录中的 `.env` 文件。

    Args:
        validate: 是否在加载完成后额外执行一次环境变量校验。

    Returns:
        加载成功返回 True；未找到文件或加载失败返回 False。
    """
    global _env_loaded

    if _env_loaded:
        return True

    # 动态定位项目根目录，避免依赖固定的运行工作目录。
    from backend.utils.path_utils import find_project_root

    try:
        project_root = find_project_root(Path(__file__).parent)
        env_path = project_root / ".env"
    except FileNotFoundError as error:
        logger.error("[ENV] 无法找到项目根目录: %s", error)
        print(f"[ENV] 错误: 无法找到项目根目录: {error}")
        return False

    # 若未找到 `.env` 文件，则记录告警并返回，由调用方决定是否继续运行。
    if not env_path.exists():
        logger.warning("[ENV] .env file not found at: %s", env_path)
        print(f"[ENV] WARNING: .env file not found at: {env_path}")
        return False

    # 使用 python-dotenv 将 `.env` 中的键值对注入当前进程环境变量。
    try:
        from dotenv import load_dotenv

        load_dotenv(dotenv_path=env_path, override=True)
        _env_loaded = True
        logger.info("[ENV] Environment variables loaded from: %s", env_path)
        print(f"[ENV] Environment variables loaded from: {env_path}")

        # 仅在显式要求时校验，避免模块导入阶段触发更多依赖链。
        if validate:
            _validate_environment_variables(project_root)

        return True

    except ImportError:
        error_msg = "[ENV] ERROR: python-dotenv not installed. Please install it: pip install python-dotenv"
        logger.error(error_msg)
        print(error_msg)
        sys.exit(1)
    except Exception as error:
        logger.error("[ENV] ERROR: Failed to load environment variables: %s", error)
        print(f"[ENV] ERROR: Failed to load environment variables: {error}")
        return False


def _validate_environment_variables(project_root: Path) -> None:
    """根据数据库基础配置校验必需环境变量是否存在。

    当前实现主要面向 MySQL 连接配置，后续如果有更多基础设施配置需要校验，
    可以继续在这里扩展。

    Args:
        project_root: 已解析出的项目根目录。
    """
    try:
        import yaml

        config_path = project_root / "config" / "base" / "database.yaml"

        if not config_path.exists():
            logger.warning("[ENV] Base database config file not found at: %s", config_path)
            print(f"[ENV] WARNING: Base database config file not found at: {config_path}")
            return

        with open(config_path, "r", encoding="utf-8") as file:
            db_config = yaml.safe_load(file)

        # 从基础数据库配置中提取出 MySQL 使用的环境变量名称。
        mysql_config = db_config.get("mysql", {})
        required_vars = [
            mysql_config.get("host_env"),
            mysql_config.get("port_env"),
            mysql_config.get("database_env"),
            mysql_config.get("username_env"),
            mysql_config.get("password_env"),
        ]
        # 过滤掉空值，避免将 None 误判为缺失的环境变量名。
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

    except Exception as error:
        error_msg = f"[ENV] WARNING: Failed to validate environment variables: {error}"
        logger.warning(error_msg)
        print(error_msg)


def validate_required_env_vars(required_vars: List[str]) -> List[str]:
    """校验指定环境变量列表中哪些尚未设置。

    Args:
        required_vars: 需要检查的环境变量名列表。

    Returns:
        缺失的环境变量名列表。
    """
    return [var for var in required_vars if not os.getenv(var)]


def get_env(key: str, default: Optional[str] = None, required: bool = False) -> Optional[str]:
    """读取单个环境变量。

    Args:
        key: 环境变量名。
        default: 默认值。
        required: 是否要求该环境变量必须存在。

    Returns:
        命中的环境变量值或默认值。

    Raises:
        ValueError: 当 `required=True` 且变量不存在时抛出。
    """
    value = os.getenv(key, default)

    if required and value is None:
        raise ValueError(f"Required environment variable '{key}' is not set")

    return value


# 模块导入时即尝试加载环境变量，便于其他模块在启动初期直接读取配置。
# 这里不默认启用校验，避免导入链路中过早引入额外依赖和副作用。
load_environment(validate=False)
