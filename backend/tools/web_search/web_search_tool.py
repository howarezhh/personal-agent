
from typing import Dict, Any, List
from backend.tools.base_tool import (
    BaseTool,
    ToolDefinition,
    ToolParameter,
    ToolConfigurationError,
    ToolExecutionError,
    ToolNetworkError,
    ToolError,
)
from backend.tools.tool_config import get_tool_config
import aiohttp


class WebSearchTool(BaseTool):
    def __init__(self):
        super().__init__()
        # 使用统一配置管理
        config = get_tool_config()
        self.api_key = config.get('web_search', 'api_key', '')
        self.api_url = config.get('web_search', 'api_url', 'https://serpapi.com/search')
        self.timeout = config.get('web_search', 'timeout', 15)
        self.max_results = config.get('web_search', 'max_results', 10)
        self._definition.timeout = self.timeout
        for parameter in self._definition.parameters:
            if parameter.name == "num_results":
                parameter.maximum = self.max_results
                break

    def _create_definition(self) -> ToolDefinition:
        return ToolDefinition(
            name="web_search",
            description="搜索互联网获取实时信息，返回相关网页的标题、摘要和链接",
            category="search",
            strict_validation=True,
            parameters=[
                ToolParameter(
                    name="query",
                    type="string",
                    description="搜索关键词或问题，例如：'最新AI技术'、'Python教程'",
                    required=True,
                    min_length=1,
                    max_length=200,
                ),
                ToolParameter(
                    name="num_results",
                    type="integer",
                    description="返回结果数量，默认为5",
                    required=False,
                    default=5,
                    minimum=1,
                )
            ]
        )

    async def execute(self, query: str, num_results: int = 5, **kwargs) -> Dict[str, Any]:
        try:
            self.logger.info(f"开始网络搜索: 关键词={query}, 结果数量={num_results}")

            # 检查API密钥
            if not self.api_key:
                self.logger.warning("未配置搜索API密钥")
                raise ToolConfigurationError("未配置搜索API密钥，请检查 web_search 配置")

            # 限制结果数量
            num_results = min(max(1, int(num_results)), self.max_results)

            # 构建请求参数
            params = {
                "q": query,
                "api_key": self.api_key,
                "num": num_results,
                "engine": "google",  # 使用Google搜索引擎
                "hl": "zh-cn",       # 中文结果
                "gl": "cn"           # 中国地区
            }

            # 发送请求
            self.logger.debug(f"发送搜索API请求: {self.api_url}")
            async with aiohttp.ClientSession() as session:
                async with session.get(self.api_url, params=params, timeout=aiohttp.ClientTimeout(total=self.timeout)) as response:
                    if response.status == 200:
                        data = await response.json()
                        result_count = len(data.get('organic_results', []))
                        self.logger.info(f"搜索成功: 找到 {result_count} 条结果")
                        return self._format_search_results(data, query)
                    else:
                        self.logger.error(f"搜索API请求失败: status={response.status}")
                        return {
                            "success": False,
                            "data": None,
                            "error": f"搜索服务请求失败（HTTP {response.status}）",
                            "error_code": "TOOL_NETWORK_ERROR",
                            "error_type": "network_error",
                        }

        except aiohttp.ClientError as e:
            self.logger.error(f"网络请求失败: {str(e)}")
            raise ToolNetworkError(f"网络请求失败：{str(e)}") from e
        except ToolError:
            raise
        except Exception as e:
            self.logger.error(f"搜索失败: {str(e)}", exc_info=True)
            raise ToolExecutionError(f"搜索失败：{str(e)}") from e

    def _format_search_results(self, data: dict, query: str) -> Dict[str, Any]:
        results = []

        # 提取有机搜索结果
        organic_results = data.get("organic_results", [])

        for i, result in enumerate(organic_results, start=1):
            results.append({
                "index": i,
                "title": result.get("title", ""),
                "link": result.get("link", ""),
                "snippet": result.get("snippet", ""),
                "source": result.get("displayed_link", "")
            })

        # 构建描述文本
        if results:
            description = f"搜索关键词：{query}\n找到 {len(results)} 条结果：\n\n"
            for result in results:
                description += f"[{result['index']}] {result['title']}\n"
                description += f"来源：{result['source']}\n"
                description += f"摘要：{result['snippet']}\n"
                description += f"链接：{result['link']}\n\n"
        else:
            description = f"搜索关键词：{query}\n未找到相关结果"

        return {
            "success": True,
            "data": {
                "query": query,
                "results": results,
                "total_results": len(results),
                "description": description
            },
            "error": None
        }
