"""工具结果解释器。

该模块负责把不同工具返回的原始结构化结果，统一转换为：
1. 可直接展示给用户的 `formatted_text`。
2. 便于前端或上层业务复用的 `key_info`。
3. 保留原始结果 `raw_data` 以支持调试与审计。

这样可以让 `ToolAgent` 只关心“调用工具”，而把“如何解释结果”收敛到单独组件中。
"""

import logging
from typing import Any, Callable, Dict

from backend.core.prompt_manager import get_prompt_manager
from backend.contracts.tools.tool_errors import ToolErrorCode, ToolErrorType
from backend.core.llm_manager import get_langchain_model_manager


class ResultInterpreter:
    """工具结果统一解释器。"""

    def __init__(self, enable_llm_interpretation: bool = False):
        """初始化解释器。

        - `enable_llm_interpretation`：是否启用基于大模型的增强解释。
        - `llm_client`：仅在启用增强解释时创建，避免无意义的依赖初始化。
        - `_interpreters`：维护“工具名 -> 专用解释函数”的映射。
        """
        self.logger = logging.getLogger(self.__class__.__name__)
        self.prompt_manager = get_prompt_manager()
        self.enable_llm_interpretation = enable_llm_interpretation
        if enable_llm_interpretation:
            self.model_manager = get_langchain_model_manager()
        else:
            self.model_manager = None

        self._interpreters: Dict[str, Callable] = {
            "calculator": self._interpret_calculator,
            "web_search": self._interpret_web_search,
            "database_query": self._interpret_database_query,
            "weather_mcp": self._interpret_weather_mcp,
            "news_mcp": self._interpret_news_mcp,
            "wikipedia_mcp": self._interpret_wikipedia_mcp,
            "exchange_rate_mcp": self._interpret_exchange_rate_mcp,
            "ip_lookup_mcp": self._interpret_ip_lookup_mcp,
        }

    def register_interpreter(self, tool_name: str, interpreter_func: Callable) -> None:
        """注册自定义结果解释函数。"""
        self._interpreters[tool_name] = interpreter_func
        self.logger.info("Registered custom interpreter for tool: %s", tool_name)

    def unregister_interpreter(self, tool_name: str) -> bool:
        """注销某个工具解释器；成功移除时返回 `True`。"""
        if tool_name in self._interpreters:
            del self._interpreters[tool_name]
            self.logger.info("Unregistered interpreter for tool: %s", tool_name)
            return True
        return False

    def interpret(self, tool_name: str, tool_result: Dict[str, Any]) -> Dict[str, Any]:
        """按工具名解释工具执行结果。"""
        try:
            if not tool_result.get("success", False):
                return {
                    "success": False,
                    "formatted_text": f"工具调用失败：{tool_result.get('error', '未知错误')}",
                    "key_info": {},
                    "error_code": tool_result.get("error_code"),
                    "error_type": tool_result.get("error_type"),
                    "raw_data": tool_result,
                }

            interpreter = self._interpreters.get(tool_name)
            if interpreter:
                return interpreter(tool_result)

            return self._interpret_default(tool_result)

        except Exception as error:
            self.logger.error("Result interpretation failed: %s", str(error), exc_info=True)
            return {
                "success": False,
                "formatted_text": f"结果解释失败：{str(error)}",
                "key_info": {},
                "error_code": ToolErrorCode.TOOL_RESULT_INTERPRETATION_ERROR.value,
                "error_type": ToolErrorType.EXECUTION_ERROR.value,
                "raw_data": tool_result,
            }

    def _interpret_calculator(self, tool_result: Dict[str, Any]) -> Dict[str, Any]:
        """解释计算器结果。"""
        data = tool_result.get("data", {})
        expression = data.get("expression", "")
        result = data.get("result", "")

        formatted_text = f"计算结果：{expression} = {result}"

        return {
            "success": True,
            "formatted_text": formatted_text,
            "key_info": {
                "expression": expression,
                "result": result,
            },
            "raw_data": tool_result,
        }

    def _interpret_weather_mcp(self, tool_result: Dict[str, Any]) -> Dict[str, Any]:
        """解释天气工具结果。"""
        data = tool_result.get("data", {})
        city = data.get("city", "")
        current = data.get("current", {})
        forecast = data.get("forecast", [])

        lines = [f"{city}天气信息："]

        # 当前天气部分。
        if current:
            lines.append("\n当前天气：")
            lines.append(f"  温度：{current.get('temperature', 'N/A')}")
            lines.append(f"  体感温度：{current.get('feels_like', 'N/A')}")
            lines.append(f"  湿度：{current.get('humidity', 'N/A')}")
            lines.append(f"  天气：{current.get('weather', 'N/A')}")
            lines.append(f"  风速：{current.get('wind_speed', 'N/A')}")

        # 未来天气预报部分。
        if forecast:
            lines.append(f"\n未来 {len(forecast)} 天预报：")
            for item in forecast:
                lines.append(f"  {item.get('date', 'N/A')}：")
                lines.append(
                    f"    温度：{item.get('temperature_min', 'N/A')} ~ {item.get('temperature_max', 'N/A')}"
                )
                lines.append(f"    天气：{item.get('weather', 'N/A')}")
                lines.append(f"    降水：{item.get('precipitation', 'N/A')}")

        formatted_text = "\n".join(lines)

        return {
            "success": True,
            "formatted_text": formatted_text,
            "key_info": {
                "city": city,
                "current": current,
                "forecast": forecast,
            },
            "raw_data": tool_result,
        }

    def _interpret_news_mcp(self, tool_result: Dict[str, Any]) -> Dict[str, Any]:
        """解释新闻工具结果。"""
        data = tool_result.get("data", {})
        articles = data.get("articles", [])
        total = data.get("total_results", 0)

        lines = [f"找到 {total} 条新闻：\n"]

        for index, article in enumerate(articles[:5], 1):
            lines.append(f"{index}. {article.get('title', 'N/A')}")
            lines.append(f"   来源：{article.get('source', 'N/A')}")
            lines.append(f"   时间：{article.get('published_at', 'N/A')}")
            if article.get("description"):
                lines.append(f"   摘要：{article.get('description', '')[:100]}...")
            lines.append("")

        formatted_text = "\n".join(lines)

        return {
            "success": True,
            "formatted_text": formatted_text,
            "key_info": {
                "total_results": total,
                "articles": articles[:5],
            },
            "raw_data": tool_result,
        }

    def _interpret_wikipedia_mcp(self, tool_result: Dict[str, Any]) -> Dict[str, Any]:
        """解释维基百科工具结果。"""
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
                "url": url,
            },
            "raw_data": tool_result,
        }

    def _interpret_exchange_rate_mcp(self, tool_result: Dict[str, Any]) -> Dict[str, Any]:
        """解释汇率工具结果。"""
        data = tool_result.get("data", {})
        base_currency = data.get("base_currency", "")
        target_currency = data.get("target_currency", "")
        rate = data.get("rate", 0)
        amount = data.get("amount", 0)
        converted_amount = data.get("converted_amount", 0)

        if amount and converted_amount:
            formatted_text = (
                f"汇率转换结果：\n{amount} {base_currency} = {converted_amount} {target_currency}"
                f"\n汇率：1 {base_currency} = {rate} {target_currency}"
            )
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
                "converted_amount": converted_amount,
            },
            "raw_data": tool_result,
        }

    def _interpret_ip_lookup_mcp(self, tool_result: Dict[str, Any]) -> Dict[str, Any]:
        """解释 IP 查询工具结果。"""
        data = tool_result.get("data", {})
        ip = data.get("ip", "")
        country = data.get("country", "")
        city = data.get("city", "")
        isp = data.get("isp", "")
        timezone = data.get("timezone", "")

        lines = [f"IP 地址信息：{ip}\n"]
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
                "timezone": timezone,
            },
            "raw_data": tool_result,
        }

    def _interpret_web_search(self, tool_result: Dict[str, Any]) -> Dict[str, Any]:
        """解释网页搜索工具结果。"""
        data = tool_result.get("data", {})
        description = data.get("description", "")
        results = data.get("results", [])

        formatted_text = description

        key_info = {
            "query": data.get("query", ""),
            "total_results": data.get("total_results", 0),
            # 只保留前 3 条结果，便于上层快速摘要显示。
            "top_results": results[:3] if results else [],
        }

        return {
            "success": True,
            "formatted_text": formatted_text,
            "key_info": key_info,
            "raw_data": tool_result,
        }

    def _interpret_database_query(self, tool_result: Dict[str, Any]) -> Dict[str, Any]:
        """解释数据库查询结果。"""
        data = tool_result.get("data", {})
        description = data.get("description", "")

        formatted_text = description

        return {
            "success": True,
            "formatted_text": formatted_text,
            "key_info": data,
            "raw_data": tool_result,
        }

    def _interpret_default(self, tool_result: Dict[str, Any]) -> Dict[str, Any]:
        """默认解释逻辑。"""
        data = tool_result.get("data", {})

        if isinstance(data, dict):
            formatted_text = data.get("description", "") or data.get("result", "") or str(data)
        else:
            formatted_text = str(data)

        return {
            "success": True,
            "formatted_text": formatted_text,
            "key_info": data if isinstance(data, dict) else {"result": data},
            "raw_data": tool_result,
        }

    def format_for_display(self, interpreted_result: Dict[str, Any]) -> str:
        """提取适合直接展示的文本。"""
        if not interpreted_result.get("success", False):
            return interpreted_result.get("formatted_text", "工具调用失败")

        return interpreted_result.get("formatted_text", "")

    def extract_key_info(self, interpreted_result: Dict[str, Any]) -> Dict[str, Any]:
        """提取解释结果中的关键信息。"""
        return interpreted_result.get("key_info", {})

    async def interpret_with_llm(
        self,
        tool_name: str,
        tool_input: Dict[str, Any],
        tool_output: Dict[str, Any],
        user_question: str,
    ) -> str:
        """使用 LLM 对工具结果做更自然语言化的解释。"""
        if not self.enable_llm_interpretation or not self.model_manager:
            self.logger.warning("LLM interpretation is not enabled")
            return self.interpret(tool_name, tool_output).get("formatted_text", "")

        try:
            prompt_template = self.prompt_manager.get_prompt_template(
                "tool.tool_result_interpretation_prompt"
            )

            if not self.prompt_manager.get_prompt("tool.tool_result_interpretation_prompt"):
                self.logger.warning("Tool result interpretation prompt not found")
                return self.interpret(tool_name, tool_output).get("formatted_text", "")

            response = await self.model_manager.invoke_prompt_template(
                prompt_template,
                {
                    "question": user_question,
                    "tool_name": tool_name,
                    "tool_input": str(tool_input),
                    "tool_output": str(tool_output.get("data", {})),
                },
                temperature=0.7,
                max_tokens=500,
            )

            return response

        except Exception as error:
            self.logger.error("LLM interpretation failed: %s", str(error))
            return self.interpret(tool_name, tool_output).get("formatted_text", "")

    def get_error_message(self, error_type: str) -> str:
        """根据错误类型读取统一错误提示。"""
        error_prompt_prefix = "tool.tool_error_handling"
        error_prompt_key = f"{error_prompt_prefix}.{error_type}"
        error_message = self.prompt_manager.get_prompt(error_prompt_key)
        if error_message:
            return error_message
        return self.prompt_manager.get_prompt(f"{error_prompt_prefix}.unknown_error")
