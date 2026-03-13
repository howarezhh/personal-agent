"""
工具模块
提供日志、LLM客户端、向量数据库、文档处理等工具
"""

from backend.utils.logger import get_logger, get_logger_manager
# 注意：llm_client, embedding_client, vector_db_client, jwt_utils 会导致循环导入
# 需要时请直接导入：
# from backend.utils.llm_client import get_llm_client
# from backend.utils.jwt_utils import get_jwt_manager
from backend.utils.exceptions import (
    PersonalAgentException,
    ConfigurationError,
    DatabaseError,
    RecordNotFoundError,
    AuthenticationError,
    AgentError,
    FileProcessingError,
    ToolError,
    ValidationError
)
from backend.utils.validators import (
    validate_required,
    validate_string_length,
    validate_email,
    validate_password_strength,
    validate_in_choices,
    validate_numeric_range,
    validate_file_extension,
    validate_file_size,
    validate_url,
    validate_uuid
)
from backend.utils.helpers import (
    generate_uuid,
    generate_short_id,
    hash_string,
    truncate_string,
    format_file_size,
    parse_duration,
    safe_get,
    chunk_list,
    remove_duplicates,
    merge_dicts,
    is_valid_email,
    sanitize_filename
)

__all__ = [
    # 日志
    "get_logger",
    "get_logger_manager",

    # 异常类
    "PersonalAgentException",
    "ConfigurationError",
    "DatabaseError",
    "RecordNotFoundError",
    "AuthenticationError",
    "AgentError",
    "FileProcessingError",
    "ToolError",
    "ValidationError",

    # 验证器
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

    # 辅助函数
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
