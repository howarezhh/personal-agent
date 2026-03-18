# -*- coding: utf-8 -*-

"""middleware 接口模块。

本文件位于接口层，负责参数校验、依赖注入、统一响应包装，以及将请求转交给应用服务。
"""

import time
import uuid
from typing import Callable
from fastapi import Request, Response
from starlette.middleware.base import BaseHTTPMiddleware
from backend.utils.logger import get_logger


# 模块级日志记录器：统一记录当前接口模块的运行日志。
logger = get_logger(__name__)


class RequestIDMiddleware(BaseHTTPMiddleware):
    """RequestIDMiddleware 相关的数据结构定义。

该类型用于承载接口层输入、输出或中间处理数据。
    """
    async def dispatch(self, request: Request, call_next: Callable) -> Response:
        # 生成请求ID
        """处理 `dispatch` 相关逻辑。

Args:
    request: 参数 `request` 的业务输入值。
    call_next: 参数 `call_next` 的业务输入值。

Returns:
    返回接口层所需的响应对象、业务结果或中间处理结果。
        """
        request_id = str(uuid.uuid4())

        # 将请求ID添加到请求状态中
        request.state.request_id = request_id

        # 处理请求
        response = await call_next(request)

        # 将请求ID添加到响应头
        response.headers["X-Request-ID"] = request_id

        return response


class PerformanceMonitorMiddleware(BaseHTTPMiddleware):
    """PerformanceMonitorMiddleware 相关的数据结构定义。

该类型用于承载接口层输入、输出或中间处理数据。
    """
    def __init__(self, app, slow_request_threshold: float = 1.0):
        """处理 `__init__` 相关逻辑。

Args:
    app: 参数 `app` 的业务输入值。
    slow_request_threshold: 参数 `slow_request_threshold` 的业务输入值。

Returns:
    返回接口层所需的响应对象、业务结果或中间处理结果。
        """
        super().__init__(app)
        self.slow_request_threshold = slow_request_threshold

    async def dispatch(self, request: Request, call_next: Callable) -> Response:
        # 记录开始时间
        """处理 `dispatch` 相关逻辑。

Args:
    request: 参数 `request` 的业务输入值。
    call_next: 参数 `call_next` 的业务输入值。

Returns:
    返回接口层所需的响应对象、业务结果或中间处理结果。
        """
        start_time = time.time()

        # 处理请求
        response = await call_next(request)

        # 计算处理时间
        process_time = time.time() - start_time

        # 将处理时间添加到响应头
        response.headers["X-Process-Time"] = f"{process_time:.4f}"

        # 记录慢请求
        if process_time > self.slow_request_threshold:
            logger.warning(
                f"检测到慢请求: {request.method} {request.url.path} "
                f"耗时 {process_time:.4f}秒 (阈值: {self.slow_request_threshold}秒)"
            )
        else:
            logger.debug(
                f"请求完成: {request.method} {request.url.path} "
                f"耗时 {process_time:.4f}秒"
            )

        return response


class RateLimitMiddleware(BaseHTTPMiddleware):
    """RateLimitMiddleware 相关的数据结构定义。

该类型用于承载接口层输入、输出或中间处理数据。
    """
    def __init__(self, app, max_requests: int = 100, window_seconds: int = 60):
        """处理 `__init__` 相关逻辑。

Args:
    app: 参数 `app` 的业务输入值。
    max_requests: 参数 `max_requests` 的业务输入值。
    window_seconds: 参数 `window_seconds` 的业务输入值。

Returns:
    返回接口层所需的响应对象、业务结果或中间处理结果。
        """
        super().__init__(app)
        self.max_requests = max_requests
        self.window_seconds = window_seconds
        # 简单的内存存储（生产环境应使用Redis）
        self.request_counts = {}

    async def dispatch(self, request: Request, call_next: Callable) -> Response:
        # 获取客户端IP
        """处理 `dispatch` 相关逻辑。

Args:
    request: 参数 `request` 的业务输入值。
    call_next: 参数 `call_next` 的业务输入值。

Returns:
    返回接口层所需的响应对象、业务结果或中间处理结果。
        """
        client_ip = request.client.host if request.client else "unknown"

        # 当前时间戳
        current_time = time.time()

        # 清理过期的记录
        self._cleanup_expired_records(current_time)

        # 检查速率限制
        if client_ip in self.request_counts:
            count, first_request_time = self.request_counts[client_ip]

            # 如果在时间窗口内
            if current_time - first_request_time < self.window_seconds:
                if count >= self.max_requests:
                    logger.warning(
                        f"速率限制超出，IP: {client_ip}: "
                        f"{count} 次请求在 {current_time - first_request_time:.2f}秒内"
                    )
                    return Response(
                        content="速率限制超出，请稍后再试",
                        status_code=429,
                        headers={
                            "X-RateLimit-Limit": str(self.max_requests),
                            "X-RateLimit-Remaining": "0",
                            "X-RateLimit-Reset": str(int(first_request_time + self.window_seconds))
                        }
                    )

                # 增加计数
                self.request_counts[client_ip] = (count + 1, first_request_time)
            else:
                # 重置计数
                self.request_counts[client_ip] = (1, current_time)
        else:
            # 首次请求
            self.request_counts[client_ip] = (1, current_time)

        # 处理请求
        response = await call_next(request)

        # 添加速率限制信息到响应头
        count, first_request_time = self.request_counts[client_ip]
        response.headers["X-RateLimit-Limit"] = str(self.max_requests)
        response.headers["X-RateLimit-Remaining"] = str(max(0, self.max_requests - count))
        response.headers["X-RateLimit-Reset"] = str(int(first_request_time + self.window_seconds))

        return response

    def _cleanup_expired_records(self, current_time: float):
        """处理 `_cleanup_expired_records` 相关逻辑。

Args:
    current_time: 参数 `current_time` 的业务输入值。

Returns:
    返回接口层所需的响应对象、业务结果或中间处理结果。
        """
        expired_ips = [
            ip for ip, (_, first_time) in self.request_counts.items()
            if current_time - first_time >= self.window_seconds
        ]

        for ip in expired_ips:
            del self.request_counts[ip]


class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    """SecurityHeadersMiddleware 相关的数据结构定义。

该类型用于承载接口层输入、输出或中间处理数据。
    """
    async def dispatch(self, request: Request, call_next: Callable) -> Response:
        """处理 `dispatch` 相关逻辑。

Args:
    request: 参数 `request` 的业务输入值。
    call_next: 参数 `call_next` 的业务输入值。

Returns:
    返回接口层所需的响应对象、业务结果或中间处理结果。
        """
        response = await call_next(request)

        # 添加安全头
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["X-XSS-Protection"] = "1; mode=block"
        response.headers["Strict-Transport-Security"] = "max-age=31536000; includeSubDomains"

        return response


