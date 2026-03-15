
import time
from typing import Optional, Callable, TYPE_CHECKING
from fastapi import Request, HTTPException, status
from fastapi.responses import JSONResponse

# 将redis导入改为可选的
try:
    import redis
    REDIS_AVAILABLE = True
except ImportError:
    REDIS_AVAILABLE = False
    redis = None

from backend.utils.logger import get_logger
from backend.core.config_manager import get_config_manager

logger = get_logger(__name__)


class RateLimiter:
    def __init__(
        self,
        redis_client: Optional[any] = None,  # 改为any以避免类型检查问题
        default_limit: int = 100,
        default_window: int = 60
    ):
        self.redis_client = redis_client
        self.default_limit = default_limit
        self.default_window = default_window
        self.memory_store = {}  # 内存存储（当Redis不可用时）
        self.use_redis = redis_client is not None

        if self.use_redis:
            logger.info("Rate limiter initialized with Redis backend")
        else:
            logger.warning("Rate limiter initialized with memory backend (not suitable for production)")

    def _get_key(self, identifier: str, endpoint: str) -> str:
        return f"rate_limit:{identifier}:{endpoint}"

    def _check_rate_limit_redis(
        self,
        identifier: str,
        endpoint: str,
        limit: int,
        window: int
    ) -> tuple[bool, int, int]:
        key = self._get_key(identifier, endpoint)
        current_time = int(time.time())
        window_start = current_time - window

        try:
            # 使用Redis的ZSET实现滑动窗口
            pipe = self.redis_client.pipeline()

            # 删除窗口外的旧记录
            pipe.zremrangebyscore(key, 0, window_start)

            # 获取当前窗口内的请求数
            pipe.zcard(key)

            # 添加当前请求
            pipe.zadd(key, {str(current_time): current_time})

            # 设置过期时间
            pipe.expire(key, window)

            results = pipe.execute()
            current_count = results[1]  # zadd之前的计数

            # 检查是否超过限制（注意：current_count是添加前的计数，所以要+1）
            if current_count + 1 > limit:
                # 获取最早的请求时间
                oldest = self.redis_client.zrange(key, 0, 0, withscores=True)
                if oldest:
                    reset_time = int(oldest[0][1]) + window
                else:
                    reset_time = current_time + window

                return False, 0, reset_time

            remaining = limit - current_count - 1
            reset_time = current_time + window

            return True, remaining, reset_time

        except Exception as e:
            logger.error(f"Redis rate limit check failed: {str(e)}")
            # Redis失败时，允许请求通过
            return True, limit, current_time + window

    def _check_rate_limit_memory(
        self,
        identifier: str,
        endpoint: str,
        limit: int,
        window: int
    ) -> tuple[bool, int, int]:
        key = f"{identifier}:{endpoint}"
        current_time = int(time.time())
        window_start = current_time - window

        # 获取或创建记录
        if key not in self.memory_store:
            self.memory_store[key] = []

        # 删除窗口外的旧记录
        self.memory_store[key] = [
            timestamp for timestamp in self.memory_store[key]
            if timestamp > window_start
        ]

        # 检查是否超过限制
        current_count = len(self.memory_store[key])
        if current_count >= limit:
            reset_time = self.memory_store[key][0] + window
            return False, 0, reset_time

        # 添加当前请求
        self.memory_store[key].append(current_time)

        remaining = limit - current_count - 1
        reset_time = current_time + window

        return True, remaining, reset_time

    def check_rate_limit(
        self,
        identifier: str,
        endpoint: str,
        limit: Optional[int] = None,
        window: Optional[int] = None
    ) -> tuple[bool, int, int]:
        limit = limit or self.default_limit
        window = window or self.default_window

        if self.use_redis:
            return self._check_rate_limit_redis(identifier, endpoint, limit, window)
        else:
            return self._check_rate_limit_memory(identifier, endpoint, limit, window)


# 全局速率限制器实例
_rate_limiter: Optional[RateLimiter] = None


def get_rate_limiter() -> RateLimiter:
    global _rate_limiter

    if _rate_limiter is None:
        config_manager = get_config_manager()

        # 尝试连接Redis
        redis_client = None
        if REDIS_AVAILABLE:
            try:
                redis_config = config_manager.get("database.redis", {})
                if redis_config:
                    redis_client = redis.Redis(
                        host=redis_config.get("host", "localhost"),
                        port=redis_config.get("port", 6379),
                        db=redis_config.get("db", 0),
                        password=redis_config.get("password"),
                        decode_responses=True
                    )
                    # 测试连接
                    redis_client.ping()
                    logger.info("Redis连接成功")
            except Exception as e:
                logger.warning(f"Redis连接失败: {str(e)}, 使用内存后端")
                redis_client = None
        else:
            logger.warning("Redis模块未安装，使用内存后端（不适合生产环境）")

        # 获取速率限制配置
        rate_limit_config = config_manager.get("business.rate_limit", {})
        default_limit = rate_limit_config.get("default_limit", 100)
        default_window = rate_limit_config.get("default_window", 60)

        _rate_limiter = RateLimiter(
            redis_client=redis_client,
            default_limit=default_limit,
            default_window=default_window
        )

    return _rate_limiter


async def rate_limit_middleware(
    request: Request,
    call_next: Callable,
    limit: Optional[int] = None,
    window: Optional[int] = None
):
    # 获取标识符（优先使用用户ID，否则使用IP地址）
    identifier = None

    # 尝试从请求中获取用户ID
    if hasattr(request.state, "user_id"):
        identifier = request.state.user_id
    else:
        # 使用IP地址
        identifier = request.client.host if request.client else "unknown"

    # 获取端点路径
    endpoint = request.url.path

    # 检查速率限制
    rate_limiter = get_rate_limiter()
    allowed, remaining, reset_time = rate_limiter.check_rate_limit(
        identifier=identifier,
        endpoint=endpoint,
        limit=limit,
        window=window
    )

    # 添加速率限制响应头
    headers = {
        "X-RateLimit-Limit": str(limit or rate_limiter.default_limit),
        "X-RateLimit-Remaining": str(remaining),
        "X-RateLimit-Reset": str(reset_time)
    }

    if not allowed:
        # 超过速率限制
        logger.warning(f"Rate limit exceeded for {identifier} on {endpoint}")
        return JSONResponse(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            content={
                "success": False,
                "code": 429,
                "message": "请求过于频繁，请稍后再试",
                "error": "TooManyRequests",
                "retry_after": reset_time - int(time.time())
            },
            headers=headers
        )

    # 继续处理请求
    response = await call_next(request)

    # 添加速率限制响应头
    for key, value in headers.items():
        response.headers[key] = value

    return response


def rate_limit(limit: int = 100, window: int = 60):
    def decorator(func):
        async def wrapper(request: Request, *args, **kwargs):
            # 获取标识符
            identifier = None
            if hasattr(request.state, "user_id"):
                identifier = request.state.user_id
            else:
                identifier = request.client.host if request.client else "unknown"

            # 获取端点路径
            endpoint = request.url.path

            # 检查速率限制
            rate_limiter = get_rate_limiter()
            allowed, remaining, reset_time = rate_limiter.check_rate_limit(
                identifier=identifier,
                endpoint=endpoint,
                limit=limit,
                window=window
            )

            if not allowed:
                raise HTTPException(
                    status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                    detail={
                        "message": "请求过于频繁，请稍后再试",
                        "retry_after": reset_time - int(time.time())
                    },
                    headers={
                        "X-RateLimit-Limit": str(limit),
                        "X-RateLimit-Remaining": str(remaining),
                        "X-RateLimit-Reset": str(reset_time),
                        "Retry-After": str(reset_time - int(time.time()))
                    }
                )

            # 执行原函数
            return await func(request, *args, **kwargs)

        return wrapper
    return decorator
