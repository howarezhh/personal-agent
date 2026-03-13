"""
辅助工具函数
提供通用的辅助功能
"""

import hashlib
import uuid
import re
from typing import Any, Dict, List, Optional
from datetime import datetime, timedelta


def generate_uuid() -> str:
    """
    生成UUID字符串

    Returns:
        UUID字符串
    """
    return str(uuid.uuid4())


def generate_short_id(length: int = 8) -> str:
    """
    生成短ID

    Args:
        length: ID长度

    Returns:
        短ID字符串
    """
    return uuid.uuid4().hex[:length]


def hash_string(text: str, algorithm: str = "sha256") -> str:
    """
    对字符串进行哈希

    Args:
        text: 要哈希的文本
        algorithm: 哈希算法（md5/sha1/sha256）

    Returns:
        哈希值
    """
    if algorithm == "md5":
        return hashlib.md5(text.encode()).hexdigest()
    elif algorithm == "sha1":
        return hashlib.sha1(text.encode()).hexdigest()
    else:
        return hashlib.sha256(text.encode()).hexdigest()


def truncate_string(text: str, max_length: int, suffix: str = "...") -> str:
    """
    截断字符串

    Args:
        text: 原始文本
        max_length: 最大长度
        suffix: 后缀

    Returns:
        截断后的文本
    """
    if len(text) <= max_length:
        return text
    return text[:max_length - len(suffix)] + suffix


def format_file_size(size_bytes: int) -> str:
    """
    格式化文件大小

    Args:
        size_bytes: 字节数

    Returns:
        格式化后的大小字符串
    """
    for unit in ['B', 'KB', 'MB', 'GB', 'TB']:
        if size_bytes < 1024.0:
            return f"{size_bytes:.2f} {unit}"
        size_bytes /= 1024.0
    return f"{size_bytes:.2f} PB"


def parse_duration(duration_str: str) -> Optional[timedelta]:
    """
    解析时间段字符串

    Args:
        duration_str: 时间段字符串（如 "1h", "30m", "1d"）

    Returns:
        timedelta对象
    """
    pattern = r'^(\d+)([smhd])$'
    match = re.match(pattern, duration_str.lower())
    
    if not match:
        return None
    
    value, unit = int(match.group(1)), match.group(2)
    
    if unit == 's':
        return timedelta(seconds=value)
    elif unit == 'm':
        return timedelta(minutes=value)
    elif unit == 'h':
        return timedelta(hours=value)
    elif unit == 'd':
        return timedelta(days=value)
    
    return None


def safe_get(data: Dict, key_path: str, default: Any = None) -> Any:
    """
    安全地从嵌套字典中获取值

    Args:
        data: 字典数据
        key_path: 键路径（用点号分隔）
        default: 默认值

    Returns:
        值或默认值
    """
    keys = key_path.split('.')
    value = data
    
    for key in keys:
        if isinstance(value, dict) and key in value:
            value = value[key]
        else:
            return default
    
    return value


def chunk_list(lst: List, chunk_size: int) -> List[List]:
    """
    将列表分块

    Args:
        lst: 原始列表
        chunk_size: 每块大小

    Returns:
        分块后的列表
    """
    return [lst[i:i + chunk_size] for i in range(0, len(lst), chunk_size)]


def remove_duplicates(lst: List, key: Optional[str] = None) -> List:
    """
    去除列表中的重复项

    Args:
        lst: 原始列表
        key: 如果列表元素是字典，指定用于去重的键

    Returns:
        去重后的列表
    """
    if not lst:
        return []
    
    if key is None:
        return list(dict.fromkeys(lst))
    
    seen = set()
    result = []
    for item in lst:
        if isinstance(item, dict):
            value = item.get(key)
            if value not in seen:
                seen.add(value)
                result.append(item)
    
    return result


def merge_dicts(*dicts: Dict) -> Dict:
    """
    合并多个字典

    Args:
        *dicts: 要合并的字典

    Returns:
        合并后的字典
    """
    result = {}
    for d in dicts:
        if d:
            result.update(d)
    return result


def is_valid_email(email: str) -> bool:
    """
    验证邮箱格式

    Args:
        email: 邮箱地址

    Returns:
        是否有效
    """
    pattern = r'^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$'
    return bool(re.match(pattern, email))


def sanitize_filename(filename: str) -> str:
    """
    清理文件名，移除不安全字符

    Args:
        filename: 原始文件名

    Returns:
        清理后的文件名
    """
    # 移除路径分隔符和其他不安全字符
    unsafe_chars = r'[<>:"/\|?*\x00-\x1f]'
    return re.sub(unsafe_chars, '_', filename)
