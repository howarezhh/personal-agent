"""
MCP工具基类
定义MCP（Model Context Protocol）工具的统一接口
"""

from abc import abstractmethod
from typing import Dict, Any, Optional, List
from backend.tools.base_tool import BaseTool, ToolDefinition, ToolParameter
from backend.tools.tool_config import get_tool_config
import logging
import aiohttp
import asyncio


class MCPTool(BaseTool):
    """
    MCP工具基类

    所有MCP工具必须继承此基类
    提供统一的HTTP请求、错误处理、重试机制等功能
    """

    def __init__(self):
        """初始化MCP工具"""
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
        """
        获取API端点

        Returns:
            API端点URL
        """
        pass

    @abstractmethod
    def get_api_key(self) -> Optional[str]:
        """
        获取API密钥

        Returns:
            API密钥，如果不需要则返回None
        """
        pass

    async def _get_session(self) -> aiohttp.ClientSession:
        """
        获取或创建HTTP会话

        Returns:
            aiohttp会话对象
        """
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
        """
        发起HTTP请求（带重试机制）

        Args:
            method: HTTP方法（GET, POST等）
            url: 请求URL
            headers: 请求头
            params: URL参数
            json_data: JSON请求体
            retry_count: 当前重试次数

        Returns:
            响应数据
        """
        try:
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
                        "status_code": response.status
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
                            "status_code": response.status
                        }
                else:
                    error_text = await response.text()
                    self.logger.error(f"MCP请求失败: {response.status}, {error_text}")
                    return {
                        "success": False,
                        "error": f"请求失败: {response.status}",
                        "status_code": response.status,
                        "details": error_text
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
            return {
                "success": False,
                "error": f"网络错误: {str(e)}"
            }
        except Exception as e:
            self.logger.error(f"MCP请求异常: {str(e)}", exc_info=True)
            return {
                "success": False,
                "error": f"请求异常: {str(e)}"
            }

    async def close(self):
        """关闭HTTP会话"""
        if self.session and not self.session.closed:
            await self.session.close()
            self.logger.info("MCP会话已关闭")

    def __del__(self):
        """析构函数，确保会话被关闭"""
        if self.session and not self.session.closed:
            try:
                # 记录警告，会话应该通过close()方法显式关闭
                self.logger.warning(f"MCP会话未正确关闭: {self.__class__.__name__}，请使用close()方法显式关闭")
            except Exception:
                # 忽略日志错误
                pass
