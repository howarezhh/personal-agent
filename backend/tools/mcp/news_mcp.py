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
        self.hn_rss_endpoint = str(config.get("news_mcp", "hn_rss_endpoint", "https://hnrss.org") or "https://hnrss.org").rstrip("/")

    def _create_definition(self) -> ToolDefinition:
        return ToolDefinition(
            name="news_mcp",
            description="查询新闻头条，支持关键词、分类、国家和条数限制。",
            category="news",
            version="1.2.0",
            timeout=30,
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
        return self.hn_rss_endpoint

    def get_api_key(self) -> Optional[str]:
        return None

    @staticmethod
    def _build_search_query(query: Optional[str], category: Optional[str]) -> str:
        terms: list[str] = []
        normalized_query = (query or "").strip()
        normalized_category = (category or "").strip()
        if normalized_query:
            terms.append(normalized_query)
        if normalized_category and normalized_category != "general" and normalized_category not in terms:
            terms.append(normalized_category)
        return " ".join(terms).strip()

    @staticmethod
    def _extract_item_author(item: ET.Element) -> str:
        """兼容命名空间 RSS 作者字段，避免 `dc:creator` 被标准库直接忽略。"""

        author_text = item.findtext("author", default="")
        if author_text:
            return author_text

        for child in list(item):
            tag_name = child.tag.rsplit("}", 1)[-1] if isinstance(child.tag, str) else ""
            if tag_name == "creator" and child.text:
                return child.text
        return ""

    @staticmethod
    def _parse_rss_articles(rss_text: str, page_size: int, *, provider: str) -> Dict[str, Any]:
        try:
            root = ET.fromstring(rss_text)
        except ET.ParseError as error:
            raise ToolExecutionError(f"{provider} RSS 解析失败: {error}") from error

        articles = []
        for item in root.findall(".//item")[:page_size]:
            source_node = item.find("source")
            source_name = source_node.text if source_node is not None else provider
            articles.append(
                {
                    "title": item.findtext("title", default=""),
                    "description": item.findtext("description", default=""),
                    "url": item.findtext("link", default=""),
                    "source": source_name or provider,
                    "author": NewsMCP._extract_item_author(item),
                    "published_at": item.findtext("pubDate", default=""),
                    "image_url": "",
                }
            )

        return {
            "total_results": len(articles),
            "provider": provider,
            "articles": articles,
        }

    async def _fetch_google_news_rss(
        self,
        *,
        query: Optional[str],
        category: Optional[str],
        country: str,
        page_size: int,
    ) -> Dict[str, Any]:
        country_code = (country or "us").upper()
        search_query = self._build_search_query(query, category)
        if search_query:
            rss_url = f"https://news.google.com/rss/search?q={quote_plus(search_query)}&hl=en-US&gl={country_code}&ceid={country_code}:en"
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

        return self._parse_rss_articles(rss_text, page_size, provider="google_news_rss")

    async def _fetch_hn_rss(
        self,
        *,
        query: Optional[str],
        category: Optional[str],
        page_size: int,
    ) -> Dict[str, Any]:
        search_query = self._build_search_query(query, category)
        if search_query:
            rss_url = f"{self.hn_rss_endpoint}/newest?q={quote_plus(search_query)}"
        else:
            rss_url = f"{self.hn_rss_endpoint}/frontpage"

        try:
            session = await self._get_session()
            async with session.get(rss_url) as response:
                if response.status != 200:
                    raise ToolNetworkError(f"HN RSS 请求失败: {response.status}")
                rss_text = await response.text()
        except aiohttp.ClientError as error:
            if self._is_access_denied_error(error):
                raise ToolNetworkError(f"网络访问被拒绝: {error}") from error
            raise ToolNetworkError(f"新闻查询失败: {error}") from error

        return self._parse_rss_articles(rss_text, page_size, provider="hnrss")

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

            return {
                "success": True,
                "data": await self._fetch_hn_rss(query=query, category=category, page_size=page_size),
            }
        except ToolNetworkError:
            raise
        except Exception as error:
            raise ToolExecutionError(f"新闻查询失败: {error}") from error
