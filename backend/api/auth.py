
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, EmailStr, Field

from backend.api.dependencies import get_current_token_payload, get_current_user_id
from backend.api.models import SuccessResponse
from backend.application.services import AuthApplicationService
from backend.database.repositories.user_repository import get_user_repository
from backend.infrastructure.persistence import UserRepositoryAdapter
from backend.infrastructure.security import JWTTokenGateway, PasswordHashGateway, get_token_revocation_store
from backend.middleware.csrf_protection import csrf_exempt
from backend.utils.jwt_utils import get_jwt_manager
from backend.utils.logger import get_logger


logger = get_logger(__name__)
router = APIRouter(prefix="/api/v1/auth", tags=["authentication"])


def get_auth_application_service() -> AuthApplicationService:
    return AuthApplicationService(
        user_repo=UserRepositoryAdapter(repository=get_user_repository()),
        token_gateway=JWTTokenGateway(manager=get_jwt_manager()),
        password_gateway=PasswordHashGateway(),
        token_revocation_store=get_token_revocation_store(),
    )


class RegisterRequest(BaseModel):
    username: str = Field(..., min_length=3, max_length=50, description="用户名")
    email: EmailStr = Field(..., description="邮箱")
    password: str = Field(..., min_length=8, max_length=100, description="密码")
    full_name: str | None = Field(default=None, max_length=100, description="全名")


class LoginRequest(BaseModel):
    username_or_email: str = Field(..., description="用户名或邮箱")
    password: str = Field(..., description="密码")


class TokenResponse(BaseModel):
    access_token: str = Field(..., description="访问令牌")
    refresh_token: str = Field(..., description="刷新令牌")
    token_type: str = Field(default="bearer", description="令牌类型")
    user_id: str = Field(..., description="用户 ID")
    username: str = Field(..., description="用户名")


class UserProfileResponse(BaseModel):
    user_id: str
    username: str
    email: str
    full_name: str | None
    avatar_url: str | None
    is_active: bool
    created_at: str


class RefreshTokenRequest(BaseModel):
    refresh_token: str = Field(..., description="刷新令牌")


class LogoutResponse(BaseModel):
    message: str
    user_id: str


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
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(error))
    except Exception as error:
        logger.error("Register failed: %s", error, exc_info=True)
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="注册失败")


@router.post("/login", response_model=SuccessResponse[TokenResponse])
@csrf_exempt
async def login(request: LoginRequest):
    try:
        payload = await get_auth_application_service().login(
            username_or_email=request.username_or_email,
            password=request.password,
        )
        if not payload:
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="用户名、邮箱或密码错误")
        return SuccessResponse.create(data=TokenResponse(**payload))
    except HTTPException:
        raise
    except ValueError as error:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(error))
    except Exception as error:
        logger.error("Login failed: %s", error, exc_info=True)
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="登录失败")


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
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="退出登录失败")


@router.get("/profile", response_model=SuccessResponse[UserProfileResponse])
async def get_profile(user_id: str = Depends(get_current_user_id)):
    try:
        user = await get_auth_application_service().get_profile(user_id=user_id)
        if not user:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="用户不存在")
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
    except HTTPException:
        raise
    except Exception as error:
        logger.error("Get profile failed: %s", error, exc_info=True)
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="获取用户资料失败")


@router.post("/refresh", response_model=SuccessResponse[TokenResponse])
@csrf_exempt
async def refresh_token(request: RefreshTokenRequest):
    try:
        payload = await get_auth_application_service().refresh(refresh_token=request.refresh_token)
        return SuccessResponse.create(data=TokenResponse(**payload))
    except ValueError as error:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail=str(error))
    except Exception as error:
        logger.error("Refresh token failed: %s", error, exc_info=True)
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="刷新令牌失败")
