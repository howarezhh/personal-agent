from backend.api.models import ErrorResponse, MessageResponse
from backend.contracts.errors import ErrorCode, infer_error_code


def test_error_response_includes_error_code():
    response = ErrorResponse.create(
        code=404,
        message="会话不存在或访问被拒绝",
        error="HTTPException",
        error_code=ErrorCode.CONVERSATION_NOT_FOUND.value,
    )

    assert response.error_code == ErrorCode.CONVERSATION_NOT_FOUND.value
    assert response.timestamp


def test_error_code_inference_matches_known_paths():
    assert infer_error_code("/api/v1/conversations/abc", 404, "会话不存在") == ErrorCode.CONVERSATION_NOT_FOUND.value
    assert infer_error_code("/api/v1/auth/profile", 401, "token expired") == ErrorCode.AUTH_TOKEN_EXPIRED.value
    assert infer_error_code("/api/v1/knowledge/documents/doc-1", 404, "document not found") == ErrorCode.DOCUMENT_NOT_FOUND.value


def test_message_response_always_contains_timestamp():
    response = MessageResponse.create("ok")
    assert response.timestamp
