"""工具模块。

提供日志、通用异常、校验器与帮助函数等基础能力。
模型交互能力已统一收敛到 `backend/core/llm_manager.py`。
"""

from backend.utils.exceptions import (
    AgentError,
    AuthenticationError,
    ConfigurationError,
    DatabaseError,
    FileProcessingError,
    PersonalAgentException,
    RecordNotFoundError,
    ToolError,
    ValidationError,
)
from backend.utils.helpers import (
    chunk_list,
    format_file_size,
    generate_short_id,
    generate_uuid,
    hash_string,
    is_valid_email,
    merge_dicts,
    parse_duration,
    remove_duplicates,
    safe_get,
    sanitize_filename,
    truncate_string,
)
from backend.utils.logger import get_logger, get_logger_manager
from backend.utils.validators import (
    validate_email,
    validate_file_extension,
    validate_file_size,
    validate_in_choices,
    validate_numeric_range,
    validate_password_strength,
    validate_required,
    validate_string_length,
    validate_url,
    validate_uuid,
)

__all__ = [
    "get_logger",
    "get_logger_manager",
    "PersonalAgentException",
    "ConfigurationError",
    "DatabaseError",
    "RecordNotFoundError",
    "AuthenticationError",
    "AgentError",
    "FileProcessingError",
    "ToolError",
    "ValidationError",
    "validate_required",
    "validate_string_length",
    "validate_email",
    "validate_password_strength",
    "validate_in_choices",
    "validate_numeric_range",
    "validate_file_extension",
    "validate_file_size",
    "validate_url",
    "validate_uuid",
    "generate_uuid",
    "generate_short_id",
    "hash_string",
    "truncate_string",
    "format_file_size",
    "parse_duration",
    "safe_get",
    "chunk_list",
    "remove_duplicates",
    "merge_dicts",
    "is_valid_email",
    "sanitize_filename",
]
