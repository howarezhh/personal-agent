
import secrets
import hmac
import hashlib
from typing import Optional, Callable
from fastapi import Request
from fastapi.responses import JSONResponse
from backend.utils.logger import get_logger
from backend.core.config_manager import get_config_manager

logger = get_logger(__name__)


class CSRFProtection:
    def __init__(
        self,
        secret_key: str,
        token_name: str = "csrf_token",
        header_name: str = "X-CSRF-Token",
        cookie_name: str = "csrf_token",
        safe_methods: tuple = ("GET", "HEAD", "OPTIONS", "TRACE")
    ):
        self.secret_key = secret_key
        self.token_name = token_name
        self.header_name = header_name
        self.cookie_name = cookie_name
        self.safe_methods = safe_methods

        logger.info("CSRF protection initialized")

    def generate_token(self, session_id: Optional[str] = None) -> str:
        # 生成随机token
        random_token = secrets.token_urlsafe(32)

        # 如果有session_id，使用HMAC签名
        if session_id:
            signature = hmac.new(
                self.secret_key.encode(),
                f"{random_token}:{session_id}".encode(),
                hashlib.sha256
            ).hexdigest()
            return f"{random_token}.{signature}"

        return random_token

    def validate_token(
        self,
        token: str,
        session_id: Optional[str] = None
    ) -> bool:
        if not token:
            return False

        # 如果有session_id，验证HMAC签名
        if session_id and "." in token:
            try:
                random_token, signature = token.rsplit(".", 1)
                expected_signature = hmac.new(
                    self.secret_key.encode(),
                    f"{random_token}:{session_id}".encode(),
                    hashlib.sha256
                ).hexdigest()
                return hmac.compare_digest(signature, expected_signature)
            except Exception as e:
                logger.error(f"CSRF token validation error: {str(e)}")
                return False

        # 简单验证token长度
        return len(token) >= 32

    def is_safe_method(self, method: str) -> bool:
        return method.upper() in self.safe_methods

    def get_token_from_request(self, request: Request) -> Optional[str]:
        # 1. 从HTTP头获取
        token = request.headers.get(self.header_name)
        if token:
            return token

        # 2. 从Cookie获取
        token = request.cookies.get(self.cookie_name)
        if token:
            return token

        return None


# 全局CSRF保护实例
_csrf_protection: Optional[CSRFProtection] = None


def get_csrf_protection() -> CSRFProtection:
    global _csrf_protection

    if _csrf_protection is None:
        config_manager = get_config_manager()

        # 获取CSRF配置
        csrf_config = config_manager.get("business.security.csrf", {})
        secret_key = config_manager.get_with_env("business.security.csrf.secret_key") or csrf_config.get("secret_key")

        if not secret_key:
            error_msg = (
                "CSRF secret key not configured. "
                "Please set 'business.security.csrf.secret_key' in config or 'CSRF_SECRET_KEY' environment variable. "
                "For development, you can generate one with: python -c 'import secrets; print(secrets.token_urlsafe(32))'"
            )
            logger.error(error_msg)
            raise ValueError(error_msg)

        _csrf_protection = CSRFProtection(
            secret_key=secret_key,
            token_name=csrf_config.get("token_name", "csrf_token"),
            header_name=csrf_config.get("header_name", "X-CSRF-Token"),
            cookie_name=csrf_config.get("cookie_name", "csrf_token"),
            safe_methods=tuple(csrf_config.get("safe_methods", ["GET", "HEAD", "OPTIONS", "TRACE"]))
        )

    return _csrf_protection


async def csrf_protect_middleware(
    request: Request,
    call_next: Callable
):
    csrf_protection = get_csrf_protection()

    # 安全方法不需要CSRF保护
    if csrf_protection.is_safe_method(request.method):
        response = await call_next(request)
        return response

    # 获取会话ID（如果有）
    session_id = None
    if hasattr(request.state, "user_id"):
        session_id = request.state.user_id

    # 获取CSRF Token
    token = csrf_protection.get_token_from_request(request)

    # 验证Token
    if not token or not csrf_protection.validate_token(token, session_id):
        logger.warning(f"CSRF validation failed for {request.url.path}")
        return JSONResponse(
            status_code=status.HTTP_403_FORBIDDEN,
            content={
                "success": False,
                "code": 403,
                "message": "CSRF验证失败",
                "error": "CSRFValidationFailed"
            }
        )

    # 继续处理请求
    response = await call_next(request)
    return response


def csrf_exempt(func):
    func._csrf_exempt = True
    return func


def require_csrf(func):
    async def wrapper(request: Request, *args, **kwargs):
        csrf_protection = get_csrf_protection()

        # 获取会话ID（如果有）
        session_id = None
        if hasattr(request.state, "user_id"):
            session_id = request.state.user_id

        # 获取CSRF Token
        token = csrf_protection.get_token_from_request(request)

        # 验证Token
        if not token or not csrf_protection.validate_token(token, session_id):
            raise forbidden("CSRF validation failed", error_code=ErrorCode.CSRF_VALIDATION_FAILED, error="CSRFValidationFailed")

        # 执行原函数
        return await func(request, *args, **kwargs)

    return wrapper


def generate_csrf_token(request: Request) -> str:
    csrf_protection = get_csrf_protection()

    # 获取会话ID（如果有）
    session_id = None
    if hasattr(request.state, "user_id"):
        session_id = request.state.user_id

    return csrf_protection.generate_token(session_id)
