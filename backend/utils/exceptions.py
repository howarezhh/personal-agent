"""项目统一异常定义。

说明：
- 对外 API 错误码、状态码统一收敛到 `backend.contracts.errors`。
- 本模块仅保留领域/工具侧更语义化的异常别名，避免业务层直接依赖 FastAPI HTTPException。
"""

from __future__ import annotations

from backend.contracts.errors import AppException, ErrorCode


class PersonalAgentException(AppException):
    def __init__(self, message: str, *, status_code: int = 500, error_code: ErrorCode | str = ErrorCode.SYSTEM_INTERNAL_ERROR, error: str = "PersonalAgentException"):
        super().__init__(status_code=status_code, message=message, error_code=error_code, error=error)


class ConfigurationError(PersonalAgentException):
    def __init__(self, message: str):
        super().__init__(message, status_code=500, error_code=ErrorCode.SYSTEM_INTERNAL_ERROR, error="ConfigurationError")


class DatabaseError(PersonalAgentException):
    def __init__(self, message: str):
        super().__init__(message, status_code=500, error_code=ErrorCode.SYSTEM_INTERNAL_ERROR, error="DatabaseError")


class RecordNotFoundError(PersonalAgentException):
    def __init__(self, model: str, identifier: str):
        super().__init__(
            f"{model} 未找到: {identifier}",
            status_code=404,
            error_code=ErrorCode.SYSTEM_NOT_FOUND,
            error="RecordNotFoundError",
        )


class AuthenticationError(PersonalAgentException):
    def __init__(self, message: str):
        super().__init__(message, status_code=401, error_code=ErrorCode.AUTH_UNAUTHORIZED, error="AuthenticationError")


class AgentError(PersonalAgentException):
    def __init__(self, message: str):
        super().__init__(message, status_code=500, error_code=ErrorCode.WORKFLOW_EXECUTION_ERROR, error="AgentError")


class FileProcessingError(PersonalAgentException):
    def __init__(self, message: str):
        super().__init__(message, status_code=500, error_code=ErrorCode.SYSTEM_INTERNAL_ERROR, error="FileProcessingError")


class ToolError(PersonalAgentException):
    def __init__(self, message: str):
        super().__init__(message, status_code=500, error_code=ErrorCode.SYSTEM_INTERNAL_ERROR, error="ToolError")


class ValidationError(PersonalAgentException):
    def __init__(self, message: str, field: str | None = None):
        if field:
            message = f"{field}: {message}"
        super().__init__(message, status_code=400, error_code=ErrorCode.SYSTEM_VALIDATION_ERROR, error="ValidationError")
