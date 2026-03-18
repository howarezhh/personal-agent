# -*- coding: utf-8 -*-

from __future__ import annotations

from fastapi import APIRouter, Depends, status

from backend.api.app_services import get_auth_application_service
from backend.api.dependencies import get_current_token_payload, get_current_user_id
from backend.contracts.api.auth import (
    LoginRequest,
    LogoutResponse,
    RefreshTokenRequest,
    RegisterRequest,
    TokenResponse,
    UserProfileResponse,
)
from backend.contracts.errors import (
    ErrorCode,
    bad_request,
    internal_server_error,
    not_found,
    unauthorized,
)
from backend.contracts.responses import SuccessResponse
from backend.middleware.csrf_protection import csrf_exempt
from backend.utils.logger import get_logger


logger = get_logger(__name__)
router = APIRouter(prefix="/api/v1/auth", tags=["authentication"])


@router.post("/register", response_model=SuccessResponse[TokenResponse], status_code=status.HTTP_201_CREATED)
@csrf_exempt
async def register(request: RegisterRequest):
    try:
        payload = await get_auth_application_service().register(
            username=request.username,
            email=request.email,
            password=request.password,
            full_name=request.full_name,
        )
        return SuccessResponse.create(data=TokenResponse(**payload), code=status.HTTP_201_CREATED)
    except ValueError as error:
        raise bad_request(str(error), error_code=ErrorCode.SYSTEM_VALIDATION_ERROR, error="RegisterValidationError") from error
    except Exception as error:
        logger.error("Register failed: %s", error, exc_info=True)
        raise internal_server_error("注册失败") from error


@router.post("/login", response_model=SuccessResponse[TokenResponse])
@csrf_exempt
async def login(request: LoginRequest):
    try:
        payload = await get_auth_application_service().login(
            username_or_email=request.username_or_email,
            password=request.password,
        )
        if not payload:
            raise unauthorized("用户名、邮箱或密码错误", error_code=ErrorCode.AUTH_INVALID_CREDENTIALS, error="LoginFailed")
        return SuccessResponse.create(data=TokenResponse(**payload))
    except ValueError as error:
        raise bad_request(str(error), error_code=ErrorCode.SYSTEM_VALIDATION_ERROR, error="LoginValidationError") from error
    except Exception as error:
        logger.error("Login failed: %s", error, exc_info=True)
        raise internal_server_error("登录失败") from error


@router.post("/logout", response_model=SuccessResponse[LogoutResponse])
async def logout(token_payload: dict = Depends(get_current_token_payload)):
    try:
        payload = await get_auth_application_service().logout(
            user_id=token_payload["user_id"],
            session_id=token_payload.get("sid"),
        )
        return SuccessResponse.create(data=LogoutResponse(**payload))
    except Exception as error:
        logger.error("Logout failed: %s", error, exc_info=True)
        raise internal_server_error("退出登录失败") from error


@router.get("/profile", response_model=SuccessResponse[UserProfileResponse])
async def get_profile(user_id: str = Depends(get_current_user_id)):
    try:
        user = await get_auth_application_service().get_profile(user_id=user_id)
        if not user:
            raise not_found("用户不存在", error_code=ErrorCode.USER_NOT_FOUND, error="UserNotFound")
        return SuccessResponse.create(
            data=UserProfileResponse(
                user_id=user.user_id,
                username=user.username,
                email=user.email,
                full_name=user.full_name,
                avatar_url=getattr(user, "avatar_url", None),
                is_active=user.is_active,
                created_at=user.created_at.isoformat() if user.created_at else "",
            )
        )
    except Exception as error:
        if getattr(error, "status_code", None):
            raise
        logger.error("Get profile failed: %s", error, exc_info=True)
        raise internal_server_error("获取用户资料失败") from error


@router.post("/refresh", response_model=SuccessResponse[TokenResponse])
@csrf_exempt
async def refresh_token(request: RefreshTokenRequest):
    try:
        payload = await get_auth_application_service().refresh(refresh_token=request.refresh_token)
        return SuccessResponse.create(data=TokenResponse(**payload))
    except ValueError as error:
        raise unauthorized(str(error), error_code=ErrorCode.AUTH_INVALID_TOKEN, error="RefreshTokenInvalid") from error
    except Exception as error:
        logger.error("Refresh token failed: %s", error, exc_info=True)
        raise internal_server_error("刷新令牌失败") from error
