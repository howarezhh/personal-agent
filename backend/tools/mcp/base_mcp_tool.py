"""Builtin MCP tool helpers.

这里的工具类运行在 builtin MCP server 内部。
它们对外暴露的宿主协议统一是标准 MCP；
若需要访问第三方 API，HTTP 只是 server 进程内部的实现细节，
不再代表 host 与 tool 之间的调用协议。
"""

from __future__ import annotations

import asyncio
import logging
from abc import abstractmethod
from typing import Any, Dict, Optional

import aiohttp

from backend.tools.base_tool import (
    BaseTool,
    ToolConfigurationError,
    ToolExecutionError,
    ToolNetworkError,
)
from backend.tools.tool_config import get_tool_config


class BuiltinMCPTool(BaseTool):
    """builtin MCP server 内可复用的外部调用基类。"""

    def __init__(self):
        super().__init__()
        self.logger = logging.getLogger(self.__class__.__name__)
        self.session: Optional[aiohttp.ClientSession] = None
        self.tool_config = get_tool_config()
        self.max_retries = self.tool_config.get("mcp", "max_retries", 3)
        self.retry_delay = self.tool_config.get("mcp", "retry_delay", 1.0)
        self.request_timeout = self.tool_config.get("mcp", "timeout", self._definition.timeout)
        self._definition.timeout = self.request_timeout

    @abstractmethod
    def get_api_endpoint(self) -> str:
        """返回工具内部访问的默认 API endpoint。"""

    @abstractmethod
    def get_api_key(self) -> Optional[str]:
        """返回工具内部访问所需的 API Key。"""

    def get_configured_endpoint(self, default: str, *, key: str = "api_endpoint") -> str:
        return self.tool_config.get(self.get_name(), key, default)

    async def _get_session(self) -> aiohttp.ClientSession:
        if self.session is None or self.session.closed:
            timeout = aiohttp.ClientTimeout(total=self.request_timeout)
            self.session = aiohttp.ClientSession(timeout=timeout)
        return self.session

    @staticmethod
    def _is_access_denied_error(error: BaseException) -> bool:
        current: Optional[BaseException] = error
        while current is not None:
            if isinstance(current, PermissionError):
                return True
            message = str(current)
            lowered = message.lower()
            if "拒绝访问" in message or "access is denied" in lowered or "winerror 5" in lowered:
                return True
            current = current.__cause__ or current.__context__
        return False

    async def _make_request(
        self,
        method: str,
        url: str,
        headers: Optional[Dict[str, str]] = None,
        params: Optional[Dict[str, Any]] = None,
        json_data: Optional[Dict[str, Any]] = None,
        retry_count: int = 0,
    ) -> Dict[str, Any]:
        try:
            api_key = self.get_api_key()
            if api_key is not None and not api_key:
                raise ToolConfigurationError(f"{self.get_name()} 缺少 API Key 配置")

            session = await self._get_session()
            async with session.request(
                method=method,
                url=url,
                headers=headers,
                params=params,
                json=json_data,
            ) as response:
                if response.status == 200:
                    data = await response.json()
                    self.logger.info("Builtin MCP tool request succeeded: %s", url)
                    return {
                        "success": True,
                        "data": data,
                        "metadata": {"status_code": response.status},
                    }

                if response.status == 429 and retry_count < self.max_retries:
                    wait_time = self.retry_delay * (2 ** retry_count)
                    self.logger.warning("Builtin MCP tool rate limited, retry after %.2fs", wait_time)
                    await asyncio.sleep(wait_time)
                    return await self._make_request(
                        method,
                        url,
                        headers=headers,
                        params=params,
                        json_data=json_data,
                        retry_count=retry_count + 1,
                    )

                self.logger.error("Builtin MCP tool request failed: status=%s url=%s", response.status, url)
                return {
                    "success": False,
                    "error": f"网络请求失败: {response.status}",
                    "error_code": "TOOL_NETWORK_ERROR",
                    "error_type": "network_error",
                    "metadata": {"status_code": response.status},
                }

        except aiohttp.ClientError as error:
            self.logger.error("Builtin MCP tool network error: %s", error)
            if self._is_access_denied_error(error):
                raise ToolNetworkError(f"网络访问被拒绝: {error}") from error
            if retry_count < self.max_retries:
                wait_time = self.retry_delay * (2 ** retry_count)
                self.logger.warning("Builtin MCP tool network retry after %.2fs", wait_time)
                await asyncio.sleep(wait_time)
                return await self._make_request(
                    method,
                    url,
                    headers=headers,
                    params=params,
                    json_data=json_data,
                    retry_count=retry_count + 1,
                )
            raise ToolNetworkError(f"网络请求失败: {error}") from error
        except ToolConfigurationError:
            raise
        except Exception as error:
            self.logger.error("Builtin MCP tool request unexpected error: %s", error, exc_info=True)
            raise ToolExecutionError(f"请求执行失败: {error}") from error

    async def close(self):
        if self.session and not self.session.closed:
            await self.session.close()
            self.logger.info("Builtin MCP tool session closed")
