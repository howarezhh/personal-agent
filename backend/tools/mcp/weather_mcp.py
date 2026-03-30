from __future__ import annotations

import logging
import re
from typing import Any, Dict, Optional

from backend.tools.base_tool import ToolDefinition, ToolExecutionError, ToolNetworkError, ToolParameter, ToolParameterError
from backend.tools.mcp.base_mcp_tool import BuiltinMCPTool


class WeatherMCP(BuiltinMCPTool):
    def __init__(self):
        super().__init__()
        self.logger = logging.getLogger(self.__class__.__name__)

    def _create_definition(self) -> ToolDefinition:
        return ToolDefinition(
            name="weather_mcp",
            description="查询任意城市的当前天气与未来 7 天预报。",
            category="weather",
            version="1.1.0",
            timeout=15,
            strict_validation=True,
            parameters=[
                ToolParameter(
                    name="city",
                    type="string",
                    description="城市名称，支持中文或英文，例如：广州、Beijing、Tokyo。",
                    required=True,
                ),
                ToolParameter(
                    name="forecast_days",
                    type="integer",
                    description="预报天数，范围 1-7，默认 1。",
                    required=False,
                    default=1,
                    minimum=1,
                    maximum=7,
                ),
            ],
        )

    def get_api_endpoint(self) -> str:
        return self.get_configured_endpoint("https://api.open-meteo.com/v1/forecast")

    def get_geocoding_endpoint(self) -> str:
        return self.get_configured_endpoint(
            "https://geocoding-api.open-meteo.com/v1/search",
            key="geocoding_endpoint",
        )

    def get_api_key(self) -> Optional[str]:
        return None

    @staticmethod
    def _detect_language(city: str) -> str:
        return "zh" if re.search(r"[\u4e00-\u9fff]", city) else "en"

    async def _resolve_location(self, city: str) -> dict[str, Any]:
        query = city.strip()
        if not query:
            raise ToolParameterError("city 不能为空")

        response = await self._make_request(
            "GET",
            self.get_geocoding_endpoint(),
            params={
                "name": query,
                "count": 1,
                "language": self._detect_language(query),
                "format": "json",
            },
        )
        if not response.get("success"):
            return response

        results = response.get("data", {}).get("results")
        if not isinstance(results, list) or not results:
            raise ToolParameterError(f"未找到城市: {city}")

        location = results[0]
        return {
            "name": location.get("name", query),
            "country": location.get("country", ""),
            "admin1": location.get("admin1", ""),
            "latitude": location.get("latitude"),
            "longitude": location.get("longitude"),
            "timezone": location.get("timezone") or "auto",
        }

    async def execute(self, city: str, forecast_days: int = 1, **kwargs) -> Dict[str, Any]:
        try:
            if isinstance(forecast_days, str):
                try:
                    forecast_days = int(forecast_days)
                except ValueError as error:
                    raise ToolParameterError(f"forecast_days 必须是整数: {forecast_days}") from error

            forecast_days = max(1, min(7, forecast_days))
            location = await self._resolve_location(city)
            if "success" in location and location.get("success") is False:
                return location

            params = {
                "latitude": location["latitude"],
                "longitude": location["longitude"],
                "current": "temperature_2m,relative_humidity_2m,apparent_temperature,precipitation,weather_code,wind_speed_10m",
                "daily": "temperature_2m_max,temperature_2m_min,precipitation_sum,weather_code,wind_speed_10m_max",
                "timezone": location.get("timezone") or "auto",
                "forecast_days": forecast_days,
            }
            response = await self._make_request("GET", self.get_api_endpoint(), params=params)
            if not response.get("success"):
                return response

            weather_data = response["data"]
            return {
                "success": True,
                "data": self._parse_weather_data(location, weather_data, forecast_days),
            }
        except (ToolParameterError, ToolNetworkError):
            raise
        except Exception as error:
            raise ToolExecutionError(f"天气查询失败: {error}") from error

    def _parse_weather_data(self, location: dict[str, Any], data: Dict[str, Any], forecast_days: int) -> Dict[str, Any]:
        weather_codes = {
            0: "晴",
            1: "大部晴朗",
            2: "局部多云",
            3: "阴",
            45: "雾",
            48: "冻雾",
            51: "小毛雨",
            53: "毛雨",
            55: "大毛雨",
            61: "小雨",
            63: "中雨",
            65: "大雨",
            71: "小雪",
            73: "中雪",
            75: "大雪",
            77: "冰粒",
            80: "小阵雨",
            81: "中阵雨",
            82: "强阵雨",
            85: "小阵雪",
            86: "大阵雪",
            95: "雷暴",
            96: "雷暴伴小冰雹",
            99: "雷暴伴大冰雹",
        }

        result = {
            "city": location.get("name", ""),
            "location": {
                "country": location.get("country", ""),
                "region": location.get("admin1", ""),
                "latitude": location.get("latitude"),
                "longitude": location.get("longitude"),
                "timezone": location.get("timezone", ""),
            },
            "current": None,
            "forecast": [],
        }

        if "current" in data:
            current = data["current"]
            weather_code = current.get("weather_code", 0)
            result["current"] = {
                "temperature": f"{current.get('temperature_2m', 0)}°C",
                "feels_like": f"{current.get('apparent_temperature', 0)}°C",
                "humidity": f"{current.get('relative_humidity_2m', 0)}%",
                "precipitation": f"{current.get('precipitation', 0)}mm",
                "wind_speed": f"{current.get('wind_speed_10m', 0)}km/h",
                "weather": weather_codes.get(weather_code, "未知"),
                "time": current.get("time", ""),
            }

        if "daily" in data:
            daily = data["daily"]
            for index in range(min(forecast_days, len(daily.get("time", [])))):
                weather_code = daily["weather_code"][index] if index < len(daily.get("weather_code", [])) else 0
                result["forecast"].append(
                    {
                        "date": daily["time"][index],
                        "temperature_max": f"{daily['temperature_2m_max'][index]}°C",
                        "temperature_min": f"{daily['temperature_2m_min'][index]}°C",
                        "precipitation": f"{daily['precipitation_sum'][index]}mm",
                        "wind_speed_max": f"{daily['wind_speed_10m_max'][index]}km/h",
                        "weather": weather_codes.get(weather_code, "未知"),
                    }
                )
        return result
