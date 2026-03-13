"""
结果解释器
负责解释工具返回的结果，转换为易于理解的文本
"""

from typing import Dict, Any, Callable
from backend.core.prompt_manager import get_prompt_manager
from backend.utils.llm_client import get_llm_client
import logging


class ResultInterpreter:
    """
    结果解释器

    功能：
    1. 解析工具返回的结果
    2. 格式化为易于理解的文本
    3. 提取关键信息
    4. 使用LLM进行智能解释（可选）
    """

    def __init__(self, enable_llm_interpretation: bool = False):
        """
        初始化结果解释器

        Args:
            enable_llm_interpretation: 是否启用LLM智能解释
        """
        self.logger = logging.getLogger(self.__class__.__name__)
        self.prompt_manager = get_prompt_manager()
        self.enable_llm_interpretation = enable_llm_interpretation
        if enable_llm_interpretation:
            self.llm_client = get_llm_client()
        else:
            self.llm_client = None

        # 工具特定的解释器映射（可配置化）
        self._interpreters: Dict[str, Callable] = {
            # 本地工具
            "calculator": self._interpret_calculator,
            "web_search": self._interpret_web_search,
            "database_query": self._interpret_database_query,
            # MCP工具
            "weather_mcp": self._interpret_weather_mcp,
            "news_mcp": self._interpret_news_mcp,
            "wikipedia_mcp": self._interpret_wikipedia_mcp,
            "exchange_rate_mcp": self._interpret_exchange_rate_mcp,
            "ip_lookup_mcp": self._interpret_ip_lookup_mcp,
        }

    def register_interpreter(self, tool_name: str, interpreter_func: Callable) -> None:
        """
        注册自定义工具解释器

        Args:
            tool_name: 工具名称
            interpreter_func: 解释器函数，接收tool_result参数，返回解释结果字典
        """
        self._interpreters[tool_name] = interpreter_func
        self.logger.info(f"Registered custom interpreter for tool: {tool_name}")

    def unregister_interpreter(self, tool_name: str) -> bool:
        """
        注销工具解释器

        Args:
            tool_name: 工具名称

        Returns:
            是否成功注销
        """
        if tool_name in self._interpreters:
            del self._interpreters[tool_name]
            self.logger.info(f"Unregistered interpreter for tool: {tool_name}")
            return True
        return False

    def interpret(self, tool_name: str, tool_result: Dict[str, Any]) -> Dict[str, Any]:
        """
        解释工具结果

        Args:
            tool_name: 工具名称
            tool_result: 工具返回的结果

        Returns:
            解释后的结果，格式为:
            {
                "success": bool,
                "formatted_text": str,
                "key_info": dict,
                "raw_data": Any
            }
        """
        try:
            # 检查工具执行是否成功
            if not tool_result.get("success", False):
                return {
                    "success": False,
                    "formatted_text": f"工具调用失败：{tool_result.get('error', '未知错误')}",
                    "key_info": {},
                    "raw_data": tool_result
                }

            # 根据工具类型进行不同的解释
            interpreter = self._interpreters.get(tool_name)
            if interpreter:
                return interpreter(tool_result)
            else:
                # 默认解释
                return self._interpret_default(tool_result)

        except Exception as e:
            self.logger.error(f"Result interpretation failed: {str(e)}", exc_info=True)
            return {
                "success": False,
                "formatted_text": f"结果解释失败：{str(e)}",
                "key_info": {},
                "raw_data": tool_result
            }

    def _interpret_calculator(self, tool_result: Dict[str, Any]) -> Dict[str, Any]:
        """
        解释计算器结果

        Args:
            tool_result: 工具结果

        Returns:
            解释后的结果
        """
        data = tool_result.get("data", {})
        expression = data.get("expression", "")
        result = data.get("result", "")

        formatted_text = f"计算结果：{expression} = {result}"

        return {
            "success": True,
            "formatted_text": formatted_text,
            "key_info": {
                "expression": expression,
                "result": result
            },
            "raw_data": tool_result
        }

    def _interpret_weather(self, tool_result: Dict[str, Any]) -> Dict[str, Any]:
        """
        解释天气查询结果（已废弃，使用weather_mcp）

        Args:
            tool_result: 工具结果

        Returns:
            解释后的结果
        """
        return self._interpret_weather_mcp(tool_result)

    def _interpret_weather_mcp(self, tool_result: Dict[str, Any]) -> Dict[str, Any]:
        """
        解释天气MCP结果

        Args:
            tool_result: 工具结果

        Returns:
            解释后的结果
        """
        data = tool_result.get("data", {})
        city = data.get("city", "")
        current = data.get("current", {})
        forecast = data.get("forecast", [])

        # 构建格式化文本
        lines = [f"{city}天气信息："]

        # 当前天气
        if current:
            lines.append(f"\n当前天气：")
            lines.append(f"  温度：{current.get('temperature', 'N/A')}")
            lines.append(f"  体感温度：{current.get('feels_like', 'N/A')}")
            lines.append(f"  湿度：{current.get('humidity', 'N/A')}")
            lines.append(f"  天气：{current.get('weather', 'N/A')}")
            lines.append(f"  风速：{current.get('wind_speed', 'N/A')}")

        # 未来天气预报
        if forecast:
            lines.append(f"\n未来{len(forecast)}天预报：")
            for item in forecast:
                lines.append(f"  {item.get('date', 'N/A')}：")
                lines.append(f"    温度：{item.get('temperature_min', 'N/A')} ~ {item.get('temperature_max', 'N/A')}")
                lines.append(f"    天气：{item.get('weather', 'N/A')}")
                lines.append(f"    降水：{item.get('precipitation', 'N/A')}")

        formatted_text = "\n".join(lines)

        return {
            "success": True,
            "formatted_text": formatted_text,
            "key_info": {
                "city": city,
                "current": current,
                "forecast": forecast
            },
            "raw_data": tool_result
        }

    def _interpret_news_mcp(self, tool_result: Dict[str, Any]) -> Dict[str, Any]:
        """
        解释新闻MCP结果

        Args:
            tool_result: 工具结果

        Returns:
            解释后的结果
        """
        data = tool_result.get("data", {})
        articles = data.get("articles", [])
        total = data.get("total_results", 0)

        lines = [f"找到 {total} 条新闻：\n"]

        for i, article in enumerate(articles[:5], 1):  # 只显示前5条
            lines.append(f"{i}. {article.get('title', 'N/A')}")
            lines.append(f"   来源：{article.get('source', 'N/A')}")
            lines.append(f"   时间：{article.get('published_at', 'N/A')}")
            if article.get('description'):
                lines.append(f"   摘要：{article.get('description', '')[:100]}...")
            lines.append("")

        formatted_text = "\n".join(lines)

        return {
            "success": True,
            "formatted_text": formatted_text,
            "key_info": {
                "total_results": total,
                "articles": articles[:5]
            },
            "raw_data": tool_result
        }

    def _interpret_wikipedia_mcp(self, tool_result: Dict[str, Any]) -> Dict[str, Any]:
        """
        解释维基百科MCP结果

        Args:
            tool_result: 工具结果

        Returns:
            解释后的结果
        """
        data = tool_result.get("data", {})
        title = data.get("title", "")
        summary = data.get("summary", "")
        url = data.get("url", "")

        lines = [f"维基百科：{title}\n"]
        lines.append(summary)
        if url:
            lines.append(f"\n详细信息：{url}")

        formatted_text = "\n".join(lines)

        return {
            "success": True,
            "formatted_text": formatted_text,
            "key_info": {
                "title": title,
                "summary": summary,
                "url": url
            },
            "raw_data": tool_result
        }

    def _interpret_exchange_rate_mcp(self, tool_result: Dict[str, Any]) -> Dict[str, Any]:
        """
        解释汇率MCP结果

        Args:
            tool_result: 工具结果

        Returns:
            解释后的结果
        """
        data = tool_result.get("data", {})
        base_currency = data.get("base_currency", "")
        target_currency = data.get("target_currency", "")
        rate = data.get("rate", 0)
        amount = data.get("amount", 0)
        converted_amount = data.get("converted_amount", 0)

        if amount and converted_amount:
            formatted_text = f"汇率转换结果：\n{amount} {base_currency} = {converted_amount} {target_currency}\n汇率：1 {base_currency} = {rate} {target_currency}"
        else:
            formatted_text = f"汇率查询结果：\n1 {base_currency} = {rate} {target_currency}"

        return {
            "success": True,
            "formatted_text": formatted_text,
            "key_info": {
                "base_currency": base_currency,
                "target_currency": target_currency,
                "rate": rate,
                "amount": amount,
                "converted_amount": converted_amount
            },
            "raw_data": tool_result
        }

    def _interpret_ip_lookup_mcp(self, tool_result: Dict[str, Any]) -> Dict[str, Any]:
        """
        解释IP查询MCP结果

        Args:
            tool_result: 工具结果

        Returns:
            解释后的结果
        """
        data = tool_result.get("data", {})
        ip = data.get("ip", "")
        country = data.get("country", "")
        city = data.get("city", "")
        isp = data.get("isp", "")
        timezone = data.get("timezone", "")

        lines = [f"IP地址信息：{ip}\n"]
        lines.append(f"国家：{country}")
        lines.append(f"城市：{city}")
        lines.append(f"ISP：{isp}")
        lines.append(f"时区：{timezone}")

        formatted_text = "\n".join(lines)

        return {
            "success": True,
            "formatted_text": formatted_text,
            "key_info": {
                "ip": ip,
                "country": country,
                "city": city,
                "isp": isp,
                "timezone": timezone
            },
            "raw_data": tool_result
        }

    def _interpret_web_search(self, tool_result: Dict[str, Any]) -> Dict[str, Any]:
        """
        解释网络搜索结果

        Args:
            tool_result: 工具结果

        Returns:
            解释后的结果
        """
        data = tool_result.get("data", {})
        description = data.get("description", "")
        results = data.get("results", [])

        formatted_text = description

        # 提取关键信息
        key_info = {
            "query": data.get("query", ""),
            "total_results": data.get("total_results", 0),
            "top_results": results[:3] if results else []  # 只保留前3个结果
        }

        return {
            "success": True,
            "formatted_text": formatted_text,
            "key_info": key_info,
            "raw_data": tool_result
        }

    def _interpret_database_query(self, tool_result: Dict[str, Any]) -> Dict[str, Any]:
        """
        解释数据库查询结果

        Args:
            tool_result: 工具结果

        Returns:
            解释后的结果
        """
        data = tool_result.get("data", {})
        description = data.get("description", "")

        formatted_text = description

        return {
            "success": True,
            "formatted_text": formatted_text,
            "key_info": data,
            "raw_data": tool_result
        }

    def _interpret_default(self, tool_result: Dict[str, Any]) -> Dict[str, Any]:
        """
        默认解释方法

        Args:
            tool_result: 工具结果

        Returns:
            解释后的结果
        """
        data = tool_result.get("data", {})

        # 尝试提取描述文本
        if isinstance(data, dict):
            formatted_text = data.get("description", "") or data.get("result", "") or str(data)
        else:
            formatted_text = str(data)

        return {
            "success": True,
            "formatted_text": formatted_text,
            "key_info": data if isinstance(data, dict) else {"result": data},
            "raw_data": tool_result
        }

    def format_for_display(self, interpreted_result: Dict[str, Any]) -> str:
        """
        格式化为展示文本

        Args:
            interpreted_result: 解释后的结果

        Returns:
            展示文本
        """
        if not interpreted_result.get("success", False):
            return interpreted_result.get("formatted_text", "工具调用失败")

        return interpreted_result.get("formatted_text", "")

    def extract_key_info(self, interpreted_result: Dict[str, Any]) -> Dict[str, Any]:
        """
        提取关键信息

        Args:
            interpreted_result: 解释后的结果

        Returns:
            关键信息字典
        """
        return interpreted_result.get("key_info", {})

    async def interpret_with_llm(
        self,
        tool_name: str,
        tool_input: Dict[str, Any],
        tool_output: Dict[str, Any],
        user_question: str
    ) -> str:
        """
        使用LLM智能解释工具结果

        Args:
            tool_name: 工具名称
            tool_input: 工具输入参数
            tool_output: 工具输出结果
            user_question: 用户原始问题

        Returns:
            友好的解释文本
        """
        if not self.enable_llm_interpretation or not self.llm_client:
            self.logger.warning("LLM interpretation is not enabled")
            return self.interpret(tool_name, tool_output).get("formatted_text", "")

        try:
            # 使用工具结果解释提示词
            prompt = self.prompt_manager.format_prompt(
                "tool.tool_result_interpretation_prompt",
                question=user_question,
                tool_name=tool_name,
                tool_input=str(tool_input),
                tool_output=str(tool_output.get("data", {}))
            )

            if not prompt:
                self.logger.warning("Tool result interpretation prompt not found")
                return self.interpret(tool_name, tool_output).get("formatted_text", "")

            # 调用LLM
            messages = [{"role": "user", "content": prompt}]
            response = await self.llm_client.chat_completion(
                messages=messages,
                temperature=0.7,
                max_tokens=500
            )

            return response

        except Exception as e:
            self.logger.error(f"LLM interpretation failed: {str(e)}")
            # 降级到基础解释
            return self.interpret(tool_name, tool_output).get("formatted_text", "")

    def get_error_message(self, error_type: str) -> str:
        """
        获取工具错误的友好提示信息

        Args:
            error_type: 错误类型（timeout/invalid_parameters/tool_unavailable/unknown_error）

        Returns:
            错误提示信息
        """
        error_prompt_key = f"tool.tool_error_handling.{error_type}"
        error_message = self.prompt_manager.get_prompt(error_prompt_key)

        if error_message:
            return error_message

        # 默认错误信息
        return "工具执行出现错误，请稍后重试。"
