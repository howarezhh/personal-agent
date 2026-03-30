from __future__ import annotations

import json
import logging
from typing import Any, Dict, Optional
from urllib.parse import quote, quote_plus

import aiohttp

from backend.tools.base_tool import ToolDefinition, ToolExecutionError, ToolNetworkError, ToolParameter
from backend.tools.mcp.base_mcp_tool import BuiltinMCPTool
from backend.tools.tool_config import get_tool_config


class WikipediaMCP(BuiltinMCPTool):
    def __init__(self):
        super().__init__()
        self.logger = logging.getLogger(self.__class__.__name__)
        config = get_tool_config()
        self.proxy_base_url = str(config.get("wikipedia_mcp", "proxy_base_url", "https://r.jina.ai/http://") or "https://r.jina.ai/http://")

    def _create_definition(self) -> ToolDefinition:
        return ToolDefinition(
            name="wikipedia_mcp",
            description="查询 Wikipedia 条目摘要，并返回相关词条。",
            category="knowledge",
            version="1.1.0",
            timeout=15,
            strict_validation=True,
            parameters=[
                ToolParameter(name="query", type="string", description="搜索关键词。", required=True),
                ToolParameter(name="language", type="string", description="语言，可选 zh 或 en，默认 zh。", required=False, default="zh", enum=["zh", "en"]),
                ToolParameter(name="limit", type="integer", description="返回结果条数，范围 1-10，默认 3。", required=False, default=3, minimum=1, maximum=10),
            ],
        )

    def get_api_endpoint(self) -> str:
        return self.get_configured_endpoint("https://zh.wikipedia.org/w/api.php", key="api_endpoint_zh")

    def get_api_key(self) -> Optional[str]:
        return None

    @staticmethod
    def _extract_jina_payload(text: str) -> str:
        marker = "Markdown Content:"
        payload = text.split(marker, 1)[1].strip() if marker in text else text.strip()
        if not payload:
            raise ToolExecutionError("Wikipedia 代理未返回正文")
        return payload

    @staticmethod
    def _extract_json_document(payload: str) -> Any:
        """尽量从代理正文中提取首个合法 JSON 文档，兼容 markdown 包装与额外说明文本。"""

        decoder = json.JSONDecoder()
        candidate_payloads = [payload.strip()]

        if payload.startswith("```"):
            fenced_lines = [line for line in payload.splitlines() if not line.startswith("```")]
            candidate_payloads.append("\n".join(fenced_lines).strip())

        for candidate in candidate_payloads:
            if not candidate:
                continue
            try:
                parsed, _index = decoder.raw_decode(candidate)
                return parsed
            except json.JSONDecodeError:
                pass

        for marker in ("{", "["):
            start_index = payload.find(marker)
            if start_index < 0:
                continue
            try:
                parsed, _index = decoder.raw_decode(payload[start_index:])
                return parsed
            except json.JSONDecodeError:
                continue

        raise ToolExecutionError("Wikipedia 代理 JSON 解析失败: 未找到合法 JSON 文档")

    def _build_proxy_url(self, target_url: str) -> str:
        normalized_target_url = target_url.strip()
        normalized_proxy_base_url = self.proxy_base_url if self.proxy_base_url.endswith("/") else f"{self.proxy_base_url}/"
        if normalized_target_url.startswith("https://"):
            return f"{normalized_proxy_base_url}{normalized_target_url}"
        if normalized_target_url.startswith("http://"):
            return f"{normalized_proxy_base_url}{normalized_target_url}"
        raise ToolExecutionError("Wikipedia 代理目标地址非法")

    async def _fetch_proxy_json(self, target_url: str) -> Any:
        proxy_url = self._build_proxy_url(target_url)
        try:
            session = await self._get_session()
            async with session.get(proxy_url, headers={"User-Agent": "personal-agent/1.0"}) as response:
                if response.status != 200:
                    raise ToolNetworkError(f"Wikipedia 代理请求失败: {response.status}")
                text = await response.text()
        except aiohttp.ClientError as error:
            if self._is_access_denied_error(error):
                raise ToolNetworkError(f"网络访问被拒绝: {error}") from error
            raise ToolNetworkError(f"Wikipedia 代理请求失败: {error}") from error

        return self._extract_json_document(self._extract_jina_payload(text))

    async def _fetch_proxy_markdown(self, target_url: str) -> str:
        proxy_url = self._build_proxy_url(target_url)
        try:
            session = await self._get_session()
            async with session.get(proxy_url, headers={"User-Agent": "personal-agent/1.0"}) as response:
                if response.status != 200:
                    raise ToolNetworkError(f"Wikipedia 代理请求失败: {response.status}")
                text = await response.text()
        except aiohttp.ClientError as error:
            if self._is_access_denied_error(error):
                raise ToolNetworkError(f"网络访问被拒绝: {error}") from error
            raise ToolNetworkError(f"Wikipedia 代理请求失败: {error}") from error

        return self._extract_jina_payload(text)

    @staticmethod
    def _build_wikipedia_result(query: str, language: str, titles: list[str], descriptions: list[str], urls: list[str], summary: str) -> Dict[str, Any]:
        result = {
            "query": query,
            "language": language,
            "main_result": {
                "title": titles[0],
                "description": descriptions[0] if descriptions else "",
                "url": urls[0] if urls else "",
                "summary": f"{summary[:500]}..." if len(summary) > 500 else summary,
            },
            "related_results": [],
        }
        for index in range(1, len(titles)):
            result["related_results"].append(
                {
                    "title": titles[index],
                    "description": descriptions[index] if index < len(descriptions) else "",
                    "url": urls[index] if index < len(urls) else "",
                }
            )
        return result

    async def _execute_via_proxy(self, query: str, language: str, limit: int) -> Dict[str, Any]:
        language_host = "en.wikipedia.org" if language == "en" else "zh.wikipedia.org"
        search_url = f"https://{language_host}/w/api.php?action=opensearch&search={quote_plus(query)}&limit={limit}&format=json"
        search_data = await self._fetch_proxy_json(search_url)

        if not search_data or len(search_data) < 4:
            raise ToolExecutionError("Wikipedia 代理搜索结果格式异常")

        titles = search_data[1]
        descriptions = search_data[2]
        urls = search_data[3]
        if not titles:
            raise ToolExecutionError("未找到相关词条")

        summary_url = str(urls[0]) if urls else ""
        summary_markdown = await self._fetch_proxy_markdown(summary_url)
        summary = summary_markdown[:2000].strip()

        return self._build_wikipedia_result(query, language, titles, descriptions, urls, summary)

    async def execute(self, query: str, language: str = "zh", limit: int = 3, **kwargs) -> Dict[str, Any]:
        try:
            limit = max(1, min(10, limit))

            return {"success": True, "data": await self._execute_via_proxy(query, language, limit)}
        except (ToolExecutionError, ToolNetworkError):
            raise
        except Exception as error:
            raise ToolExecutionError(f"Wikipedia 查询失败: {error}") from error
