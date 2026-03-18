from __future__ import annotations

import logging
from typing import Any, Dict, Optional

from backend.tools.base_tool import ToolDefinition, ToolExecutionError, ToolNetworkError, ToolParameter
from backend.tools.mcp.base_mcp_tool import BuiltinMCPTool


class IPLookupMCP(BuiltinMCPTool):
    def __init__(self):
        super().__init__()
        self.logger = logging.getLogger(self.__class__.__name__)

    def _create_definition(self) -> ToolDefinition:
        return ToolDefinition(
            name="ip_lookup_mcp",
            description="查询 IP 地址的地理位置、网络运营商和 ASN 信息。",
            category="network",
            version="1.0.0",
            timeout=10,
            strict_validation=True,
            parameters=[
                ToolParameter(name="ip_address", type="string", description="IP 地址，支持 IPv4/IPv6；为空时查询当前出口 IP。", required=False),
                ToolParameter(
                    name="language",
                    type="string",
                    description="返回语言，默认 zh-CN。",
                    required=False,
                    default="zh-CN",
                    enum=["zh-CN", "en"],
                ),
            ],
        )

    def get_api_endpoint(self) -> str:
        return self.get_configured_endpoint("https://ipapi.co")

    def get_api_key(self) -> Optional[str]:
        return None

    async def execute(self, ip_address: Optional[str] = None, language: str = "zh-CN", **kwargs) -> Dict[str, Any]:
        try:
            base_url = self.get_api_endpoint().rstrip("/")
            api_url = f"{base_url}/{ip_address}/json/" if ip_address else f"{base_url}/json/"
            response = await self._make_request("GET", api_url)
            if not response.get("success"):
                return response

            ip_data = response["data"]
            if ip_data.get("error"):
                raise ToolExecutionError(ip_data.get("reason") or "IP 查询失败")

            result = {
                "ip": ip_data.get("ip", ""),
                "location": {
                    "country": ip_data.get("country_name", ""),
                    "country_code": ip_data.get("country_code", ""),
                    "region": ip_data.get("region", ""),
                    "region_code": ip_data.get("region_code", ""),
                    "city": ip_data.get("city", ""),
                    "zip_code": ip_data.get("postal", ""),
                    "latitude": ip_data.get("latitude", 0),
                    "longitude": ip_data.get("longitude", 0),
                    "timezone": ip_data.get("timezone", ""),
                },
                "isp": {
                    "name": ip_data.get("org", ""),
                    "organization": ip_data.get("org", ""),
                    "as": ip_data.get("asn", ""),
                },
            }
            return {"success": True, "data": result}
        except (ToolExecutionError, ToolNetworkError):
            raise
        except Exception as error:
            raise ToolExecutionError(f"IP 查询失败: {error}") from error
