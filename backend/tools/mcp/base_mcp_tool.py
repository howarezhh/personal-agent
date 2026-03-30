"""Builtin MCP Tool 统一基类。"""

from __future__ import annotations

import asyncio
import json
import logging
from abc import abstractmethod
from typing import Any, Dict, Optional

import aiohttp

from backend.contracts.tools import ToolCapability, ToolOrigin, ToolTransportProtocol
from backend.contracts.tools.tool_errors import ToolErrorCode, ToolErrorType
from backend.tools.base_tool import BaseTool, ToolConfigurationError, ToolExecutionError, ToolNetworkError
from backend.tools.tool_config import get_tool_config


class BuiltinMCPTool(BaseTool):
    """运行在 builtin MCP server 内的外部 Tool 基类。"""

    declared_capabilities = (
        ToolCapability.INVOKE.value,
        ToolCapability.MCP_PROXY.value,
    )
    declared_transport_protocol = ToolTransportProtocol.MCP.value
    declared_tool_origin = ToolOrigin.EXTERNAL.value
    declared_mcp_server = "builtin"

    def __init__(self):
        super().__init__()
        self.logger = logging.getLogger(self.__class__.__name__)
        self.session: Optional[aiohttp.ClientSession] = None
        self.tool_config = get_tool_config()
        self.max_retries = self.tool_config.get("mcp", "max_retries", 3)
        self.retry_delay = self.tool_config.get("mcp", "retry_delay", 1.0)
        registry_timeout = self.tool_config.get_registry_entry(self.get_name()).get("timeout")
        configured_timeout = registry_timeout or self.tool_config.get("mcp", "timeout", self._definition.timeout)
        try:
            self.request_timeout = max(int(self._definition.timeout), int(configured_timeout))
        except (TypeError, ValueError):
            self.request_timeout = int(self._definition.timeout)
        self._definition.timeout = self.request_timeout

    @abstractmethod
    def get_api_endpoint(self) -> str:
        raise NotImplementedError

    @abstractmethod
    def get_api_key(self) -> Optional[str]:
        raise NotImplementedError

    def get_configured_endpoint(self, default: str, *, key: str = "api_endpoint") -> str:
        return self.tool_config.get(self.get_name(), key, default)

    async def initialize(self) -> None:
        await self._get_session()

    async def _get_session(self) -> aiohttp.ClientSession:
        if self.session is None or self.session.closed:
            timeout = aiohttp.ClientTimeout(total=self.request_timeout)
            self.session = aiohttp.ClientSession(
                timeout=timeout,
                headers={
                    "Accept": "application/json, text/plain;q=0.9, */*;q=0.8",
                    "Accept-Encoding": "gzip, deflate",
                    "User-Agent": "personal-agent/1.0",
                },
            )
        return self.session

    @staticmethod
    def _merge_headers(headers: Optional[Dict[str, str]]) -> Dict[str, str]:
        merged = {
            "Accept": "application/json, text/plain;q=0.9, */*;q=0.8",
            "Accept-Encoding": "gzip, deflate",
            "User-Agent": "personal-agent/1.0",
        }
        if headers:
            merged.update(headers)
        return merged

    @staticmethod
    async def _parse_json_response(response: aiohttp.ClientResponse) -> Any:
        try:
            return await response.json(content_type=None)
        except (aiohttp.ContentTypeError, json.JSONDecodeError):
            text = await response.text()
            try:
                return json.loads(text)
            except json.JSONDecodeError as error:
                raise ToolExecutionError(f"响应 JSON 解析失败: {error}") from error

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
            request_headers = self._merge_headers(headers)
            async with session.request(method=method, url=url, headers=request_headers, params=params, json=json_data) as response:
                if response.status == 200:
                    data = await self._parse_json_response(response)
                    self.logger.info("Builtin MCP tool request succeeded: %s", url)
                    return {"success": True, "data": data, "metadata": {"status_code": response.status}}

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
                    "error_code": ToolErrorCode.TOOL_NETWORK_ERROR.value,
                    "error_type": ToolErrorType.NETWORK_ERROR.value,
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
        """关闭动作保持幂等。"""

        if self.session and not self.session.closed:
            await self.session.close()
            self.logger.info("Builtin MCP tool session closed")


__all__ = ["BuiltinMCPTool"]
