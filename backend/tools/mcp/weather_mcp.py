from __future__ import annotations

import logging
from typing import Any, Dict, Optional

from backend.tools.base_tool import ToolDefinition, ToolExecutionError, ToolNetworkError, ToolParameter, ToolParameterError
from backend.tools.mcp.base_mcp_tool import BuiltinMCPTool


class WeatherMCP(BuiltinMCPTool):
    def __init__(self):
        super().__init__()
        self.logger = logging.getLogger(self.__class__.__name__)
        self.city_coords = {
            "北京": {"lat": 39.9042, "lon": 116.4074},
            "上海": {"lat": 31.2304, "lon": 121.4737},
            "广州": {"lat": 23.1291, "lon": 113.2644},
            "深圳": {"lat": 22.5431, "lon": 114.0579},
            "成都": {"lat": 30.5728, "lon": 104.0668},
            "杭州": {"lat": 30.2741, "lon": 120.1551},
            "武汉": {"lat": 30.5928, "lon": 114.3055},
            "西安": {"lat": 34.3416, "lon": 108.9398},
            "重庆": {"lat": 29.4316, "lon": 106.9123},
            "南京": {"lat": 32.0603, "lon": 118.7969},
        }
        self.city_aliases = {
            "beijing": "北京",
            "shanghai": "上海",
            "guangzhou": "广州",
            "shenzhen": "深圳",
            "chengdu": "成都",
            "hangzhou": "杭州",
            "wuhan": "武汉",
            "xian": "西安",
            "xi'an": "西安",
            "chongqing": "重庆",
            "nanjing": "南京",
        }

    def _create_definition(self) -> ToolDefinition:
        return ToolDefinition(
            name="weather_mcp",
            description="查询指定城市当前天气及未来 7 天内的天气预报。",
            category="weather",
            version="1.0.0",
            timeout=10,
            strict_validation=True,
            parameters=[
                ToolParameter(
                    name="city",
                    type="string",
                    description="城市名称，支持中文或英文别名，例如：广州、Beijing。",
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

    def get_api_key(self) -> Optional[str]:
        return None

    def _normalize_city_name(self, city: str) -> str:
        normalized = city.strip()
        if normalized in self.city_coords:
            return normalized
        return self.city_aliases.get(normalized.lower(), normalized)

    async def execute(self, city: str, forecast_days: int = 1, **kwargs) -> Dict[str, Any]:
        try:
            normalized_city = self._normalize_city_name(city)
            if normalized_city not in self.city_coords:
                raise ToolParameterError(
                    f"暂不支持城市：{city}。当前支持：{', '.join(self.city_coords.keys())}"
                )

            if isinstance(forecast_days, str):
                try:
                    forecast_days = int(forecast_days)
                except ValueError as error:
                    raise ToolParameterError(f"forecast_days 必须是整数：{forecast_days}") from error

            forecast_days = max(1, min(7, forecast_days))
            coords = self.city_coords[normalized_city]
            params = {
                "latitude": coords["lat"],
                "longitude": coords["lon"],
                "current": "temperature_2m,relative_humidity_2m,apparent_temperature,precipitation,weather_code,wind_speed_10m",
                "daily": "temperature_2m_max,temperature_2m_min,precipitation_sum,weather_code,wind_speed_10m_max",
                "timezone": "Asia/Shanghai",
                "forecast_days": forecast_days,
            }
            response = await self._make_request("GET", self.get_api_endpoint(), params=params)
            if not response.get("success"):
                return response
            weather_data = response["data"]
            return {
                "success": True,
                "data": self._parse_weather_data(normalized_city, weather_data, forecast_days),
            }
        except (ToolParameterError, ToolNetworkError):
            raise
        except Exception as error:
            raise ToolExecutionError(f"天气查询失败: {error}") from error

    def _parse_weather_data(self, city: str, data: Dict[str, Any], forecast_days: int) -> Dict[str, Any]:
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
        result = {"city": city, "current": None, "forecast": []}

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
