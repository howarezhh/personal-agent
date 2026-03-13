"""
路径工具模块
提供统一的项目根目录查找功能
"""

from pathlib import Path
from typing import Optional
import logging

logger = logging.getLogger(__name__)


def find_project_root(start_path: Optional[Path] = None, max_depth: int = 10) -> Path:
    """
    动态查找项目根目录

    通过查找特征文件/目录来确定项目根目录，而不是依赖固定的层级关系。
    这样更加健壮，适应不同的项目结构和调用位置。

    特征文件/目录（按优先级）：
    1. .git 目录（Git仓库标识）
    2. requirements.txt 或 pyproject.toml（Python项目标识）
    3. config 目录（项目配置目录）
    4. backend 目录（项目后端目录）

    Args:
        start_path: 开始搜索的路径，默认为当前文件所在目录
        max_depth: 最大向上搜索的层级数，防止无限循环

    Returns:
        项目根目录的Path对象

    Raises:
        FileNotFoundError: 如果找不到项目根目录
    """
    if start_path is None:
        start_path = Path(__file__).resolve().parent
    else:
        start_path = Path(start_path).resolve()

    # 特征文件/目录列表
    markers = [
        '.git',
        'requirements.txt',
        'requirements-minimal.txt',
        'pyproject.toml',
        'config',
        'backend'
    ]

    current = start_path
    depth = 0

    while depth < max_depth:
        # 检查当前目录是否包含任何特征文件/目录
        for marker in markers:
            marker_path = current / marker
            if marker_path.exists():
                logger.debug(f"找到项目根目录: {current} (通过特征: {marker})")
                return current

        # 如果已经到达文件系统根目录，停止搜索
        parent = current.parent
        if parent == current:
            break

        current = parent
        depth += 1

    # 如果找不到，抛出异常
    error_msg = f"无法找到项目根目录，从 {start_path} 开始搜索，已尝试 {depth} 层"
    logger.error(error_msg)
    raise FileNotFoundError(error_msg)


def get_project_root() -> Path:
    """
    获取项目根目录（便捷方法）

    Returns:
        项目根目录的Path对象
    """
    return find_project_root()


# 缓存项目根目录，避免重复查找
_cached_project_root: Optional[Path] = None


def get_project_root_cached() -> Path:
    """
    获取项目根目录（带缓存）

    第一次调用时查找并缓存结果，后续调用直接返回缓存值。
    适用于需要频繁获取项目根目录的场景。

    Returns:
        项目根目录的Path对象
    """
    global _cached_project_root

    if _cached_project_root is None:
        _cached_project_root = find_project_root()
        logger.debug(f"缓存项目根目录: {_cached_project_root}")

    return _cached_project_root


def reset_project_root_cache():
    """
    重置项目根目录缓存

    在测试或特殊场景下可能需要重置缓存。
    """
    global _cached_project_root
    _cached_project_root = None
    logger.debug("已重置项目根目录缓存")
