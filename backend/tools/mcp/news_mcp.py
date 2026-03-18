from __future__ import annotations

import logging
import xml.etree.ElementTree as ET
from typing import Any, Dict, Optional
from urllib.parse import quote_plus

import aiohttp

from backend.tools.base_tool import ToolConfigurationError, ToolDefinition, ToolExecutionError, ToolNetworkError, ToolParameter
from backend.tools.mcp.base_mcp_tool import BuiltinMCPTool
from backend.tools.tool_config import get_tool_config


class NewsMCP(BuiltinMCPTool):
    def __init__(self):
        super().__init__()
        self.logger = logging.getLogger(self.__class__.__name__)
        config = get_tool_config()
        self.api_key = config.get("news_mcp", "api_key", "")

    def _create_definition(self) -> ToolDefinition:
        return ToolDefinition(
            name="news_mcp",
            description="查询新闻头条，支持关键词、分类、国家和条数限制。",
            category="news",
            version="1.0.0",
            timeout=10,
            strict_validation=True,
            parameters=[
                ToolParameter(name="query", type="string", description="关键词，可选。", required=False),
                ToolParameter(
                    name="category",
                    type="string",
                    description="新闻分类，可选：business、entertainment、general、health、science、sports、technology。",
                    required=False,
                    enum=["business", "entertainment", "general", "health", "science", "sports", "technology"],
                ),
                ToolParameter(name="country", type="string", description="国家代码，例如 cn、us、gb，默认 cn。", required=False, default="cn"),
                ToolParameter(
                    name="page_size",
                    type="integer",
                    description="返回条数，范围 1-100，默认 10。",
                    required=False,
                    default=10,
                    minimum=1,
                    maximum=100,
                ),
            ],
        )

    def get_api_endpoint(self) -> str:
        return self.get_configured_endpoint("https://newsapi.org/v2/top-headlines")

    def get_api_key(self) -> Optional[str]:
        return self.api_key

    async def _fetch_google_news_rss(
        self,
        *,
        query: Optional[str],
        category: Optional[str],
        country: str,
        page_size: int,
    ) -> Dict[str, Any]:
        country_code = (country or "us").upper()
        search_query = (query or "").strip()
        if not search_query and category and category != "general":
            search_query = category
        if search_query:
            rss_url = (
                f"https://news.google.com/rss/search?q={quote_plus(search_query)}"
                f"&hl=en-US&gl={country_code}&ceid={country_code}:en"
            )
        else:
            rss_url = f"https://news.google.com/rss?hl=en-US&gl={country_code}&ceid={country_code}:en"

        try:
            session = await self._get_session()
            async with session.get(rss_url) as response:
                if response.status != 200:
                    raise ToolNetworkError(f"Google News RSS 请求失败: {response.status}")
                rss_text = await response.text()
        except aiohttp.ClientError as error:
            if self._is_access_denied_error(error):
                raise ToolNetworkError(f"网络访问被拒绝: {error}") from error
            raise ToolNetworkError(f"新闻查询失败: {error}") from error

        try:
            root = ET.fromstring(rss_text)
        except ET.ParseError as error:
            raise ToolExecutionError(f"Google News RSS 解析失败: {error}") from error

        articles = []
        for item in root.findall(".//item")[:page_size]:
            articles.append(
                {
                    "title": item.findtext("title", default=""),
                    "description": item.findtext("description", default=""),
                    "url": item.findtext("link", default=""),
                    "source": item.findtext("source", default=""),
                    "author": "",
                    "published_at": item.findtext("pubDate", default=""),
                    "image_url": "",
                }
            )

        return {
            "total_results": len(articles),
            "provider": "google_news_rss",
            "articles": articles,
        }

    async def execute(
        self,
        query: Optional[str] = None,
        category: Optional[str] = None,
        country: str = "cn",
        page_size: int = 10,
        **kwargs,
    ) -> Dict[str, Any]:
        try:
            page_size = max(1, min(100, page_size))
            if not self.api_key:
                return {
                    "success": True,
                    "data": await self._fetch_google_news_rss(
                        query=query,
                        category=category,
                        country=country,
                        page_size=page_size,
                    ),
                }

            params = {"apiKey": self.api_key, "country": country, "pageSize": page_size}
            if query:
                params["q"] = query
            if category:
                params["category"] = category
            response = await self._make_request("GET", self.get_api_endpoint(), params=params)
            if not response.get("success"):
                return response
            return {"success": True, "data": self._parse_news_data(response["data"])}
        except (ToolConfigurationError, ToolNetworkError):
            raise
        except Exception as error:
            raise ToolExecutionError(f"新闻查询失败: {error}") from error

    def _parse_news_data(self, data: Dict[str, Any]) -> Dict[str, Any]:
        result = {"total_results": data.get("totalResults", 0), "provider": "newsapi", "articles": []}
        for article in data.get("articles", []):
            result["articles"].append(
                {
                    "title": article.get("title", ""),
                    "description": article.get("description", ""),
                    "url": article.get("url", ""),
                    "source": article.get("source", {}).get("name", ""),
                    "author": article.get("author", ""),
                    "published_at": article.get("publishedAt", ""),
                    "image_url": article.get("urlToImage", ""),
                }
            )
        return result
