"""
自定义中间件
提供请求处理、日志记录、性能监控等功能
"""

import time
import uuid
from typing import Callable
from fastapi import Request, Response
from starlette.middleware.base import BaseHTTPMiddleware
from backend.utils.logger import get_logger


logger = get_logger(__name__)


class RequestIDMiddleware(BaseHTTPMiddleware):
    """
    请求ID中间件
    为每个请求生成唯一的请求ID，便于追踪和调试
    """

    async def dispatch(self, request: Request, call_next: Callable) -> Response:
        """
        处理请求

        Args:
            request: HTTP请求
            call_next: 下一个中间件

        Returns:
            HTTP响应
        """
        # 生成请求ID
        request_id = str(uuid.uuid4())

        # 将请求ID添加到请求状态中
        request.state.request_id = request_id

        # 处理请求
        response = await call_next(request)

        # 将请求ID添加到响应头
        response.headers["X-Request-ID"] = request_id

        return response


class PerformanceMonitorMiddleware(BaseHTTPMiddleware):
    """
    性能监控中间件
    记录每个请求的处理时间
    """

    def __init__(self, app, slow_request_threshold: float = 1.0):
        """
        初始化性能监控中间件

        Args:
            app: FastAPI应用
            slow_request_threshold: 慢请求阈值（秒），超过此时间的请求会被记录为警告
        """
        super().__init__(app)
        self.slow_request_threshold = slow_request_threshold

    async def dispatch(self, request: Request, call_next: Callable) -> Response:
        """
        处理请求并监控性能

        Args:
            request: HTTP请求
            call_next: 下一个中间件

        Returns:
            HTTP响应
        """
        # 记录开始时间
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
    """
    速率限制中间件
    防止API被滥用（简单实现，生产环境建议使用Redis）
    """

    def __init__(self, app, max_requests: int = 100, window_seconds: int = 60):
        """
        初始化速率限制中间件

        Args:
            app: FastAPI应用
            max_requests: 时间窗口内的最大请求数
            window_seconds: 时间窗口大小（秒）
        """
        super().__init__(app)
        self.max_requests = max_requests
        self.window_seconds = window_seconds
        # 简单的内存存储（生产环境应使用Redis）
        self.request_counts = {}

    async def dispatch(self, request: Request, call_next: Callable) -> Response:
        """
        处理请求并检查速率限制

        Args:
            request: HTTP请求
            call_next: 下一个中间件

        Returns:
            HTTP响应
        """
        # 获取客户端IP
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
        """
        清理过期的速率限制记录

        Args:
            current_time: 当前时间戳
        """
        expired_ips = [
            ip for ip, (_, first_time) in self.request_counts.items()
            if current_time - first_time >= self.window_seconds
        ]

        for ip in expired_ips:
            del self.request_counts[ip]


class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    """
    安全头中间件
    添加安全相关的HTTP响应头
    """

    async def dispatch(self, request: Request, call_next: Callable) -> Response:
        """
        处理请求并添加安全头

        Args:
            request: HTTP请求
            call_next: 下一个中间件

        Returns:
            HTTP响应
        """
        response = await call_next(request)

        # 添加安全头
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["X-XSS-Protection"] = "1; mode=block"
        response.headers["Strict-Transport-Security"] = "max-age=31536000; includeSubDomains"

        return response


# 便捷函数：添加所有自定义中间件到应用
def add_custom_middlewares(app, config: dict = None):
    """
    添加所有自定义中间件到FastAPI应用

    Args:
        app: FastAPI应用实例
        config: 中间件配置字典
    """
    config = config or {}

    # 添加请求ID中间件
    app.add_middleware(RequestIDMiddleware)
    logger.info("已添加请求ID中间件")

    # 添加性能监控中间件
    slow_threshold = config.get("slow_request_threshold", 1.0)
    app.add_middleware(PerformanceMonitorMiddleware, slow_request_threshold=slow_threshold)
    logger.info(f"已添加性能监控中间件 (阈值: {slow_threshold}秒)")

    # 添加速率限制中间件（可选）
    if config.get("enable_rate_limit", False):
        max_requests = config.get("rate_limit_max_requests", 100)
        window_seconds = config.get("rate_limit_window_seconds", 60)
        app.add_middleware(RateLimitMiddleware, max_requests=max_requests, window_seconds=window_seconds)
        logger.info(f"已添加速率限制中间件 (每{window_seconds}秒{max_requests}次请求)")

    # 添加安全头中间件
    app.add_middleware(SecurityHeadersMiddleware)
    logger.info("已添加安全头中间件")
