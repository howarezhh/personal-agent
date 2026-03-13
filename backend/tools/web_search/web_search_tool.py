"""
网络搜索工具
搜索互联网获取实时信息
"""

from typing import Dict, Any, List
from backend.tools.base_tool import BaseTool, ToolDefinition, ToolParameter
from backend.tools.tool_config import get_tool_config
import aiohttp


class WebSearchTool(BaseTool):
    """
    网络搜索工具

    功能：
    - 搜索互联网获取实时信息
    - 返回搜索结果（标题、摘要、URL）

    注意：需要配置搜索API密钥（环境变量SEARCH_API_KEY）
    支持的搜索引擎：SerpAPI、Google Custom Search API等
    """

    def __init__(self):
        """初始化搜索工具"""
        super().__init__()
        # 使用统一配置管理
        config = get_tool_config()
        self.api_key = config.get('web_search', 'api_key', '')
        self.api_url = config.get('web_search', 'api_url', 'https://serpapi.com/search')
        self.timeout = config.get('web_search', 'timeout', 15)
        self.max_results = config.get('web_search', 'max_results', 10)
        self._definition.timeout = self.timeout

    def _create_definition(self) -> ToolDefinition:
        """创建工具定义"""
        return ToolDefinition(
            name="web_search",
            description="搜索互联网获取实时信息，返回相关网页的标题、摘要和链接",
            category="search",
            parameters=[
                ToolParameter(
                    name="query",
                    type="string",
                    description="搜索关键词或问题，例如：'最新AI技术'、'Python教程'",
                    required=True
                ),
                ToolParameter(
                    name="num_results",
                    type="number",
                    description="返回结果数量，默认为5",
                    required=False,
                    default=5
                )
            ]
        )

    async def execute(self, query: str, num_results: int = 5, **kwargs) -> Dict[str, Any]:
        """
        执行搜索

        Args:
            query: 搜索关键词
            num_results: 返回结果数量

        Returns:
            搜索结果
        """
        try:
            self.logger.info(f"开始网络搜索: 关键词={query}, 结果数量={num_results}")

            # 检查API密钥
            if not self.api_key:
                self.logger.warning("未配置搜索API密钥")
                return {
                    "success": False,
                    "data": None,
                    "error": "未配置搜索API密钥，请设置环境变量SEARCH_API_KEY"
                }

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
                        error_data = await response.json()
                        error_msg = error_data.get('error', '未知错误')
                        self.logger.error(f"搜索API请求失败: {error_msg}")
                        return {
                            "success": False,
                            "data": None,
                            "error": f"搜索API请求失败：{error_msg}"
                        }

        except aiohttp.ClientError as e:
            self.logger.error(f"网络请求失败: {str(e)}")
            return {
                "success": False,
                "data": None,
                "error": f"网络请求失败：{str(e)}"
            }
        except Exception as e:
            self.logger.error(f"搜索失败: {str(e)}", exc_info=True)
            return {
                "success": False,
                "data": None,
                "error": f"搜索失败：{str(e)}"
            }

    def _format_search_results(self, data: dict, query: str) -> Dict[str, Any]:
        """
        格式化搜索结果

        Args:
            data: API返回的原始数据
            query: 搜索关键词

        Returns:
            格式化后的搜索结果
        """
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
