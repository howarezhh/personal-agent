from __future__ import annotations

from pydantic import BaseModel, EmailStr, Field


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
