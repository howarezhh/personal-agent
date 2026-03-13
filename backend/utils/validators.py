"""
数据验证器
提供各种数据验证功能
"""

import re
from typing import Any, List, Optional
from backend.utils.exceptions import ValidationError


def validate_required(value: Any, field_name: str) -> None:
    """
    验证必填字段

    Args:
        value: 值
        field_name: 字段名

    Raises:
        ValidationError: 如果值为空
    """
    if value is None or (isinstance(value, str) and not value.strip()):
        raise ValidationError(f"{field_name}是必填项", field_name)


def validate_string_length(
    value: str,
    field_name: str,
    min_length: Optional[int] = None,
    max_length: Optional[int] = None
) -> None:
    """
    验证字符串长度

    Args:
        value: 字符串值
        field_name: 字段名
        min_length: 最小长度
        max_length: 最大长度

    Raises:
        ValidationError: 如果长度不符合要求
    """
    if not isinstance(value, str):
        raise ValidationError(f"{field_name}必须是字符串", field_name)
    
    length = len(value)
    
    if min_length is not None and length < min_length:
        raise ValidationError(
            f"{field_name}至少需要{min_length}个字符",
            field_name
        )
    
    if max_length is not None and length > max_length:
        raise ValidationError(
            f"{field_name}不能超过{max_length}个字符",
            field_name
        )


def validate_email(email: str, field_name: str = "email") -> None:
    """
    验证邮箱格式

    Args:
        email: 邮箱地址
        field_name: 字段名

    Raises:
        ValidationError: 如果邮箱格式无效
    """
    pattern = r'^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$'
    if not re.match(pattern, email):
        raise ValidationError(f"邮箱格式无效", field_name)


def validate_password_strength(password: str, field_name: str = "password") -> None:
    """
    验证密码强度

    要求：
    - 至少8个字符
    - 包含字母和数字

    Args:
        password: 密码
        field_name: 字段名

    Raises:
        ValidationError: 如果密码强度不足
    """
    if len(password) < 8:
        raise ValidationError(
            "密码至少需要8个字符",
            field_name
        )
    
    if not re.search(r'[a-zA-Z]', password):
        raise ValidationError(
            "密码必须包含至少一个字母",
            field_name
        )
    
    if not re.search(r'\d', password):
        raise ValidationError(
            "密码必须包含至少一个数字",
            field_name
        )


def validate_in_choices(
    value: Any,
    choices: List[Any],
    field_name: str
) -> None:
    """
    验证值是否在允许的选项中

    Args:
        value: 值
        choices: 允许的选项列表
        field_name: 字段名

    Raises:
        ValidationError: 如果值不在选项中
    """
    if value not in choices:
        raise ValidationError(
            f"{field_name}必须是以下值之一: {', '.join(map(str, choices))}",
            field_name
        )


def validate_numeric_range(
    value: float,
    field_name: str,
    min_value: Optional[float] = None,
    max_value: Optional[float] = None
) -> None:
    """
    验证数值范围

    Args:
        value: 数值
        field_name: 字段名
        min_value: 最小值
        max_value: 最大值

    Raises:
        ValidationError: 如果数值超出范围
    """
    if min_value is not None and value < min_value:
        raise ValidationError(
            f"{field_name}必须至少为{min_value}",
            field_name
        )
    
    if max_value is not None and value > max_value:
        raise ValidationError(
            f"{field_name}不能超过{max_value}",
            field_name
        )


def validate_file_extension(
    filename: str,
    allowed_extensions: List[str],
    field_name: str = "file"
) -> None:
    """
    验证文件扩展名

    Args:
        filename: 文件名
        allowed_extensions: 允许的扩展名列表（如 ['.pdf', '.docx']）
        field_name: 字段名

    Raises:
        ValidationError: 如果扩展名不允许
    """
    extension = filename.lower().split('.')[-1] if '.' in filename else ''
    extension_with_dot = f'.{extension}'
    
    if extension_with_dot not in [ext.lower() for ext in allowed_extensions]:
        raise ValidationError(
            f"不允许的文件类型。允许的类型: {', '.join(allowed_extensions)}",
            field_name
        )


def validate_file_size(
    file_size: int,
    max_size: int,
    field_name: str = "file"
) -> None:
    """
    验证文件大小

    Args:
        file_size: 文件大小（字节）
        max_size: 最大大小（字节）
        field_name: 字段名

    Raises:
        ValidationError: 如果文件过大
    """
    if file_size > max_size:
        max_size_mb = max_size / (1024 * 1024)
        raise ValidationError(
            f"文件大小超过最大允许大小 {max_size_mb:.2f} MB",
            field_name
        )


def validate_url(url: str, field_name: str = "url") -> None:
    """
    验证URL格式

    Args:
        url: URL地址
        field_name: 字段名

    Raises:
        ValidationError: 如果URL格式无效
    """
    pattern = r'^https?://[^\s/$.?#].[^\s]*$'
    if not re.match(pattern, url, re.IGNORECASE):
        raise ValidationError(f"URL格式无效", field_name)


def validate_uuid(value: str, field_name: str = "id") -> None:
    """
    验证UUID格式

    Args:
        value: UUID字符串
        field_name: 字段名

    Raises:
        ValidationError: 如果UUID格式无效
    """
    pattern = r'^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$'
    if not re.match(pattern, value.lower()):
        raise ValidationError(f"UUID格式无效", field_name)
