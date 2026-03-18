# -*- coding: utf-8 -*-

from __future__ import annotations

from typing import Optional

from fastapi import Depends
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from backend.api.app_services import get_auth_application_service
from backend.application.services import AuthApplicationService
from backend.contracts.errors import ErrorCode, AppException, forbidden, not_found, unauthorized
from backend.models.user import User
from backend.utils.logger import get_logger


logger = get_logger(__name__)
security = HTTPBearer()


async def get_current_token_payload(
    credentials: HTTPAuthorizationCredentials = Depends(security),
) -> dict:
    auth_service: AuthApplicationService = get_auth_application_service()

    try:
        return await auth_service.validate_access_token(access_token=credentials.credentials)
    except ValueError as error:
        logger.warning("Invalid bearer token: %s", error)
        normalized_error = str(error).lower()
        error_detail = "token expired" if "expired" in normalized_error else "invalid token"
        error_code = ErrorCode.AUTH_TOKEN_EXPIRED if "expired" in normalized_error else ErrorCode.AUTH_INVALID_TOKEN
        raise unauthorized(
            error_detail,
            error_code=error_code,
            error="InvalidBearerToken",
            headers={"WWW-Authenticate": "Bearer"},
        ) from error


async def get_current_user_id(
    credentials: HTTPAuthorizationCredentials = Depends(security),
) -> str:
    payload = await get_current_token_payload(credentials)
    user_id = payload.get("user_id")
    if not user_id:
        logger.warning("Token payload missing user_id")
        raise unauthorized(
            "invalid token",
            error_code=ErrorCode.AUTH_INVALID_TOKEN,
            error="InvalidBearerToken",
            headers={"WWW-Authenticate": "Bearer"},
        )

    return user_id


async def get_current_user(
    user_id: str = Depends(get_current_user_id),
) -> User:
    auth_service: AuthApplicationService = get_auth_application_service()

    try:
        return await auth_service.get_active_user(user_id=user_id)
    except LookupError as error:
        logger.warning("User not found: %s", user_id)
        raise not_found("用户不存在", error_code=ErrorCode.USER_NOT_FOUND, error="UserNotFound") from error
    except PermissionError as error:
        logger.warning("Inactive user attempted access: %s", user_id)
        raise forbidden("用户账号未激活", error_code=ErrorCode.SYSTEM_FORBIDDEN, error="InactiveUser") from error


async def get_optional_current_user_id(
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(HTTPBearer(auto_error=False)),
) -> Optional[str]:
    if not credentials:
        return None

    try:
        return await get_current_user_id(credentials)
    except AppException:
        return None


def verify_user_access(
    resource_user_id: str,
    current_user_id: str,
) -> None:
    if resource_user_id != current_user_id:
        logger.warning(
            "Access denied: user %s attempted to access user %s resource",
            current_user_id,
            resource_user_id,
        )
        raise forbidden("您没有权限访问此资源", error_code=ErrorCode.SYSTEM_FORBIDDEN, error="UserAccessDenied")


def require_admin(
    current_user: User = Depends(get_current_user),
) -> User:
    if not getattr(current_user, "is_admin", False):
        raise forbidden("需要管理员权限", error_code=ErrorCode.SYSTEM_FORBIDDEN, error="AdminRequired")
    return current_user
