from backend.contracts.errors import ErrorCode, infer_error_code, resolve_error_code


def test_resolve_error_code_distinguishes_invalid_token_from_credentials():
    assert resolve_error_code(401, "invalid token") == ErrorCode.AUTH_INVALID_TOKEN
    assert resolve_error_code(401, "password incorrect") == ErrorCode.AUTH_INVALID_CREDENTIALS


def test_infer_error_code_uses_invalid_token_for_protected_auth_endpoints():
    assert infer_error_code("/api/v1/auth/profile", 401, "invalid token") == ErrorCode.AUTH_INVALID_TOKEN.value
    assert infer_error_code("/api/v1/auth/logout", 401, "token expired") == ErrorCode.AUTH_TOKEN_EXPIRED.value
    assert infer_error_code("/api/v1/auth/login", 401, "password incorrect") == ErrorCode.AUTH_INVALID_CREDENTIALS.value
