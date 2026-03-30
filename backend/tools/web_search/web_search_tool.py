from __future__ import annotations

import base64
import logging
import re
from typing import Any, Dict
from urllib.parse import quote_plus, urlparse, parse_qs

import aiohttp

from backend.tools.base_tool import BaseTool, ToolDefinition, ToolExecutionError, ToolNetworkError, ToolParameter
from backend.tools.tool_config import get_tool_config


class WebSearchTool(BaseTool):
    """基于 Jina Reader + Bing 的实时搜索工具。"""

    SEARCH_RESULT_PATTERN = re.compile(
        r"^\s*\d+\.\s+##\s+\[(?P<title>.*?)\]\((?P<link>.*?)\)\s*(?P<snippet>.*?)(?=^\s*\d+\.\s+##\s+\[|\Z)",
        re.MULTILINE | re.DOTALL,
    )

    def __init__(self) -> None:
        super().__init__()
        config = get_tool_config()
        self.logger = logging.getLogger(self.__class__.__name__)
        self.proxy_base_url = str(config.get("web_search", "proxy_base_url", "https://r.jina.ai/http://") or "https://r.jina.ai/http://")
        self.search_base_url = str(config.get("web_search", "search_base_url", "https://www.bing.com/search") or "https://www.bing.com/search")
        self.timeout = int(config.get("web_search", "timeout", 20) or 20)
        self.max_results = int(config.get("web_search", "max_results", 10) or 10)
        self.region = str(config.get("web_search", "region", "zh-CN") or "zh-CN")
        self._definition.timeout = self.timeout
        for parameter in self._definition.parameters:
            if parameter.name == "num_results":
                parameter.maximum = self.max_results
                break

    def _create_definition(self) -> ToolDefinition:
        return ToolDefinition(
            name="web_search",
            description="搜索互联网获取实时信息，返回标题、摘要与链接。",
            category="search",
            strict_validation=True,
            parameters=[
                ToolParameter(
                    name="query",
                    type="string",
                    description="搜索关键词或问题，例如：'最新 AI 技术'、'Python 教程'。",
                    required=True,
                    min_length=1,
                    max_length=200,
                ),
                ToolParameter(
                    name="num_results",
                    type="integer",
                    description="返回结果数量，默认 5。",
                    required=False,
                    default=5,
                    minimum=1,
                ),
            ],
        )

    def _build_search_proxy_url(self, query: str) -> str:
        encoded_query = quote_plus(query)
        target_url = f"{self.search_base_url}?q={encoded_query}&setlang={quote_plus(self.region)}"
        normalized_proxy_base_url = self.proxy_base_url if self.proxy_base_url.endswith("/") else f"{self.proxy_base_url}/"
        return f"{normalized_proxy_base_url}https://{target_url.removeprefix('https://')}"

    @staticmethod
    def _decode_bing_redirect(link: str) -> str:
        parsed_url = urlparse(link)
        if parsed_url.netloc != "www.bing.com":
            return link
        encoded_target = parse_qs(parsed_url.query).get("u", [""])[0]
        if not encoded_target.startswith("a1"):
            return link
        base64_payload = encoded_target[2:]
        padding = "=" * (-len(base64_payload) % 4)
        try:
            decoded = base64.b64decode(base64_payload + padding).decode("utf-8", errors="strict")
        except Exception:
            return link
        return decoded if decoded.startswith(("http://", "https://")) else link

    @classmethod
    def _extract_markdown_payload(cls, raw_text: str) -> str:
        marker = "Markdown Content:"
        payload = raw_text.split(marker, 1)[1] if marker in raw_text else raw_text
        return payload.strip()

    @classmethod
    def _parse_search_results(cls, markdown_payload: str, *, query: str, limit: int) -> Dict[str, Any]:
        results: list[dict[str, Any]] = []
        normalized_payload = cls._extract_markdown_payload(markdown_payload)

        for index, match in enumerate(cls.SEARCH_RESULT_PATTERN.finditer(normalized_payload), start=1):
            title = re.sub(r"\s+", " ", match.group("title")).strip()
            snippet = re.sub(r"\s+", " ", match.group("snippet")).strip()
            raw_link = match.group("link").strip()
            results.append(
                {
                    "index": index,
                    "title": title,
                    "link": cls._decode_bing_redirect(raw_link),
                    "snippet": snippet,
                }
            )
            if len(results) >= limit:
                break

        if not results:
            raise ToolExecutionError("搜索结果解析失败：未提取到任何标准结果")

        return {
            "query": query,
            "total_results": len(results),
            "search_engine": "bing_via_jina",
            "results": results,
        }

    async def execute(self, query: str, num_results: int = 5, **kwargs) -> Dict[str, Any]:
        normalized_result_count = min(max(1, int(num_results)), self.max_results)
        search_url = self._build_search_proxy_url(query)
        self.logger.info("开始网络搜索: query=%s num_results=%s", query, normalized_result_count)

        try:
            async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=self.timeout)) as session:
                async with session.get(search_url, headers={"User-Agent": "personal-agent/1.0"}) as response:
                    if response.status != 200:
                        raise ToolNetworkError(f"搜索代理请求失败: HTTP {response.status}")
                    raw_text = await response.text()
        except aiohttp.ClientError as error:
            self.logger.error("网络搜索请求失败: %s", error)
            raise ToolNetworkError(f"网络搜索请求失败: {error}") from error
        except Exception as error:
            self.logger.error("网络搜索执行失败: %s", error, exc_info=True)
            raise ToolExecutionError(f"网络搜索执行失败: {error}") from error

        parsed_result = self._parse_search_results(raw_text, query=query, limit=normalized_result_count)
        return {"success": True, "data": parsed_result}
