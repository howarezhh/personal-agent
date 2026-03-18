from __future__ import annotations

from enum import StrEnum
from typing import Iterable, Mapping, Optional

from backend.contracts.responses import ErrorDetail


class ErrorCode(StrEnum):
    AUTH_INVALID_CREDENTIALS = "AUTH_INVALID_CREDENTIALS"
    AUTH_INVALID_TOKEN = "AUTH_INVALID_TOKEN"
    AUTH_TOKEN_EXPIRED = "AUTH_TOKEN_EXPIRED"
    AUTH_UNAUTHORIZED = "AUTH_UNAUTHORIZED"
    USER_NOT_FOUND = "USER_NOT_FOUND"
    CHAT_STREAM_ABORTED = "CHAT_STREAM_ABORTED"
    CHAT_EXECUTION_FAILED = "CHAT_EXECUTION_FAILED"
    CONVERSATION_NOT_FOUND = "CONVERSATION_NOT_FOUND"
    KNOWLEDGE_BASE_NOT_FOUND = "KNOWLEDGE_BASE_NOT_FOUND"
    DOCUMENT_NOT_FOUND = "DOCUMENT_NOT_FOUND"
    TOOL_NOT_FOUND = "TOOL_NOT_FOUND"
    TOOL_ACCESS_DENIED = "TOOL_ACCESS_DENIED"
    TOOL_TIMEOUT = "TOOL_TIMEOUT"
    CONTENT_TOOL_UNAVAILABLE = "CONTENT_TOOL_UNAVAILABLE"
    CSRF_VALIDATION_FAILED = "CSRF_VALIDATION_FAILED"
    RATE_LIMIT_EXCEEDED = "RATE_LIMIT_EXCEEDED"
    RETRIEVAL_NO_RESULT = "RETRIEVAL_NO_RESULT"
    WORKFLOW_INVALID_INPUT = "WORKFLOW_INVALID_INPUT"
    WORKFLOW_ROUTER_FAILED = "WORKFLOW_ROUTER_FAILED"
    WORKFLOW_EXECUTION_ERROR = "WORKFLOW_EXECUTION_ERROR"
    SYSTEM_BAD_REQUEST = "SYSTEM_BAD_REQUEST"
    SYSTEM_VALIDATION_ERROR = "SYSTEM_VALIDATION_ERROR"
    SYSTEM_FORBIDDEN = "SYSTEM_FORBIDDEN"
    SYSTEM_INTERNAL_ERROR = "SYSTEM_INTERNAL_ERROR"
    SYSTEM_NOT_FOUND = "SYSTEM_NOT_FOUND"
    SYSTEM_HTTP_ERROR = "SYSTEM_HTTP_ERROR"


class AppException(Exception):
    def __init__(
        self,
        *,
        status_code: int,
        message: str,
        error_code: ErrorCode | str,
        error: str = "ApplicationError",
        details: Optional[Iterable[ErrorDetail]] = None,
        headers: Optional[Mapping[str, str]] = None,
    ) -> None:
        self.status_code = status_code
        self.message = message
        self.error_code = error_code.value if isinstance(error_code, ErrorCode) else str(error_code)
        self.error = error
        self.details = list(details) if details else None
        self.headers = dict(headers or {})
        super().__init__(message)


def bad_request(
    message: str,
    *,
    error_code: ErrorCode | str = ErrorCode.SYSTEM_BAD_REQUEST,
    error: str = "BadRequest",
) -> AppException:
    return AppException(status_code=400, message=message, error_code=error_code, error=error)


def unauthorized(
    message: str,
    *,
    error_code: ErrorCode | str = ErrorCode.AUTH_UNAUTHORIZED,
    error: str = "Unauthorized",
    headers: Optional[Mapping[str, str]] = None,
) -> AppException:
    return AppException(status_code=401, message=message, error_code=error_code, error=error, headers=headers)


def forbidden(
    message: str,
    *,
    error_code: ErrorCode | str = ErrorCode.SYSTEM_FORBIDDEN,
    error: str = "Forbidden",
) -> AppException:
    return AppException(status_code=403, message=message, error_code=error_code, error=error)


def not_found(
    message: str,
    *,
    error_code: ErrorCode | str = ErrorCode.SYSTEM_NOT_FOUND,
    error: str = "NotFound",
) -> AppException:
    return AppException(status_code=404, message=message, error_code=error_code, error=error)


def too_many_requests(
    message: str,
    *,
    error_code: ErrorCode | str = ErrorCode.RATE_LIMIT_EXCEEDED,
    error: str = "TooManyRequests",
    headers: Optional[Mapping[str, str]] = None,
) -> AppException:
    return AppException(status_code=429, message=message, error_code=error_code, error=error, headers=headers)


def internal_server_error(
    message: str,
    *,
    error_code: ErrorCode | str = ErrorCode.SYSTEM_INTERNAL_ERROR,
    error: str = "InternalServerError",
) -> AppException:
    return AppException(status_code=500, message=message, error_code=error_code, error=error)


def resolve_error_code(status_code: int, detail: str | None = None) -> ErrorCode:
    normalized_detail = (detail or "").lower()

    if status_code == 400:
        return ErrorCode.SYSTEM_BAD_REQUEST

    if status_code == 401:
        if "expired" in normalized_detail or "过期" in normalized_detail:
            return ErrorCode.AUTH_TOKEN_EXPIRED
        if "invalid token" in normalized_detail or "token invalid" in normalized_detail or "令牌无效" in normalized_detail:
            return ErrorCode.AUTH_INVALID_TOKEN
        if "credential" in normalized_detail or "password" in normalized_detail or "密码" in normalized_detail:
            return ErrorCode.AUTH_INVALID_CREDENTIALS
        return ErrorCode.AUTH_UNAUTHORIZED

    if status_code == 403:
        if "csrf" in normalized_detail:
            return ErrorCode.CSRF_VALIDATION_FAILED
        return ErrorCode.SYSTEM_FORBIDDEN

    if status_code == 404:
        if "conversation" in normalized_detail or "会话" in normalized_detail:
            return ErrorCode.CONVERSATION_NOT_FOUND
        if "knowledge" in normalized_detail or "知识库" in normalized_detail:
            return ErrorCode.KNOWLEDGE_BASE_NOT_FOUND
        if "document" in normalized_detail or "文档" in normalized_detail:
            return ErrorCode.DOCUMENT_NOT_FOUND
        if "tool" in normalized_detail or "工具" in normalized_detail:
            return ErrorCode.TOOL_NOT_FOUND
        if "user" in normalized_detail or "用户" in normalized_detail:
            return ErrorCode.USER_NOT_FOUND
        return ErrorCode.SYSTEM_NOT_FOUND

    if status_code == 422:
        return ErrorCode.SYSTEM_VALIDATION_ERROR

    if status_code == 429:
        return ErrorCode.RATE_LIMIT_EXCEEDED

    if status_code >= 500:
        return ErrorCode.SYSTEM_INTERNAL_ERROR

    return ErrorCode.SYSTEM_HTTP_ERROR


def infer_error_code(path: str, status_code: int, detail: str | None = None) -> str:
    normalized_path = path.lower()
    normalized_detail = (detail or "").lower()

    if "/auth/" in normalized_path:
        if status_code == 401 and ("expired" in normalized_detail or "过期" in normalized_detail):
            return ErrorCode.AUTH_TOKEN_EXPIRED.value
        if status_code == 401 and ("invalid token" in normalized_detail or "token invalid" in normalized_detail or "令牌无效" in normalized_detail):
            return ErrorCode.AUTH_INVALID_TOKEN.value
        if "/auth/login" in normalized_path and status_code in (400, 401):
            return ErrorCode.AUTH_INVALID_CREDENTIALS.value
        if "/auth/profile" in normalized_path and status_code == 404:
            return ErrorCode.USER_NOT_FOUND.value

    if "/chat/" in normalized_path and status_code >= 500:
        return ErrorCode.CHAT_EXECUTION_FAILED.value

    if "/conversations/" in normalized_path and status_code == 404:
        return ErrorCode.CONVERSATION_NOT_FOUND.value

    if "/documents/" in normalized_path and status_code == 404:
        return ErrorCode.DOCUMENT_NOT_FOUND.value

    if "/knowledge/" in normalized_path and status_code == 404:
        return ErrorCode.KNOWLEDGE_BASE_NOT_FOUND.value

    if "/tools/" in normalized_path and status_code == 404:
        return ErrorCode.TOOL_NOT_FOUND.value

    return resolve_error_code(status_code, detail).value
