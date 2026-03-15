
from enum import StrEnum


class ErrorCode(StrEnum):
    AUTH_INVALID_CREDENTIALS = "AUTH_INVALID_CREDENTIALS"
    AUTH_INVALID_TOKEN = "AUTH_INVALID_TOKEN"
    AUTH_TOKEN_EXPIRED = "AUTH_TOKEN_EXPIRED"
    AUTH_UNAUTHORIZED = "AUTH_UNAUTHORIZED"
    CHAT_STREAM_ABORTED = "CHAT_STREAM_ABORTED"
    CHAT_EXECUTION_FAILED = "CHAT_EXECUTION_FAILED"
    CONVERSATION_NOT_FOUND = "CONVERSATION_NOT_FOUND"
    KNOWLEDGE_BASE_NOT_FOUND = "KNOWLEDGE_BASE_NOT_FOUND"
    DOCUMENT_NOT_FOUND = "DOCUMENT_NOT_FOUND"
    TOOL_TIMEOUT = "TOOL_TIMEOUT"
    RETRIEVAL_NO_RESULT = "RETRIEVAL_NO_RESULT"
    WORKFLOW_INVALID_INPUT = "WORKFLOW_INVALID_INPUT"
    WORKFLOW_ROUTER_FAILED = "WORKFLOW_ROUTER_FAILED"
    WORKFLOW_EXECUTION_ERROR = "WORKFLOW_EXECUTION_ERROR"
    VALIDATION_ERROR = "SYSTEM_VALIDATION_ERROR"
    INTERNAL_ERROR = "SYSTEM_INTERNAL_ERROR"
    NOT_FOUND = "SYSTEM_NOT_FOUND"
    HTTP_ERROR = "SYSTEM_HTTP_ERROR"
    SYSTEM_VALIDATION_ERROR = "SYSTEM_VALIDATION_ERROR"
    SYSTEM_INTERNAL_ERROR = "SYSTEM_INTERNAL_ERROR"
    SYSTEM_NOT_FOUND = "SYSTEM_NOT_FOUND"
    SYSTEM_HTTP_ERROR = "SYSTEM_HTTP_ERROR"


def resolve_error_code(status_code: int, detail: str | None = None) -> ErrorCode:
    normalized_detail = (detail or "").lower()

    if status_code == 401:
        if "expired" in normalized_detail or "过期" in normalized_detail:
            return ErrorCode.AUTH_TOKEN_EXPIRED
        if (
            "invalid token" in normalized_detail
            or "token invalid" in normalized_detail
            or "令牌无效" in normalized_detail
            or "token无效" in normalized_detail
        ):
            return ErrorCode.AUTH_INVALID_TOKEN
        if (
            "credential" in normalized_detail
            or "password" in normalized_detail
            or "凭证" in normalized_detail
            or "密码" in normalized_detail
        ):
            return ErrorCode.AUTH_INVALID_CREDENTIALS
        return ErrorCode.AUTH_UNAUTHORIZED

    if status_code == 404:
        if "conversation" in normalized_detail or "会话" in normalized_detail:
            return ErrorCode.CONVERSATION_NOT_FOUND
        if "knowledge" in normalized_detail or "知识库" in normalized_detail:
            return ErrorCode.KNOWLEDGE_BASE_NOT_FOUND
        if "document" in normalized_detail or "文档" in normalized_detail:
            return ErrorCode.DOCUMENT_NOT_FOUND
        return ErrorCode.NOT_FOUND

    if status_code == 422:
        return ErrorCode.VALIDATION_ERROR

    if status_code >= 500:
        return ErrorCode.INTERNAL_ERROR

    return ErrorCode.HTTP_ERROR


def infer_error_code(path: str, status_code: int, detail: str | None = None) -> str:
    normalized_path = path.lower()
    normalized_detail = (detail or "").lower()

    if "/auth/" in normalized_path:
        if status_code == 401 and ("expired" in normalized_detail or "过期" in normalized_detail):
            return ErrorCode.AUTH_TOKEN_EXPIRED.value
        if status_code == 401 and (
            "invalid token" in normalized_detail
            or "token invalid" in normalized_detail
            or "令牌无效" in normalized_detail
            or "token无效" in normalized_detail
        ):
            return ErrorCode.AUTH_INVALID_TOKEN.value
        if "/auth/login" in normalized_path and status_code in (400, 401):
            return ErrorCode.AUTH_INVALID_CREDENTIALS.value

    if "/chat/" in normalized_path and status_code >= 500:
        return ErrorCode.CHAT_EXECUTION_FAILED.value

    if "/conversations/" in normalized_path and status_code == 404:
        return ErrorCode.CONVERSATION_NOT_FOUND.value

    if "/documents/" in normalized_path and status_code == 404:
        return ErrorCode.DOCUMENT_NOT_FOUND.value

    if "/knowledge/" in normalized_path and status_code == 404:
        return ErrorCode.KNOWLEDGE_BASE_NOT_FOUND.value

    return resolve_error_code(status_code, detail).value
