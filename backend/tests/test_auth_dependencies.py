import pytest
from fastapi import HTTPException
from fastapi.security import HTTPAuthorizationCredentials

from backend.api import dependencies


class FakeJWTManager:
    def __init__(self, is_valid=True, payload=None, error=None):
        self._is_valid = is_valid
        self._payload = payload or {}
        self._error = error

    def verify_token(self, token: str):
        return self._is_valid, self._payload, self._error


class FakeRevocationStore:
    def __init__(self, revoked_sessions=None):
        self.revoked_sessions = set(revoked_sessions or [])

    def is_session_revoked(self, session_id):
        return session_id in self.revoked_sessions


@pytest.mark.asyncio
async def test_get_current_user_id_rejects_refresh_tokens(monkeypatch):
    monkeypatch.setattr(
        dependencies,
        "get_jwt_manager",
        lambda: FakeJWTManager(payload={"type": "refresh", "user_id": "user-1", "sid": "sid-1"}),
    )
    monkeypatch.setattr(dependencies, "get_token_revocation_store", lambda: FakeRevocationStore())

    with pytest.raises(HTTPException) as exc_info:
        await dependencies.get_current_user_id(HTTPAuthorizationCredentials(scheme="Bearer", credentials="refresh-token"))

    assert exc_info.value.status_code == 401
    assert "invalid token" in str(exc_info.value.detail).lower()


@pytest.mark.asyncio
async def test_get_current_user_id_rejects_revoked_sessions(monkeypatch):
    monkeypatch.setattr(
        dependencies,
        "get_jwt_manager",
        lambda: FakeJWTManager(payload={"type": "access", "user_id": "user-1", "sid": "sid-1"}),
    )
    monkeypatch.setattr(dependencies, "get_token_revocation_store", lambda: FakeRevocationStore(revoked_sessions={"sid-1"}))

    with pytest.raises(HTTPException) as exc_info:
        await dependencies.get_current_user_id(HTTPAuthorizationCredentials(scheme="Bearer", credentials="access-token"))

    assert exc_info.value.status_code == 401
    assert "invalid token" in str(exc_info.value.detail).lower()
