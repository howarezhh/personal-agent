
from typing import Dict, Any, Optional
from backend.tools.mcp.base_mcp_tool import MCPTool
from backend.tools.base_tool import ToolDefinition, ToolParameter
import logging


class WikipediaMCP(MCPTool):
    def __init__(self):
        super().__init__()
        self.logger = logging.getLogger(self.__class__.__name__)

    def _create_definition(self) -> ToolDefinition:
        return ToolDefinition(
            name="wikipedia_mcp",
            description="搜索维基百科，获取百科知识",
            category="mcp",
            version="1.0.0",
            timeout=10,
            strict_validation=True,
            parameters=[
                ToolParameter(
                    name="query",
                    type="string",
                    description="搜索关键词",
                    required=True
                ),
                ToolParameter(
                    name="language",
                    type="string",
                    description="语言（zh/en），默认为zh",
                    required=False,
                    default="zh",
                    enum=["zh", "en"]
                ),
                ToolParameter(
                    name="limit",
                    type="integer",
                    description="返回结果数量（1-10），默认为3",
                    required=False,
                    default=3,
                    minimum=1,
                    maximum=10,
                )
            ]
        )

    def get_api_endpoint(self) -> str:
        return "https://zh.wikipedia.org/w/api.php"

    def get_api_key(self) -> Optional[str]:
        return None

    async def execute(
        self,
        query: str,
        language: str = "zh",
        limit: int = 3,
        **kwargs
    ) -> Dict[str, Any]:
        try:
            # 限制返回数量
            limit = max(1, min(10, limit))

            # 根据语言选择API端点
            if language == "en":
                api_url = "https://en.wikipedia.org/w/api.php"
            else:
                api_url = "https://zh.wikipedia.org/w/api.php"

            # 第一步：搜索相关条目
            search_params = {
                "action": "opensearch",
                "search": query,
                "limit": limit,
                "format": "json"
            }

            self.logger.info(f"搜索维基百科: {query}, 语言: {language}")
            search_response = await self._make_request("GET", api_url, params=search_params)

            if not search_response.get("success"):
                return search_response

            search_data = search_response["data"]

            # 解析搜索结果
            if not search_data or len(search_data) < 4:
                return {
                    "success": False,
                    "error": "未找到相关结果"
                }

            titles = search_data[1]
            descriptions = search_data[2]
            urls = search_data[3]

            if not titles:
                return {
                    "success": False,
                    "error": "未找到相关结果"
                }

            # 第二步：获取第一个条目的详细摘要
            summary_params = {
                "action": "query",
                "prop": "extracts",
                "exintro": True,
                "explaintext": True,
                "titles": titles[0],
                "format": "json"
            }

            summary_response = await self._make_request("GET", api_url, params=summary_params)

            summary = ""
            if summary_response.get("success"):
                pages = summary_response["data"].get("query", {}).get("pages", {})
                for page_id, page_data in pages.items():
                    summary = page_data.get("extract", "")
                    break

            # 构建结果
            result = {
                "query": query,
                "language": language,
                "main_result": {
                    "title": titles[0],
                    "description": descriptions[0] if descriptions else "",
                    "url": urls[0] if urls else "",
                    "summary": summary[:500] + "..." if len(summary) > 500 else summary
                },
                "related_results": []
            }

            # 添加其他相关结果
            for i in range(1, len(titles)):
                result["related_results"].append({
                    "title": titles[i],
                    "description": descriptions[i] if i < len(descriptions) else "",
                    "url": urls[i] if i < len(urls) else ""
                })

            return {
                "success": True,
                "data": result
            }

        except Exception as e:
            self.logger.error(f"维基百科搜索失败: {str(e)}", exc_info=True)
            return {
                "success": False,
                "error": f"维基百科搜索失败: {str(e)}"
            }
