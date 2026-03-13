"""
IP地址查询MCP服务
使用ip-api.com提供IP地址信息查询功能
"""

from typing import Dict, Any, Optional
from backend.tools.mcp.base_mcp_tool import MCPTool
from backend.tools.base_tool import ToolDefinition, ToolParameter
import logging


class IPLookupMCP(MCPTool):
    """
    IP地址查询MCP服务

    功能：
    - 查询IP地址的地理位置
    - 查询IP所属的ISP信息
    - 支持IPv4和IPv6

    使用ip-api.com，完全免费，无需API密钥
    """

    def __init__(self):
        """初始化IP地址查询MCP"""
        super().__init__()
        self.logger = logging.getLogger(self.__class__.__name__)

    def _create_definition(self) -> ToolDefinition:
        """创建工具定义"""
        return ToolDefinition(
            name="ip_lookup_mcp",
            description="查询IP地址的地理位置和ISP信息",
            category="mcp",
            version="1.0.0",
            timeout=10,
            parameters=[
                ToolParameter(
                    name="ip_address",
                    type="string",
                    description="IP地址（IPv4或IPv6），不指定则查询当前IP",
                    required=False
                ),
                ToolParameter(
                    name="language",
                    type="string",
                    description="返回语言（zh-CN/en），默认为zh-CN",
                    required=False,
                    default="zh-CN",
                    enum=["zh-CN", "en"]
                )
            ]
        )

    def get_api_endpoint(self) -> str:
        """获取API端点"""
        return "http://ip-api.com/json"

    def get_api_key(self) -> Optional[str]:
        """获取API密钥（ip-api.com不需要密钥）"""
        return None

    async def execute(
        self,
        ip_address: Optional[str] = None,
        language: str = "zh-CN",
        **kwargs
    ) -> Dict[str, Any]:
        """
        执行IP地址查询

        Args:
            ip_address: IP地址（不指定则查询当前IP）
            language: 返回语言
            **kwargs: 其他参数

        Returns:
            IP地址信息
        """
        try:
            # 构建API URL
            if ip_address:
                api_url = f"{self.get_api_endpoint()}/{ip_address}"
            else:
                api_url = self.get_api_endpoint()

            # 构建请求参数
            params = {
                "lang": language,
                "fields": "status,message,country,countryCode,region,regionName,city,zip,lat,lon,timezone,isp,org,as,query"
            }

            # 发起请求
            self.logger.info(f"查询IP地址: {ip_address or '当前IP'}")
            response = await self._make_request("GET", api_url, params=params)

            if not response.get("success"):
                return response

            # 解析IP数据
            ip_data = response["data"]

            if ip_data.get("status") != "success":
                return {
                    "success": False,
                    "error": ip_data.get("message", "查询失败")
                }

            # 构建结果
            result = {
                "ip": ip_data.get("query", ""),
                "location": {
                    "country": ip_data.get("country", ""),
                    "country_code": ip_data.get("countryCode", ""),
                    "region": ip_data.get("regionName", ""),
                    "region_code": ip_data.get("region", ""),
                    "city": ip_data.get("city", ""),
                    "zip_code": ip_data.get("zip", ""),
                    "latitude": ip_data.get("lat", 0),
                    "longitude": ip_data.get("lon", 0),
                    "timezone": ip_data.get("timezone", "")
                },
                "isp": {
                    "name": ip_data.get("isp", ""),
                    "organization": ip_data.get("org", ""),
                    "as": ip_data.get("as", "")
                }
            }

            return {
                "success": True,
                "data": result
            }

        except Exception as e:
            self.logger.error(f"IP地址查询失败: {str(e)}", exc_info=True)
            return {
                "success": False,
                "error": f"IP地址查询失败: {str(e)}"
            }
