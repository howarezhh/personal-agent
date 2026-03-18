from __future__ import annotations

import logging
from typing import Any, Dict, Optional

from backend.tools.base_tool import ToolDefinition, ToolExecutionError, ToolNetworkError, ToolParameter, ToolParameterError
from backend.tools.mcp.base_mcp_tool import BuiltinMCPTool


class ExchangeRateMCP(BuiltinMCPTool):
    def __init__(self):
        super().__init__()
        self.logger = logging.getLogger(self.__class__.__name__)
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
            "SGD": "新加坡元",
        }

    def _create_definition(self) -> ToolDefinition:
        return ToolDefinition(
            name="exchange_rate_mcp",
            description="查询实时汇率，并支持金额换算。",
            category="finance",
            version="1.0.0",
            timeout=10,
            strict_validation=True,
            parameters=[
                ToolParameter(name="from_currency", type="string", description="基准货币代码，例如 CNY、USD、EUR。", required=True),
                ToolParameter(name="to_currency", type="string", description="目标货币代码；若为空则返回常见汇率。", required=False),
                ToolParameter(name="amount", type="number", description="金额，默认 1。", required=False, default=1),
            ],
        )

    def get_api_endpoint(self) -> str:
        return self.get_configured_endpoint("https://open.er-api.com/v6/latest")

    def get_api_key(self) -> Optional[str]:
        return None

    async def execute(self, from_currency: str, to_currency: Optional[str] = None, amount: float = 1, **kwargs) -> Dict[str, Any]:
        try:
            from_currency = from_currency.upper()
            if to_currency:
                to_currency = to_currency.upper()

            response = await self._make_request("GET", f"{self.get_api_endpoint()}/{from_currency}")
            if not response.get("success"):
                return response

            rate_data = response["data"]
            if rate_data.get("result") != "success":
                raise ToolParameterError(f"不支持的货币代码: {from_currency}")

            rates = rate_data.get("rates", {})
            if to_currency:
                if to_currency not in rates:
                    raise ToolParameterError(f"不支持的目标货币代码: {to_currency}")
                rate = rates[to_currency]
                result = {
                    "from_currency": from_currency,
                    "to_currency": to_currency,
                    "exchange_rate": rate,
                    "amount": amount,
                    "converted_amount": round(amount * rate, 2),
                    "last_update": rate_data.get("time_last_update_utc", ""),
                }
            else:
                common_rates = {}
                for code, name in self.common_currencies.items():
                    if code in rates and code != from_currency:
                        common_rates[code] = {
                            "name": name,
                            "rate": rates[code],
                            "converted": round(amount * rates[code], 2),
                        }
                result = {
                    "base_currency": from_currency,
                    "common_rates": common_rates,
                    "last_update": rate_data.get("time_last_update_utc", ""),
                }
            return {"success": True, "data": result}
        except (ToolParameterError, ToolNetworkError):
            raise
        except Exception as error:
            raise ToolExecutionError(f"汇率查询失败: {error}") from error
