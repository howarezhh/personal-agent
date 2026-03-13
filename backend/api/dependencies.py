"""Common API dependencies."""

from __future__ import annotations

from typing import Optional

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from backend.database.repositories.user_repository import get_user_repository
from backend.infrastructure.security import get_token_revocation_store
from backend.models.user import User
from backend.utils.jwt_utils import get_jwt_manager
from backend.utils.logger import get_logger


logger = get_logger(__name__)

security = HTTPBearer()


async def get_current_token_payload(
    credentials: HTTPAuthorizationCredentials = Depends(security),
) -> dict:
    token = credentials.credentials
    jwt_manager = get_jwt_manager()
    token_revocation_store = get_token_revocation_store()

    is_valid, payload, error = jwt_manager.verify_token(token)
    if not is_valid or not payload:
        logger.warning("Invalid bearer token: %s", error)
        normalized_error = (error or "").lower()
        error_detail = "token expired" if "expired" in normalized_error or "过期" in normalized_error else "invalid token"
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=error_detail,
            headers={"WWW-Authenticate": "Bearer"},
        )

    if payload.get("type") != "access":
        logger.warning("Non-access token used for protected endpoint")
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="invalid token",
            headers={"WWW-Authenticate": "Bearer"},
        )

    if token_revocation_store.is_session_revoked(payload.get("sid")):
        logger.warning("Revoked session attempted to access protected endpoint: %s", payload.get("sid"))
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="invalid token",
            headers={"WWW-Authenticate": "Bearer"},
        )

    return payload


async def get_current_user_id(
    credentials: HTTPAuthorizationCredentials = Depends(security),
) -> str:
    payload = await get_current_token_payload(credentials)
    user_id = payload.get("user_id")
    if not user_id:
        logger.warning("Token payload missing user_id")
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="invalid token",
            headers={"WWW-Authenticate": "Bearer"},
        )

    return user_id


async def get_current_user(
    user_id: str = Depends(get_current_user_id),
) -> User:
    user_repo = get_user_repository()
    user = user_repo.get_user_by_id(user_id)

    if not user:
        logger.warning("User not found: %s", user_id)
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="用户不存在")

    if not user.is_active:
        logger.warning("Inactive user attempted access: %s", user_id)
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="用户账号未激活")

    return user


async def get_optional_current_user_id(
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(HTTPBearer(auto_error=False)),
) -> Optional[str]:
    if not credentials:
        return None

    try:
        return await get_current_user_id(credentials)
    except HTTPException:
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
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="您没有权限访问此资源")


def require_admin(
    current_user: User = Depends(get_current_user),
) -> User:
    if not getattr(current_user, "is_admin", False):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="需要管理员权限")
    return current_user
