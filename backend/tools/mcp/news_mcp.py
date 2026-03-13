"""
新闻查询MCP服务
使用NewsAPI提供新闻查询功能
"""

from typing import Dict, Any, Optional
from backend.tools.mcp.base_mcp_tool import MCPTool
from backend.tools.base_tool import ToolDefinition, ToolParameter
from backend.tools.tool_config import get_tool_config
import logging


class NewsMCP(MCPTool):
    """
    新闻查询MCP服务

    功能：
    - 查询最新新闻
    - 按关键词搜索新闻
    - 按类别查询新闻

    使用NewsAPI（需要免费API密钥）
    注册地址: https://newsapi.org/
    """

    def __init__(self):
        """初始化新闻查询MCP"""
        super().__init__()
        self.logger = logging.getLogger(self.__class__.__name__)
        config = get_tool_config()
        self.api_key = config.get('news_mcp', 'api_key', '')

    def _create_definition(self) -> ToolDefinition:
        """创建工具定义"""
        return ToolDefinition(
            name="news_mcp",
            description="查询最新新闻，支持关键词搜索和分类查询",
            category="mcp",
            version="1.0.0",
            timeout=10,
            parameters=[
                ToolParameter(
                    name="query",
                    type="string",
                    description="搜索关键词（可选）",
                    required=False
                ),
                ToolParameter(
                    name="category",
                    type="string",
                    description="新闻类别（business/entertainment/general/health/science/sports/technology）",
                    required=False,
                    enum=["business", "entertainment", "general", "health", "science", "sports", "technology"]
                ),
                ToolParameter(
                    name="country",
                    type="string",
                    description="国家代码（如：cn/us/gb等），默认为cn",
                    required=False,
                    default="cn"
                ),
                ToolParameter(
                    name="page_size",
                    type="number",
                    description="返回新闻数量（1-100），默认为10",
                    required=False,
                    default=10
                )
            ]
        )

    def get_api_endpoint(self) -> str:
        """获取API端点"""
        return "https://newsapi.org/v2/top-headlines"

    def get_api_key(self) -> Optional[str]:
        """获取API密钥"""
        return self.api_key

    async def execute(
        self,
        query: Optional[str] = None,
        category: Optional[str] = None,
        country: str = "cn",
        page_size: int = 10,
        **kwargs
    ) -> Dict[str, Any]:
        """
        执行新闻查询

        Args:
            query: 搜索关键词
            category: 新闻类别
            country: 国家代码
            page_size: 返回数量
            **kwargs: 其他参数

        Returns:
            新闻列表
        """
        try:
            # 检查API密钥
            if not self.api_key:
                return {
                    "success": False,
                    "error": "未配置NewsAPI密钥，请设置环境变量NEWSAPI_KEY。免费注册地址: https://newsapi.org/"
                }

            # 限制返回数量
            page_size = max(1, min(100, page_size))

            # 构建请求参数
            params = {
                "apiKey": self.api_key,
                "country": country,
                "pageSize": page_size
            }

            if query:
                params["q"] = query

            if category:
                params["category"] = category

            # 发起请求
            self.logger.info(f"查询新闻: query={query}, category={category}, country={country}")
            response = await self._make_request("GET", self.get_api_endpoint(), params=params)

            if not response.get("success"):
                return response

            # 解析新闻数据
            news_data = response["data"]
            result = self._parse_news_data(news_data)

            return {
                "success": True,
                "data": result
            }

        except Exception as e:
            self.logger.error(f"新闻查询失败: {str(e)}", exc_info=True)
            return {
                "success": False,
                "error": f"新闻查询失败: {str(e)}"
            }

    def _parse_news_data(self, data: Dict[str, Any]) -> Dict[str, Any]:
        """
        解析新闻数据

        Args:
            data: API返回的原始数据

        Returns:
            格式化的新闻信息
        """
        result = {
            "total_results": data.get("totalResults", 0),
            "articles": []
        }

        articles = data.get("articles", [])
        for article in articles:
            result["articles"].append({
                "title": article.get("title", ""),
                "description": article.get("description", ""),
                "url": article.get("url", ""),
                "source": article.get("source", {}).get("name", ""),
                "author": article.get("author", ""),
                "published_at": article.get("publishedAt", ""),
                "image_url": article.get("urlToImage", "")
            })

        return result
