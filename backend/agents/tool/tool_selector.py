"""
工具选择器
负责分析用户问题并选择合适的工具
"""

import json
from typing import Dict, List, Optional
from backend.utils.llm_client import get_llm_client
from backend.tools.tool_registry import get_tool_registry
from backend.core.prompt_manager import get_prompt_manager
import logging


class ToolSelector:
    """
    工具选择器

    功能：
    1. 分析用户问题
    2. 从可用工具列表中选择最合适的工具
    3. 提取工具调用参数
    """

    def __init__(self):
        """初始化工具选择器"""
        self.logger = logging.getLogger(self.__class__.__name__)
        self.llm_client = get_llm_client()
        self.tool_registry = get_tool_registry()
        if self.tool_registry.get_tool_count() == 0:
            from backend.tools import tool_initializer  # noqa: F401
            self.logger.info("工具注册表为空，已触发自动初始化")
        self.prompt_manager = get_prompt_manager()

    async def select_tool(
        self,
        user_question: str,
        available_tools: Optional[List[str]] = None,
        conversation_history: Optional[str] = None
    ) -> Dict:
        """
        选择合适的工具

        Args:
            user_question: 用户问题
            available_tools: 可用工具列表（工具名称），如果为None则使用所有工具
            conversation_history: 对话历史文本

        Returns:
            工具选择结果，格式为:
            {
                "tool_name": str,
                "tool_params": dict,
                "confidence": float,
                "reasoning": str
            }
        """
        try:
            if self._is_explicit_retrieval_question(user_question):
                self.logger.info("检测到显式知识库检索问题，工具选择器返回retrieval移交结果")
                return {
                    "tool_name": None,
                    "tool_params": {},
                    "confidence": 0.98,
                    "reasoning": "问题明确要求查询知识库或文档，应交由检索流程处理",
                    "route_action": "retrieval"
                }

            # 获取工具定义
            if available_tools:
                tool_definitions = [
                    self.tool_registry.get_tool_definition(tool_name)
                    for tool_name in available_tools
                    if self.tool_registry.is_tool_available(tool_name)
                ]
            else:
                tool_definitions = self.tool_registry.get_tool_definitions()

            if not tool_definitions:
                return {
                    "tool_name": None,
                    "tool_params": {},
                    "confidence": 0.0,
                    "reasoning": "没有可用的工具"
                }

            # 构建提示词 - 使用配置文件中的提示词模板
            prompt = self._build_selection_prompt_from_template(
                user_question,
                tool_definitions,
                conversation_history or ""
            )

            # 调用LLM
            messages = [
                {"role": "user", "content": prompt}
            ]

            response = await self.llm_client.chat_completion(
                messages=messages,
                temperature=0.3,
                max_tokens=500
            )

            # 解析响应
            selection = self._parse_selection(response)

            # 验证工具是否存在
            if selection["tool_name"] and not self.tool_registry.is_tool_available(selection["tool_name"]):
                self.logger.warning(f"Selected tool '{selection['tool_name']}' is not available")
                selection["tool_name"] = None
                selection["confidence"] = 0.0
                selection["reasoning"] = "选择的工具不可用"

            return selection

        except Exception as e:
            self.logger.error(f"Tool selection failed: {str(e)}", exc_info=True)
            return {
                "tool_name": None,
                "tool_params": {},
                "confidence": 0.0,
                "reasoning": f"工具选择失败：{str(e)}"
            }

    def _is_explicit_retrieval_question(self, user_question: str) -> bool:
        """显式知识库/文档问题不应进入工具调用。"""
        question = (user_question or "").lower()
        retrieval_keywords = [
            "知识库", "知识库里", "知识库中", "文档", "文档里", "文档中",
            "资料", "资料里", "资料中", "上传的文件", "库里", "库中", "内部文档"
        ]
        external_tool_keywords = [
            "联网", "互联网", "网页", "网站", "实时", "最新", "新闻", "搜索",
            "天气", "汇率", "翻译", "计算", "时间", "日期", "维基", "百科"
        ]

        has_retrieval_keyword = any(keyword in question for keyword in retrieval_keywords)
        has_external_tool_keyword = any(keyword in question for keyword in external_tool_keywords)
        return has_retrieval_keyword and not has_external_tool_keyword

    def _build_selection_prompt_from_template(
        self,
        user_question: str,
        tool_definitions: List[dict],
        conversation_history: str = ""
    ) -> str:
        """
        使用配置文件中的提示词模板构建工具选择提示词

        Args:
            user_question: 用户问题
            tool_definitions: 工具定义列表
            conversation_history: 对话历史文本

        Returns:
            提示词文本
        """
        # 格式化工具列表
        tools_text = ""
        for i, tool_def in enumerate(tool_definitions, start=1):
            tools_text += f"\n{i}. {tool_def['name']}\n"
            tools_text += f"   描述：{tool_def['description']}\n"
            tools_text += f"   分类：{tool_def['category']}\n"

            # 添加参数信息
            params = tool_def.get('parameters', {}).get('properties', {})
            required = tool_def.get('parameters', {}).get('required', [])

            if params:
                tools_text += "   参数：\n"
                for param_name, param_info in params.items():
                    required_mark = "（必需）" if param_name in required else "（可选）"
                    tools_text += f"     - {param_name}{required_mark}: {param_info.get('description', '')}\n"

        # 使用提示词模板
        prompt = self.prompt_manager.format_prompt(
            "tool_selection_prompt",
            available_tools=tools_text,
            question=user_question,
            conversation_history=conversation_history
        )

        # 如果模板不存在，使用默认格式
        if not prompt:
            prompt = self._build_selection_prompt(user_question, tool_definitions)

        return prompt

    def _build_selection_prompt(self, user_question: str, tool_definitions: List[dict]) -> str:
        """
        构建工具选择提示词

        Args:
            user_question: 用户问题
            tool_definitions: 工具定义列表

        Returns:
            提示词文本
        """
        # 格式化工具列表
        tools_text = ""
        for i, tool_def in enumerate(tool_definitions, start=1):
            tools_text += f"\n{i}. {tool_def['name']}\n"
            tools_text += f"   描述：{tool_def['description']}\n"
            tools_text += f"   分类：{tool_def['category']}\n"

            # 添加参数信息
            params = tool_def.get('parameters', {}).get('properties', {})
            required = tool_def.get('parameters', {}).get('required', [])

            if params:
                tools_text += "   参数：\n"
                for param_name, param_info in params.items():
                    required_mark = "（必需）" if param_name in required else "（可选）"
                    tools_text += f"     - {param_name}{required_mark}: {param_info.get('description', '')}\n"

        prompt = f"""请分析以下用户问题，并从可用工具列表中选择最合适的工具。

用户问题：
{user_question}

可用工具列表：
{tools_text}

请按照以下JSON格式返回结果：
```json
{{
    "tool_name": "工具名称（如果不需要工具则为null）",
    "tool_params": {{
        "参数名": "参数值"
    }},
    "confidence": 0.9,
    "reasoning": "选择该工具的理由"
}}
```

注意：
1. 如果用户问题不需要使用任何工具，tool_name应为null
2. tool_params必须包含所有必需参数
3. confidence表示选择的置信度（0-1之间）
4. reasoning简要说明为什么选择这个工具
"""
        return prompt

    def _parse_selection(self, response: str) -> Dict:
        """
        解析LLM返回的工具选择结果

        Args:
            response: LLM返回的文本

        Returns:
            工具选择结果
        """
        try:
            # 尝试提取JSON内容（处理LLM可能返回的额外文本）
            import re

            # 查找JSON代码块
            json_match = re.search(r'```json\s*(.*?)\s*```', response, re.DOTALL)
            if json_match:
                json_str = json_match.group(1)
            else:
                # 查找花括号包裹的JSON
                json_match = re.search(r'\{.*\}', response, re.DOTALL)
                if json_match:
                    json_str = json_match.group(0)
                else:
                    json_str = response.strip()

            selection = json.loads(json_str)

            # 验证格式
            if "tool_name" not in selection:
                selection["tool_name"] = None
            if "tool_params" not in selection:
                selection["tool_params"] = {}
            if "confidence" not in selection:
                selection["confidence"] = 0.5
            if "reasoning" not in selection:
                selection["reasoning"] = "无推理说明"

            return selection

        except json.JSONDecodeError as e:
            self.logger.error(f"工具选择JSON解析失败: {str(e)}")
            return {
                "tool_name": None,
                "tool_params": {},
                "confidence": 0.0,
                "reasoning": "无法解析工具选择结果"
            }

    def get_available_tools(self) -> List[str]:
        """
        获取所有可用工具名称

        Returns:
            工具名称列表
        """
        return self.tool_registry.get_tool_names()

    def get_tools_by_category(self, category: str) -> List[str]:
        """
        根据分类获取工具名称

        Args:
            category: 工具分类

        Returns:
            工具名称列表
        """
        tools = self.tool_registry.get_tools_by_category(category)
        return [tool.get_name() for tool in tools]
