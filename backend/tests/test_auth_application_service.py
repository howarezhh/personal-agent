from datetime import datetime, timedelta

import pytest

from backend.application.services.auth_application_service import AuthApplicationService
from backend.models.user import User


class FakeUserRepository:
    def __init__(self):
        self.users: list[User] = []
        self.last_login_updates: list[str] = []

    def create_user(self, user: User) -> User:
        self.users.append(user)
        return user

    def get_user_by_id(self, user_id: str):
        return next((user for user in self.users if user.user_id == user_id), None)

    def get_user_by_username(self, username: str):
        return next((user for user in self.users if user.username == username), None)

    def get_user_by_email(self, email: str):
        return next((user for user in self.users if user.email == email), None)

    def exists_by_username(self, username: str) -> bool:
        return any(user.username == username for user in self.users)

    def exists_by_email(self, email: str) -> bool:
        return any(user.email == email for user in self.users)

    def update_last_login(self, user_id: str) -> bool:
        self.last_login_updates.append(user_id)
        return True


class FakeTokenGateway:
    refresh_token_expire_days = 30

    def __init__(self):
        self.last_access_claims = None
        self.last_refresh_claims = None
        self.refresh_verify_result = (True, {"type": "refresh", "user_id": "user-1", "username": "alice", "sid": "sid-1", "jti": "refresh-jti-1"}, None)

    def generate_access_token(self, user_id: str, username: str, additional_claims=None) -> str:
        self.last_access_claims = additional_claims or {}
        sid = self.last_access_claims.get("sid", "missing")
        return f"access:{user_id}:{username}:{sid}"

    def generate_refresh_token(self, user_id: str, username: str, additional_claims=None) -> str:
        self.last_refresh_claims = additional_claims or {}
        sid = self.last_refresh_claims.get("sid", "missing")
        jti = self.last_refresh_claims.get("jti", "missing")
        return f"refresh:{user_id}:{username}:{sid}:{jti}"

    def verify_token(self, refresh_token: str):
        return self.refresh_verify_result

    def get_token_expiration(self, refresh_token: str):
        return datetime.utcnow() + timedelta(minutes=10)


class FakePasswordGateway:
    def hash_password(self, password: str) -> str:
        return f"hashed::{password}"

    def verify_password(self, password: str, password_hash: str) -> bool:
        return password_hash == f"hashed::{password}"


class FakeTokenRevocationStore:
    def __init__(self):
        self.revoked_sessions: list[tuple[str, int]] = []
        self.revoked_refresh_tokens: list[tuple[str, int]] = []
        self.blocked_sessions: set[str] = set()
        self.blocked_refresh_tokens: set[str] = set()

    def revoke_session(self, session_id: str, ttl_seconds: int) -> None:
        self.revoked_sessions.append((session_id, ttl_seconds))

    def is_session_revoked(self, session_id: str | None) -> bool:
        return bool(session_id and session_id in self.blocked_sessions)

    def revoke_refresh_token(self, token_jti: str, ttl_seconds: int) -> None:
        self.revoked_refresh_tokens.append((token_jti, ttl_seconds))

    def is_refresh_token_revoked(self, token_jti: str | None) -> bool:
        return bool(token_jti and token_jti in self.blocked_refresh_tokens)


def make_user(
    *,
    user_id: str = "user-1",
    username: str = "alice",
    email: str = "alice@example.com",
    password_hash: str = "hashed::Password1",
    is_active: bool = True,
) -> User:
    now = datetime.utcnow()
    return User(
        user_id=user_id,
        username=username,
        email=email,
        password_hash=password_hash,
        is_active=is_active,
        created_at=now,
        updated_at=now,
    )


@pytest.mark.asyncio
async def test_register_hashes_password_and_persists_user():
    user_repo = FakeUserRepository()
    service = AuthApplicationService(
        user_repo=user_repo,
        token_gateway=FakeTokenGateway(),
        password_gateway=FakePasswordGateway(),
        token_revocation_store=FakeTokenRevocationStore(),
    )

    payload = await service.register(
        username="alice",
        email="alice@example.com",
        password="Password1",
        full_name="Alice",
    )

    assert payload["username"] == "alice"
    assert len(user_repo.users) == 1
    assert user_repo.users[0].password_hash == "hashed::Password1"


@pytest.mark.asyncio
async def test_register_rejects_duplicate_username():
    user_repo = FakeUserRepository()
    user_repo.users.append(make_user(username="alice", email="old@example.com"))
    service = AuthApplicationService(
        user_repo=user_repo,
        token_gateway=FakeTokenGateway(),
        password_gateway=FakePasswordGateway(),
        token_revocation_store=FakeTokenRevocationStore(),
    )

    with pytest.raises(ValueError, match="用户名"):
        await service.register(
            username="alice",
            email="alice@example.com",
            password="Password1",
        )


@pytest.mark.asyncio
async def test_login_validates_password_and_updates_last_login():
    user_repo = FakeUserRepository()
    user_repo.users.append(make_user())
    service = AuthApplicationService(
        user_repo=user_repo,
        token_gateway=FakeTokenGateway(),
        password_gateway=FakePasswordGateway(),
        token_revocation_store=FakeTokenRevocationStore(),
    )

    payload = await service.login(username_or_email="alice", password="Password1")

    assert payload is not None
    assert user_repo.last_login_updates == ["user-1"]


@pytest.mark.asyncio
async def test_login_returns_none_for_inactive_user_or_wrong_password():
    user_repo = FakeUserRepository()
    user_repo.users.append(make_user(user_id="user-1", username="alice", is_active=False))
    user_repo.users.append(make_user(user_id="user-2", username="bob", email="bob@example.com"))
    service = AuthApplicationService(
        user_repo=user_repo,
        token_gateway=FakeTokenGateway(),
        password_gateway=FakePasswordGateway(),
        token_revocation_store=FakeTokenRevocationStore(),
    )

    inactive_result = await service.login(username_or_email="alice", password="Password1")
    wrong_password_result = await service.login(username_or_email="bob@example.com", password="WrongPass1")

    assert inactive_result is None
    assert wrong_password_result is None
    assert user_repo.last_login_updates == []


@pytest.mark.asyncio
async def test_refresh_requires_active_existing_user_and_revokes_old_refresh_token():
    user_repo = FakeUserRepository()
    user_repo.users.append(make_user())
    token_gateway = FakeTokenGateway()
    token_revocation_store = FakeTokenRevocationStore()
    service = AuthApplicationService(
        user_repo=user_repo,
        token_gateway=token_gateway,
        password_gateway=FakePasswordGateway(),
        token_revocation_store=token_revocation_store,
    )

    payload = await service.refresh(refresh_token="refresh-token")

    assert payload["user_id"] == "user-1"
    assert token_revocation_store.revoked_refresh_tokens
    revoked_jti, ttl_seconds = token_revocation_store.revoked_refresh_tokens[0]
    assert revoked_jti == "refresh-jti-1"
    assert ttl_seconds > 0
    assert token_gateway.last_access_claims["sid"] == "sid-1"
    assert token_gateway.last_refresh_claims["sid"] == "sid-1"


@pytest.mark.asyncio
async def test_refresh_rejects_missing_or_inactive_user():
    token_gateway = FakeTokenGateway()
    service = AuthApplicationService(
        user_repo=FakeUserRepository(),
        token_gateway=token_gateway,
        password_gateway=FakePasswordGateway(),
        token_revocation_store=FakeTokenRevocationStore(),
    )

    with pytest.raises(ValueError, match="invalid token"):
        await service.refresh(refresh_token="refresh-token")

    inactive_repo = FakeUserRepository()
    inactive_repo.users.append(make_user(is_active=False))
    inactive_service = AuthApplicationService(
        user_repo=inactive_repo,
        token_gateway=token_gateway,
        password_gateway=FakePasswordGateway(),
        token_revocation_store=FakeTokenRevocationStore(),
    )

    with pytest.raises(ValueError, match="invalid token"):
        await inactive_service.refresh(refresh_token="refresh-token")


@pytest.mark.asyncio
async def test_logout_revokes_current_session():
    token_revocation_store = FakeTokenRevocationStore()
    service = AuthApplicationService(
        user_repo=FakeUserRepository(),
        token_gateway=FakeTokenGateway(),
        password_gateway=FakePasswordGateway(),
        token_revocation_store=token_revocation_store,
    )

    result = await service.logout(user_id="user-1", session_id="sid-1")

    assert result["user_id"] == "user-1"
    assert token_revocation_store.revoked_sessions
    revoked_session_id, ttl_seconds = token_revocation_store.revoked_sessions[0]
    assert revoked_session_id == "sid-1"
    assert ttl_seconds > 0
