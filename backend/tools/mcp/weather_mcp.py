
from typing import Dict, Any, Optional
from backend.tools.mcp.base_mcp_tool import MCPTool
from backend.tools.base_tool import ToolDefinition, ToolParameter
import logging


class WeatherMCP(MCPTool):
    def __init__(self):
        super().__init__()
        self.logger = logging.getLogger(self.__class__.__name__)
        # 主要城市坐标映射
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

    def _create_definition(self) -> ToolDefinition:
        return ToolDefinition(
            name="weather_mcp",
            description="查询天气信息，支持当前天气和未来7天预报",
            category="mcp",
            version="1.0.0",
            timeout=10,
            strict_validation=True,
            parameters=[
                ToolParameter(
                    name="city",
                    type="string",
                    description="城市名称（如：北京、上海、广州等）",
                    required=True
                ),
                ToolParameter(
                    name="forecast_days",
                    type="integer",
                    description="预报天数（1-7天），默认为1天",
                    required=False,
                    default=1,
                    minimum=1,
                    maximum=7,
                )
            ]
        )

    def get_api_endpoint(self) -> str:
        return "https://api.open-meteo.com/v1/forecast"

    def get_api_key(self) -> Optional[str]:
        return None

    async def execute(self, city: str, forecast_days: int = 1, **kwargs) -> Dict[str, Any]:
        try:
            # 参数类型转换和验证
            if isinstance(forecast_days, str):
                try:
                    forecast_days = int(forecast_days)
                except ValueError:
                    return {
                        "success": False,
                        "error": f"预报天数必须是数字，当前值: {forecast_days}"
                    }

            # 获取城市坐标
            if city not in self.city_coords:
                return {
                    "success": False,
                    "error": f"不支持的城市: {city}，当前支持的城市: {', '.join(self.city_coords.keys())}"
                }

            coords = self.city_coords[city]
            lat = coords["lat"]
            lon = coords["lon"]

            # 限制预报天数
            forecast_days = max(1, min(7, forecast_days))

            # 构建请求参数
            params = {
                "latitude": lat,
                "longitude": lon,
                "current": "temperature_2m,relative_humidity_2m,apparent_temperature,precipitation,weather_code,wind_speed_10m",
                "daily": "temperature_2m_max,temperature_2m_min,precipitation_sum,weather_code,wind_speed_10m_max",
                "timezone": "Asia/Shanghai",
                "forecast_days": forecast_days
            }

            # 发起请求
            self.logger.info(f"查询天气: {city}, 预报天数: {forecast_days}")
            response = await self._make_request("GET", self.get_api_endpoint(), params=params)

            if not response.get("success"):
                return response

            # 解析天气数据
            weather_data = response["data"]
            result = self._parse_weather_data(city, weather_data, forecast_days)

            return {
                "success": True,
                "data": result
            }

        except Exception as e:
            self.logger.error(f"天气查询失败: {str(e)}", exc_info=True)
            return {
                "success": False,
                "error": f"天气查询失败: {str(e)}"
            }

    def _parse_weather_data(self, city: str, data: Dict[str, Any], forecast_days: int) -> Dict[str, Any]:
        # 天气代码映射
        weather_codes = {
            0: "晴朗",
            1: "基本晴朗",
            2: "部分多云",
            3: "阴天",
            45: "有雾",
            48: "雾凇",
            51: "小雨",
            53: "中雨",
            55: "大雨",
            61: "小雨",
            63: "中雨",
            65: "大雨",
            71: "小雪",
            73: "中雪",
            75: "大雪",
            77: "雪粒",
            80: "阵雨",
            81: "中阵雨",
            82: "大阵雨",
            85: "小阵雪",
            86: "大阵雪",
            95: "雷暴",
            96: "雷暴伴冰雹",
            99: "强雷暴伴冰雹"
        }

        result = {
            "city": city,
            "current": None,
            "forecast": []
        }

        # 当前天气
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
                "time": current.get("time", "")
            }

        # 未来天气预报
        if "daily" in data:
            daily = data["daily"]
            for i in range(min(forecast_days, len(daily.get("time", [])))):
                weather_code = daily["weather_code"][i] if i < len(daily.get("weather_code", [])) else 0
                forecast_item = {
                    "date": daily["time"][i],
                    "temperature_max": f"{daily['temperature_2m_max'][i]}°C",
                    "temperature_min": f"{daily['temperature_2m_min'][i]}°C",
                    "precipitation": f"{daily['precipitation_sum'][i]}mm",
                    "wind_speed_max": f"{daily['wind_speed_10m_max'][i]}km/h",
                    "weather": weather_codes.get(weather_code, "未知")
                }
                result["forecast"].append(forecast_item)

        return result
