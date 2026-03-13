"""
汇率查询MCP服务
使用ExchangeRate-API提供实时汇率查询功能
"""

from typing import Dict, Any, Optional
from backend.tools.mcp.base_mcp_tool import MCPTool
from backend.tools.base_tool import ToolDefinition, ToolParameter
import logging


class ExchangeRateMCP(MCPTool):
    """
    汇率查询MCP服务

    功能：
    - 查询实时汇率
    - 货币转换计算
    - 支持150+种货币

    使用ExchangeRate-API，完全免费，无需API密钥
    """

    def __init__(self):
        """初始化汇率查询MCP"""
        super().__init__()
        self.logger = logging.getLogger(self.__class__.__name__)
        # 常用货币代码
        self.common_currencies = {
            "CNY": "人民币",
            "USD": "美元",
            "EUR": "欧元",
            "GBP": "英镑",
            "JPY": "日元",
            "HKD": "港币",
            "KRW": "韩元",
            "AUD": "澳元",
            "CAD": "加元",
            "SGD": "新加坡元"
        }

    def _create_definition(self) -> ToolDefinition:
        """创建工具定义"""
        return ToolDefinition(
            name="exchange_rate_mcp",
            description="查询实时汇率和货币转换",
            category="mcp",
            version="1.0.0",
            timeout=10,
            parameters=[
                ToolParameter(
                    name="from_currency",
                    type="string",
                    description="源货币代码（如：CNY/USD/EUR等）",
                    required=True
                ),
                ToolParameter(
                    name="to_currency",
                    type="string",
                    description="目标货币代码（如：CNY/USD/EUR等），不指定则返回所有汇率",
                    required=False
                ),
                ToolParameter(
                    name="amount",
                    type="number",
                    description="转换金额，默认为1",
                    required=False,
                    default=1
                )
            ]
        )

    def get_api_endpoint(self) -> str:
        """获取API端点"""
        return "https://open.er-api.com/v6/latest"

    def get_api_key(self) -> Optional[str]:
        """获取API密钥（ExchangeRate-API不需要密钥）"""
        return None

    async def execute(
        self,
        from_currency: str,
        to_currency: Optional[str] = None,
        amount: float = 1,
        **kwargs
    ) -> Dict[str, Any]:
        """
        执行汇率查询

        Args:
            from_currency: 源货币代码
            to_currency: 目标货币代码
            amount: 转换金额
            **kwargs: 其他参数

        Returns:
            汇率信息
        """
        try:
            # 转换为大写
            from_currency = from_currency.upper()
            if to_currency:
                to_currency = to_currency.upper()

            # 构建API URL
            api_url = f"{self.get_api_endpoint()}/{from_currency}"

            # 发起请求
            self.logger.info(f"查询汇率: {from_currency} -> {to_currency or '所有货币'}")
            response = await self._make_request("GET", api_url)

            if not response.get("success"):
                return response

            # 解析汇率数据
            rate_data = response["data"]

            if rate_data.get("result") != "success":
                return {
                    "success": False,
                    "error": f"不支持的货币代码: {from_currency}"
                }

            rates = rate_data.get("rates", {})

            # 如果指定了目标货币
            if to_currency:
                if to_currency not in rates:
                    return {
                        "success": False,
                        "error": f"不支持的货币代码: {to_currency}"
                    }

                rate = rates[to_currency]
                converted_amount = amount * rate

                result = {
                    "from_currency": from_currency,
                    "to_currency": to_currency,
                    "exchange_rate": rate,
                    "amount": amount,
                    "converted_amount": round(converted_amount, 2),
                    "last_update": rate_data.get("time_last_update_utc", "")
                }
            else:
                # 返回常用货币的汇率
                result = {
                    "base_currency": from_currency,
                    "common_rates": {},
                    "last_update": rate_data.get("time_last_update_utc", "")
                }

                for code, name in self.common_currencies.items():
                    if code in rates and code != from_currency:
                        result["common_rates"][code] = {
                            "name": name,
                            "rate": rates[code],
                            "converted": round(amount * rates[code], 2)
                        }

            return {
                "success": True,
                "data": result
            }

        except Exception as e:
            self.logger.error(f"汇率查询失败: {str(e)}", exc_info=True)
            return {
                "success": False,
                "error": f"汇率查询失败: {str(e)}"
            }
