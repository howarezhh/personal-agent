
from abc import abstractmethod
from typing import Dict, Any, Optional, List
from backend.tools.base_tool import (
    BaseTool,
    ToolDefinition,
    ToolParameter,
    ToolConfigurationError,
    ToolExecutionError,
    ToolNetworkError,
)
from backend.tools.tool_config import get_tool_config
import logging
import aiohttp
import asyncio


class MCPTool(BaseTool):
    def __init__(self):
        super().__init__()
        self.logger = logging.getLogger(self.__class__.__name__)
        self.session: Optional[aiohttp.ClientSession] = None
        config = get_tool_config()
        self.max_retries = config.get('mcp', 'max_retries', 3)
        self.retry_delay = config.get('mcp', 'retry_delay', 1.0)
        self.request_timeout = config.get('mcp', 'timeout', self._definition.timeout)
        self._definition.timeout = self.request_timeout

    @abstractmethod
    def get_api_endpoint(self) -> str:
        pass

    @abstractmethod
    def get_api_key(self) -> Optional[str]:
        pass

    async def _get_session(self) -> aiohttp.ClientSession:
        if self.session is None or self.session.closed:
            timeout = aiohttp.ClientTimeout(total=self.request_timeout)
            self.session = aiohttp.ClientSession(timeout=timeout)
        return self.session

    async def _make_request(
        self,
        method: str,
        url: str,
        headers: Optional[Dict[str, str]] = None,
        params: Optional[Dict[str, Any]] = None,
        json_data: Optional[Dict[str, Any]] = None,
        retry_count: int = 0
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
                json=json_data
            ) as response:
                # 检查响应状态
                if response.status == 200:
                    data = await response.json()
                    self.logger.info(f"MCP请求成功: {url}")
                    return {
                        "success": True,
                        "data": data,
                        "metadata": {"status_code": response.status},
                    }
                elif response.status == 429:  # 速率限制
                    if retry_count < self.max_retries:
                        wait_time = self.retry_delay * (2 ** retry_count)
                        self.logger.warning(f"MCP请求速率限制，{wait_time}秒后重试")
                        await asyncio.sleep(wait_time)
                        return await self._make_request(
                            method, url, headers, params, json_data, retry_count + 1
                        )
                    else:
                        return {
                            "success": False,
                            "error": "请求速率限制，请稍后再试",
                            "error_code": "TOOL_NETWORK_ERROR",
                            "error_type": "network_error",
                            "metadata": {"status_code": response.status},
                        }
                else:
                    self.logger.error(f"MCP请求失败: {response.status}")
                    return {
                        "success": False,
                        "error": f"请求失败: {response.status}",
                        "error_code": "TOOL_NETWORK_ERROR",
                        "error_type": "network_error",
                        "metadata": {"status_code": response.status},
                    }

        except aiohttp.ClientError as e:
            self.logger.error(f"MCP网络错误: {str(e)}")
            if retry_count < self.max_retries:
                wait_time = self.retry_delay * (2 ** retry_count)
                self.logger.warning(f"网络错误，{wait_time}秒后重试")
                await asyncio.sleep(wait_time)
                return await self._make_request(
                    method, url, headers, params, json_data, retry_count + 1
                )
            raise ToolNetworkError(f"网络错误: {str(e)}") from e
        except ToolConfigurationError:
            raise
        except Exception as e:
            self.logger.error(f"MCP请求异常: {str(e)}", exc_info=True)
            raise ToolExecutionError(f"请求异常: {str(e)}") from e

    async def close(self):
        if self.session and not self.session.closed:
            await self.session.close()
            self.logger.info("MCP会话已关闭")

    def __del__(self):
        if self.session and not self.session.closed:
            try:
                # 记录警告，会话应该通过close()方法显式关闭
                self.logger.warning(f"MCP会话未正确关闭: {self.__class__.__name__}，请使用close()方法显式关闭")
            except Exception:
                # 忽略日志错误
                pass
