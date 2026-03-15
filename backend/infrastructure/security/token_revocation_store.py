
from __future__ import annotations

import time
from threading import Lock

from backend.core.config_manager import get_config_manager
from backend.utils.logger import get_logger

try:
    import redis

    REDIS_AVAILABLE = True
except ImportError:
    redis = None
    REDIS_AVAILABLE = False


logger = get_logger(__name__)


class TokenRevocationStore:
    SESSION_PREFIX = "auth:revoked_session:"
    REFRESH_PREFIX = "auth:revoked_refresh:"

    def __init__(self, redis_client=None):
        self.redis_client = redis_client
        self.use_redis = redis_client is not None
        self._memory_store: dict[str, int] = {}
        self._lock = Lock()

        if self.use_redis:
            logger.info("Token revocation store initialized with Redis backend")
        else:
            logger.warning("Token revocation store initialized with memory backend")

    def revoke_session(self, session_id: str, ttl_seconds: int) -> None:
        self._set(self._session_key(session_id), ttl_seconds)

    def is_session_revoked(self, session_id: str | None) -> bool:
        if not session_id:
            return False
        return self._exists(self._session_key(session_id))

    def revoke_refresh_token(self, token_jti: str, ttl_seconds: int) -> None:
        self._set(self._refresh_key(token_jti), ttl_seconds)

    def is_refresh_token_revoked(self, token_jti: str | None) -> bool:
        if not token_jti:
            return False
        return self._exists(self._refresh_key(token_jti))

    def _session_key(self, session_id: str) -> str:
        return f"{self.SESSION_PREFIX}{session_id}"

    def _refresh_key(self, token_jti: str) -> str:
        return f"{self.REFRESH_PREFIX}{token_jti}"

    def _set(self, key: str, ttl_seconds: int) -> None:
        ttl = max(int(ttl_seconds), 1)
        if self.use_redis:
            try:
                self.redis_client.setex(key, ttl, "1")
                return
            except Exception as error:
                logger.error("Failed to write revocation entry to Redis: %s", error)

        self._set_memory(key, ttl)

    def _exists(self, key: str) -> bool:
        if self.use_redis:
            try:
                return bool(self.redis_client.exists(key))
            except Exception as error:
                logger.error("Failed to read revocation entry from Redis: %s", error)

        return self._exists_memory(key)

    def _set_memory(self, key: str, ttl_seconds: int) -> None:
        expires_at = int(time.time()) + ttl_seconds
        with self._lock:
            self._memory_store[key] = expires_at
            self._prune_memory_locked(int(time.time()))

    def _exists_memory(self, key: str) -> bool:
        now = int(time.time())
        with self._lock:
            self._prune_memory_locked(now)
            expires_at = self._memory_store.get(key)
            return bool(expires_at and expires_at > now)

    def _prune_memory_locked(self, now: int) -> None:
        expired_keys = [key for key, expires_at in self._memory_store.items() if expires_at <= now]
        for key in expired_keys:
            self._memory_store.pop(key, None)


def _build_redis_client():
    if not REDIS_AVAILABLE:
        logger.warning("Redis module not installed, token revocation uses memory backend")
        return None

    config_manager = get_config_manager()
    redis_config = config_manager.get_database_config("redis")
    if not redis_config:
        return None

    host = redis_config.get("host")
    port = redis_config.get("port")
    if not host or not port:
        return None

    try:
        client = redis.Redis(
            host=host,
            port=port,
            db=redis_config.get("db", 0),
            password=redis_config.get("password"),
            decode_responses=True,
            socket_connect_timeout=1,
            socket_timeout=1,
        )
        client.ping()
        return client
    except Exception as error:
        logger.warning("Redis unavailable for token revocation, falling back to memory: %s", error)
        return None


_token_revocation_store: TokenRevocationStore | None = None


def get_token_revocation_store() -> TokenRevocationStore:
    global _token_revocation_store

    if _token_revocation_store is None:
        _token_revocation_store = TokenRevocationStore(redis_client=_build_redis_client())

    return _token_revocation_store
