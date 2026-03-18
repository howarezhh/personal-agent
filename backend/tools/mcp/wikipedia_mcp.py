from __future__ import annotations

import logging
from typing import Any, Dict, Optional

from backend.tools.base_tool import ToolDefinition, ToolExecutionError, ToolNetworkError, ToolParameter
from backend.tools.mcp.base_mcp_tool import BuiltinMCPTool


class WikipediaMCP(BuiltinMCPTool):
    def __init__(self):
        super().__init__()
        self.logger = logging.getLogger(self.__class__.__name__)

    def _create_definition(self) -> ToolDefinition:
        return ToolDefinition(
            name="wikipedia_mcp",
            description="查询 Wikipedia 条目摘要，并返回相关词条。",
            category="knowledge",
            version="1.0.0",
            timeout=10,
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

    async def execute(self, query: str, language: str = "zh", limit: int = 3, **kwargs) -> Dict[str, Any]:
        try:
            limit = max(1, min(10, limit))
            api_url = self.get_configured_endpoint("https://en.wikipedia.org/w/api.php", key="api_endpoint_en") if language == "en" else self.get_api_endpoint()

            search_response = await self._make_request(
                "GET",
                api_url,
                params={"action": "opensearch", "search": query, "limit": limit, "format": "json"},
            )
            if not search_response.get("success"):
                return search_response

            search_data = search_response["data"]
            if not search_data or len(search_data) < 4:
                raise ToolExecutionError("Wikipedia 返回结果格式异常")

            titles = search_data[1]
            descriptions = search_data[2]
            urls = search_data[3]
            if not titles:
                raise ToolExecutionError("未找到相关词条")

            summary_response = await self._make_request(
                "GET",
                api_url,
                params={
                    "action": "query",
                    "prop": "extracts",
                    "exintro": True,
                    "explaintext": True,
                    "titles": titles[0],
                    "format": "json",
                },
            )

            summary = ""
            if summary_response.get("success"):
                pages = summary_response["data"].get("query", {}).get("pages", {})
                for page_data in pages.values():
                    summary = page_data.get("extract", "")
                    break

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

            return {"success": True, "data": result}
        except (ToolExecutionError, ToolNetworkError):
            raise
        except Exception as error:
            raise ToolExecutionError(f"Wikipedia 查询失败: {error}") from error
