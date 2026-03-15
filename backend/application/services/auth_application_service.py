
from __future__ import annotations

import asyncio
from datetime import datetime
from uuid import uuid4

from backend.infrastructure.persistence import UserRepositoryAdapter
from backend.infrastructure.security import JWTTokenGateway, PasswordHashGateway, get_token_revocation_store
from backend.models.user import User, UserCreate, UserLogin


class AuthApplicationService:
    def __init__(self, user_repo=None, token_gateway=None, password_gateway=None, token_revocation_store=None):
        self.user_repo = user_repo or UserRepositoryAdapter()
        self.token_gateway = token_gateway or JWTTokenGateway()
        self.password_gateway = password_gateway or PasswordHashGateway()
        self.token_revocation_store = token_revocation_store or get_token_revocation_store()

    async def register(self, *, username: str, email: str, password: str, full_name: str | None = None):
        user_create = UserCreate(username=username, email=email, password=password, full_name=full_name)
        is_valid, error_msg = user_create.validate()
        if not is_valid:
            raise ValueError(error_msg)

        normalized_username = user_create.username.strip()
        normalized_email = user_create.email.strip()

        username_exists = await asyncio.to_thread(self.user_repo.exists_by_username, normalized_username)
        if username_exists:
            raise ValueError(f"用户名 '{normalized_username}' 已存在")

        email_exists = await asyncio.to_thread(self.user_repo.exists_by_email, normalized_email)
        if email_exists:
            raise ValueError(f"邮箱 '{normalized_email}' 已存在")

        password_hash = await asyncio.to_thread(self.password_gateway.hash_password, user_create.password)
        now = datetime.utcnow()
        user = User(
            username=normalized_username,
            email=normalized_email,
            password_hash=password_hash,
            full_name=user_create.full_name,
            created_at=now,
            updated_at=now,
        )

        user = await asyncio.to_thread(self.user_repo.create_user, user)
        return self._build_token_payload(user.user_id, user.username)

    async def login(self, *, username_or_email: str, password: str):
        user_login = UserLogin(username_or_email=username_or_email, password=password)
        is_valid, error_msg = user_login.validate()
        if not is_valid:
            raise ValueError(error_msg)

        if "@" in user_login.username_or_email:
            user = await asyncio.to_thread(self.user_repo.get_user_by_email, user_login.username_or_email)
        else:
            user = await asyncio.to_thread(self.user_repo.get_user_by_username, user_login.username_or_email)

        if not user or not user.is_active:
            return None

        password_matches = await asyncio.to_thread(
            self.password_gateway.verify_password,
            user_login.password,
            user.password_hash,
        )
        if not password_matches:
            return None

        await asyncio.to_thread(self.user_repo.update_last_login, user.user_id)
        return self._build_token_payload(user.user_id, user.username)

    async def get_profile(self, *, user_id: str):
        return await asyncio.to_thread(self.user_repo.get_user_by_id, user_id)

    async def refresh(self, *, refresh_token: str):
        is_valid, payload, error = self.token_gateway.verify_token(refresh_token)
        if not is_valid or not payload:
            raise ValueError(error or "invalid token")
        if payload.get("type") != "refresh":
            raise ValueError("invalid token")

        session_id = payload.get("sid")
        refresh_jti = payload.get("jti")
        if self.token_revocation_store.is_session_revoked(session_id):
            raise ValueError("invalid token")
        if self.token_revocation_store.is_refresh_token_revoked(refresh_jti):
            raise ValueError("invalid token")

        user = await asyncio.to_thread(self.user_repo.get_user_by_id, payload["user_id"])
        if not user or not user.is_active:
            raise ValueError("invalid token")

        if refresh_jti:
            self.token_revocation_store.revoke_refresh_token(refresh_jti, self._resolve_refresh_token_ttl_seconds(refresh_token))

        return self._build_token_payload(user.user_id, user.username, session_id=session_id)

    async def logout(self, *, user_id: str, session_id: str | None = None):
        if session_id:
            self.token_revocation_store.revoke_session(session_id, self._get_session_ttl_seconds())
        return {"message": "Logged out successfully", "user_id": user_id}

    def _build_token_payload(self, user_id: str, username: str, session_id: str | None = None):
        session_id = session_id or str(uuid4())
        return {
            "access_token": self._generate_access_token(user_id, username, session_id),
            "refresh_token": self._generate_refresh_token(user_id, username, session_id),
            "token_type": "bearer",
            "user_id": user_id,
            "username": username,
        }

    def _generate_access_token(self, user_id: str, username: str, session_id: str) -> str:
        claims = {"sid": session_id}
        try:
            return self.token_gateway.generate_access_token(user_id, username, claims)
        except TypeError:
            return self.token_gateway.generate_access_token(user_id, username)

    def _generate_refresh_token(self, user_id: str, username: str, session_id: str) -> str:
        claims = {"sid": session_id, "jti": str(uuid4())}
        try:
            return self.token_gateway.generate_refresh_token(user_id, username, claims)
        except TypeError:
            return self.token_gateway.generate_refresh_token(user_id, username)

    def _get_session_ttl_seconds(self) -> int:
        refresh_days = getattr(self.token_gateway, "refresh_token_expire_days", None)
        if refresh_days is None and hasattr(self.token_gateway, "manager"):
            refresh_days = getattr(self.token_gateway.manager, "refresh_token_expire_days", None)
        refresh_days = refresh_days or 30
        return int(refresh_days * 24 * 60 * 60)

    def _resolve_refresh_token_ttl_seconds(self, refresh_token: str) -> int:
        expiration = None
        if hasattr(self.token_gateway, "get_token_expiration"):
            expiration = self.token_gateway.get_token_expiration(refresh_token)
        if expiration is None and hasattr(self.token_gateway, "manager"):
            expiration = getattr(self.token_gateway.manager, "get_token_expiration", lambda _token: None)(refresh_token)
        if expiration is None:
            return self._get_session_ttl_seconds()

        remaining_seconds = int((expiration - datetime.utcnow()).total_seconds())
        return max(remaining_seconds, 1)
