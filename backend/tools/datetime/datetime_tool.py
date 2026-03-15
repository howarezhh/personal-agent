
from typing import Dict, Any, Optional
from datetime import datetime, timedelta
import pytz
from backend.tools.base_tool import BaseTool, ToolDefinition, ToolParameter
import logging


class DateTimeTool(BaseTool):
    # 常用时区
    COMMON_TIMEZONES = {
        "UTC": "UTC",
        "Asia/Shanghai": "中国标准时间",
        "Asia/Tokyo": "日本标准时间",
        "Asia/Seoul": "韩国标准时间",
        "America/New_York": "美国东部时间",
        "America/Los_Angeles": "美国西部时间",
        "Europe/London": "英国时间",
        "Europe/Paris": "欧洲中部时间",
        "Australia/Sydney": "澳大利亚东部时间"
    }

    def __init__(self):
        super().__init__()
        self.logger = logging.getLogger(self.__class__.__name__)
        self.logger.info("时间日期工具初始化完成")

    def _create_definition(self) -> ToolDefinition:
        return ToolDefinition(
            name="datetime",
            description="时间日期工具，支持查询当前时间、日期计算、时区转换、日期格式化等功能",
            category="utility",
            strict_validation=True,
            parameters=[
                ToolParameter(
                    name="action",
                    type="string",
                    description="操作类型：current_time(当前时间), date_calc(日期计算), timezone_convert(时区转换), date_diff(日期差), format_date(格式化日期)",
                    required=True,
                    enum=["current_time", "date_calc", "timezone_convert", "date_diff", "format_date"]
                ),
                ToolParameter(
                    name="timezone",
                    type="string",
                    description="时区（如：Asia/Shanghai, UTC）",
                    required=False,
                    default="Asia/Shanghai"
                ),
                ToolParameter(
                    name="date",
                    type="string",
                    description="日期字符串（格式：YYYY-MM-DD 或 YYYY-MM-DD HH:MM:SS）",
                    required=False
                ),
                ToolParameter(
                    name="days",
                    type="integer",
                    description="天数（用于日期计算，正数为加，负数为减）",
                    required=False
                ),
                ToolParameter(
                    name="months",
                    type="integer",
                    description="月数（用于日期计算，正数为加，负数为减）",
                    required=False
                ),
                ToolParameter(
                    name="years",
                    type="integer",
                    description="年数（用于日期计算，正数为加，负数为减）",
                    required=False
                ),
                ToolParameter(
                    name="from_timezone",
                    type="string",
                    description="源时区（用于时区转换）",
                    required=False
                ),
                ToolParameter(
                    name="to_timezone",
                    type="string",
                    description="目标时区（用于时区转换）",
                    required=False
                ),
                ToolParameter(
                    name="date1",
                    type="string",
                    description="第一个日期（用于计算日期差）",
                    required=False
                ),
                ToolParameter(
                    name="date2",
                    type="string",
                    description="第二个日期（用于计算日期差）",
                    required=False
                ),
                ToolParameter(
                    name="format",
                    type="string",
                    description="日期格式（如：%Y-%m-%d, %Y年%m月%d日）",
                    required=False,
                    default="%Y-%m-%d %H:%M:%S"
                )
            ],
            timeout=10
        )

    async def execute(self, action: str, **kwargs) -> Dict[str, Any]:
        try:
            self.logger.info(f"执行时间日期操作: {action}")

            if action == "current_time":
                return await self._get_current_time(kwargs.get("timezone", "Asia/Shanghai"))
            elif action == "date_calc":
                return await self._calculate_date(
                    kwargs.get("date"),
                    kwargs.get("days", 0),
                    kwargs.get("months", 0),
                    kwargs.get("years", 0),
                    kwargs.get("timezone", "Asia/Shanghai")
                )
            elif action == "timezone_convert":
                return await self._convert_timezone(
                    kwargs.get("date"),
                    kwargs.get("from_timezone", "Asia/Shanghai"),
                    kwargs.get("to_timezone", "UTC")
                )
            elif action == "date_diff":
                return await self._calculate_date_diff(
                    kwargs.get("date1"),
                    kwargs.get("date2")
                )
            elif action == "format_date":
                return await self._format_date(
                    kwargs.get("date"),
                    kwargs.get("format", "%Y-%m-%d %H:%M:%S"),
                    kwargs.get("timezone", "Asia/Shanghai")
                )
            else:
                return {
                    "success": False,
                    "data": None,
                    "error": f"不支持的操作类型: {action}",
                    "error_code": "TOOL_INVALID_PARAMETER",
                    "error_type": "parameter_error",
                }

        except Exception as e:
            self.logger.error(f"时间日期操作失败: {str(e)}", exc_info=True)
            return {
                "success": False,
                "data": None,
                "error": f"操作失败: {str(e)}"
            }

    async def _get_current_time(self, timezone: str) -> Dict[str, Any]:
        try:
            tz = pytz.timezone(timezone)
            now = datetime.now(tz)

            return {
                "success": True,
                "data": {
                    "datetime": now.strftime("%Y-%m-%d %H:%M:%S"),
                    "date": now.strftime("%Y-%m-%d"),
                    "time": now.strftime("%H:%M:%S"),
                    "timezone": timezone,
                    "timezone_name": self.COMMON_TIMEZONES.get(timezone, timezone),
                    "timestamp": int(now.timestamp()),
                    "weekday": now.strftime("%A"),
                    "weekday_cn": ["星期一", "星期二", "星期三", "星期四", "星期五", "星期六", "星期日"][now.weekday()],
                    "year": now.year,
                    "month": now.month,
                    "day": now.day,
                    "hour": now.hour,
                    "minute": now.minute,
                    "second": now.second
                },
                "error": None
            }
        except Exception as e:
            return {
                "success": False,
                "data": None,
                "error": f"获取当前时间失败: {str(e)}"
            }

    async def _calculate_date(self, date_str: Optional[str], days: int, months: int, years: int, timezone: str) -> Dict[str, Any]:
        try:
            tz = pytz.timezone(timezone)

            # 解析日期
            if date_str:
                if len(date_str) == 10:  # YYYY-MM-DD
                    base_date = datetime.strptime(date_str, "%Y-%m-%d")
                else:  # YYYY-MM-DD HH:MM:SS
                    base_date = datetime.strptime(date_str, "%Y-%m-%d %H:%M:%S")
                base_date = tz.localize(base_date)
            else:
                base_date = datetime.now(tz)

            # 计算新日期
            new_date = base_date
            if days:
                new_date += timedelta(days=days)
            if months:
                # 简单的月份计算
                month = new_date.month + months
                year = new_date.year
                while month > 12:
                    month -= 12
                    year += 1
                while month < 1:
                    month += 12
                    year -= 1
                new_date = new_date.replace(year=year, month=month)
            if years:
                new_date = new_date.replace(year=new_date.year + years)

            return {
                "success": True,
                "data": {
                    "original_date": base_date.strftime("%Y-%m-%d %H:%M:%S"),
                    "calculated_date": new_date.strftime("%Y-%m-%d %H:%M:%S"),
                    "days_added": days,
                    "months_added": months,
                    "years_added": years,
                    "timezone": timezone
                },
                "error": None
            }
        except Exception as e:
            return {
                "success": False,
                "data": None,
                "error": f"日期计算失败: {str(e)}"
            }

    async def _convert_timezone(self, date_str: Optional[str], from_tz: str, to_tz: str) -> Dict[str, Any]:
        try:
            from_timezone = pytz.timezone(from_tz)
            to_timezone = pytz.timezone(to_tz)

            # 解析日期
            if date_str:
                if len(date_str) == 10:  # YYYY-MM-DD
                    dt = datetime.strptime(date_str, "%Y-%m-%d")
                else:  # YYYY-MM-DD HH:MM:SS
                    dt = datetime.strptime(date_str, "%Y-%m-%d %H:%M:%S")
                dt = from_timezone.localize(dt)
            else:
                dt = datetime.now(from_timezone)

            # 转换时区
            converted_dt = dt.astimezone(to_timezone)

            return {
                "success": True,
                "data": {
                    "original_datetime": dt.strftime("%Y-%m-%d %H:%M:%S"),
                    "original_timezone": from_tz,
                    "original_timezone_name": self.COMMON_TIMEZONES.get(from_tz, from_tz),
                    "converted_datetime": converted_dt.strftime("%Y-%m-%d %H:%M:%S"),
                    "converted_timezone": to_tz,
                    "converted_timezone_name": self.COMMON_TIMEZONES.get(to_tz, to_tz),
                    "time_difference_hours": (converted_dt.utcoffset().total_seconds() - dt.utcoffset().total_seconds()) / 3600
                },
                "error": None
            }
        except Exception as e:
            return {
                "success": False,
                "data": None,
                "error": f"时区转换失败: {str(e)}"
            }

    async def _calculate_date_diff(self, date1_str: Optional[str], date2_str: Optional[str]) -> Dict[str, Any]:
        try:
            if not date1_str or not date2_str:
                return {
                    "success": False,
                    "data": None,
                    "error": "需要提供两个日期"
                }

            # 解析日期
            if len(date1_str) == 10:
                date1 = datetime.strptime(date1_str, "%Y-%m-%d")
            else:
                date1 = datetime.strptime(date1_str, "%Y-%m-%d %H:%M:%S")

            if len(date2_str) == 10:
                date2 = datetime.strptime(date2_str, "%Y-%m-%d")
            else:
                date2 = datetime.strptime(date2_str, "%Y-%m-%d %H:%M:%S")

            # 计算差值
            diff = date2 - date1
            total_seconds = abs(diff.total_seconds())
            days = int(total_seconds // 86400)
            hours = int((total_seconds % 86400) // 3600)
            minutes = int((total_seconds % 3600) // 60)
            seconds = int(total_seconds % 60)

            return {
                "success": True,
                "data": {
                    "date1": date1_str,
                    "date2": date2_str,
                    "total_days": days,
                    "total_hours": int(total_seconds // 3600),
                    "total_minutes": int(total_seconds // 60),
                    "total_seconds": int(total_seconds),
                    "formatted_diff": f"{days}天 {hours}小时 {minutes}分钟 {seconds}秒",
                    "is_future": diff.total_seconds() > 0
                },
                "error": None
            }
        except Exception as e:
            return {
                "success": False,
                "data": None,
                "error": f"计算日期差失败: {str(e)}"
            }

    async def _format_date(self, date_str: Optional[str], format_str: str, timezone: str) -> Dict[str, Any]:
        try:
            tz = pytz.timezone(timezone)

            # 解析日期
            if date_str:
                if len(date_str) == 10:
                    dt = datetime.strptime(date_str, "%Y-%m-%d")
                else:
                    dt = datetime.strptime(date_str, "%Y-%m-%d %H:%M:%S")
                dt = tz.localize(dt)
            else:
                dt = datetime.now(tz)

            # 格式化
            formatted = dt.strftime(format_str)

            return {
                "success": True,
                "data": {
                    "original_date": date_str or "当前时间",
                    "formatted_date": formatted,
                    "format": format_str,
                    "timezone": timezone
                },
                "error": None
            }
        except Exception as e:
            return {
                "success": False,
                "data": None,
                "error": f"格式化日期失败: {str(e)}"
            }

    def get_supported_timezones(self) -> Dict[str, str]:
        return self.COMMON_TIMEZONES.copy()
