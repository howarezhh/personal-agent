"""工具选择器。

该模块负责根据用户问题、可见工具列表以及会话上下文，
调用大模型判断是否需要使用工具，以及应该选择哪个工具。

设计目标：
1. 将“是否调用工具”的决策逻辑从 `ToolAgent` 中拆分出来，降低职责耦合。
2. 将工具可见性过滤、Prompt 构造、LLM 响应解析集中到一个组件中维护。
3. 在明确是知识库检索问题时，直接返回路由建议，避免误调用外部工具。
"""

import json
import logging
from typing import Dict, List, Optional, Tuple

from langchain_core.prompts import PromptTemplate
from pydantic import BaseModel, Field

from backend.core.prompt_manager import get_prompt_manager
from backend.tools.tool_config import get_tool_config
from backend.tools.tool_initializer import ensure_tools_initialized
from backend.tools.tool_registry import get_tool_registry
from backend.core.llm_manager import get_langchain_model_manager


class ToolSelectionStructuredResult(BaseModel):
    """Structured result for tool selection."""


    tool_name: Optional[str] = None
    tool_params: Dict[str, object] = Field(default_factory=dict)
    confidence: float = 0.0
    reasoning: str = ""
    route_action: Optional[str] = None


class ToolSelector:
    """负责选择最合适工具的组件。

    关键成员说明：
    - `logger`：记录工具筛选、Prompt 构造和异常信息。
    - `llm_client`：与大模型通信，用于完成工具选择推理。
    - `tool_registry`：读取当前已注册且可用的工具定义。
    - `prompt_manager`：统一加载工具选择 Prompt，避免在代码中硬编码长提示词。
    - `tool_config`：读取工具暴露策略，例如哪些工具允许暴露给 Agent。
    """

    def __init__(self):
        """初始化工具选择器依赖。"""
        self.logger = logging.getLogger(self.__class__.__name__)
        self.model_manager = get_langchain_model_manager()
        self.tool_registry = get_tool_registry()
        if self.tool_registry.get_tool_count() == 0:
            ensure_tools_initialized(strict=False)
            self.logger.info("工具注册表为空，已触发自动初始化")
        self.prompt_manager = get_prompt_manager()
        self.tool_config = get_tool_config()

    async def select_tool(
        self,
        user_question: str,
        available_tools: Optional[List[str]] = None,
        conversation_history: Optional[str] = None,
    ) -> Dict:
        """根据问题与上下文选择工具。

        参数说明：
        - `user_question`：当前用户问题，是工具选择的核心输入。
        - `available_tools`：调用方限定的候选工具列表；若为空则使用全部对 Agent 可见的工具。
        - `conversation_history`：会话历史摘要，帮助模型结合上下文做决策。

        返回结构说明：
        - `tool_name`：选中的工具名；为 `None` 表示无需工具。
        - `tool_params`：工具调用参数。
        - `confidence`：模型对本次选择的置信度。
        - `reasoning`：工具选择原因说明。
        - `route_action`：当应转检索链路等非工具路径时给出的路由建议。
        """
        try:
            if self._is_explicit_retrieval_question(user_question):
                self.logger.info("检测到显式知识库检索问题，返回 retrieval 路由建议")
                return {
                    "tool_name": None,
                    "tool_params": {},
                    "confidence": 0.98,
                    "reasoning": "问题明确要求查询知识库或文档内容，应优先走检索流程。",
                    "route_action": "retrieval",
                }

            # 过滤出“允许暴露给 Agent 且当前真实可用”的工具。
            agent_visible_tools = {
                tool_name
                for tool_name in self.tool_config.get_enabled_tool_names(expose_to_agent_only=True)
                if self.tool_registry.is_tool_available(tool_name)
            }

            # 如果上游额外限制了候选工具，则只在交集内选择。
            if available_tools is not None:
                tool_definitions = [
                    self.tool_registry.get_tool_definition(tool_name)
                    for tool_name in available_tools
                    if tool_name in agent_visible_tools
                ]
            else:
                tool_definitions = [
                    self.tool_registry.get_tool_definition(tool_name)
                    for tool_name in agent_visible_tools
                ]

            if not tool_definitions:
                return {
                    "tool_name": None,
                    "tool_params": {},
                    "confidence": 0.0,
                    "reasoning": "没有可用的工具。",
                }
            # Render tool descriptions with the standardized PromptTemplate path.
            prompt_template, prompt_variables = self._build_selection_prompt_template(
                user_question,
                tool_definitions,
                conversation_history or "",
            )

            selection_model = await self.model_manager.bind_tools(
                tool_definitions
            ).with_structured_output(
                ToolSelectionStructuredResult
            ).invoke_prompt_template(
                prompt_template,
                prompt_variables,
                temperature=0.3,
                max_tokens=500,
            )

            selection = selection_model.model_dump()

            # 二次校验，避免模型选择一个当前不可用的工具。
            if selection["tool_name"] and not self.tool_registry.is_tool_available(selection["tool_name"]):
                self.logger.warning("Selected tool '%s' is not available", selection["tool_name"])
                selection["tool_name"] = None
                selection["confidence"] = 0.0
                selection["reasoning"] = "选中的工具当前不可用。"

            return selection

        except Exception as error:
            self.logger.error("Tool selection failed: %s", str(error), exc_info=True)
            return {
                "tool_name": None,
                "tool_params": {},
                "confidence": 0.0,
                "reasoning": f"工具选择失败：{str(error)}",
            }

    def _is_explicit_retrieval_question(self, user_question: str) -> bool:
        """判断问题是否明显属于知识库检索场景。"""
        question = (user_question or "").lower()
        retrieval_keywords = [
            "知识库",
            "知识库里",
            "知识库中",
            "文档",
            "文档里",
            "文档中",
            "资料",
            "资料里",
            "资料中",
            "上传的文件",
            "库里",
            "库中",
            "内部文档",
        ]
        external_tool_keywords = [
            "联网",
            "互联网",
            "网页",
            "网站",
            "实时",
            "最新",
            "新闻",
            "搜索",
            "天气",
            "汇率",
            "翻译",
            "计算",
            "时间",
            "日期",
            "维基",
            "百科",
        ]

        has_retrieval_keyword = any(keyword in question for keyword in retrieval_keywords)
        has_external_tool_keyword = any(keyword in question for keyword in external_tool_keywords)
        return has_retrieval_keyword and not has_external_tool_keyword

    def _build_selection_prompt_template(
        self,
        user_question: str,
        tool_definitions: List[dict],
        conversation_history: str,
    ) -> Tuple[PromptTemplate, Dict[str, str]]:
        """Build tool-selection prompt text with the standard PromptTemplate path."""
        tools_text = ""
        for index, tool_def in enumerate(tool_definitions, start=1):
            tools_text += f"\n{index}. {tool_def['name']}\n"
            tools_text += f"   Description: {tool_def['description']}\n"
            tools_text += f"   Category: {tool_def['category']}\n"

            params = tool_def.get("parameters", {}).get("properties", {})
            required = tool_def.get("parameters", {}).get("required", [])
            if params:
                tools_text += "   Parameters:\n"
                for param_name, param_info in params.items():
                    required_mark = " (required)" if param_name in required else " (optional)"
                    tools_text += f"     - {param_name}{required_mark}: {param_info.get('description', '')}\n"

        prompt_key = "tool.tool_selection_prompt"
        raw_prompt = self.prompt_manager.get_prompt(prompt_key)
        if raw_prompt:
            return self.prompt_manager.get_prompt_template(prompt_key), {
                "user_input": user_question,
                "available_tools": tools_text,
                "conversation_history": conversation_history,
            }

        fallback_prompt = self._build_selection_prompt(user_question, tool_definitions)
        return PromptTemplate.from_template("{prompt_text}"), {"prompt_text": fallback_prompt}

    def _build_selection_prompt(self, user_question: str, tool_definitions: List[dict]) -> str:
        """构造默认工具选择提示词。"""
        tools_text = ""
        for index, tool_def in enumerate(tool_definitions, start=1):
            tools_text += f"\n{index}. {tool_def['name']}\n"
            tools_text += f"   描述：{tool_def['description']}\n"
            tools_text += f"   分类：{tool_def['category']}\n"

            params = tool_def.get("parameters", {}).get("properties", {})
            required = tool_def.get("parameters", {}).get("required", [])

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

请按照以下 JSON 格式返回结果：
```json
{{
    "tool_name": "工具名称（如果不需要工具则为 null）",
    "tool_params": {{
        "参数名": "参数值"
    }},
    "confidence": 0.9,
    "reasoning": "选择该工具的理由"
}}
```

注意：
1. 如果用户问题不需要使用任何工具，`tool_name` 应为 `null`
2. `tool_params` 必须包含所有必需参数
3. `confidence` 表示本次选择的置信度，范围为 0 到 1
4. `reasoning` 需简要说明为什么选择这个工具
"""
        return prompt

    def _parse_selection(self, response: str) -> Dict:
        """解析大模型返回的工具选择结果。"""
        try:
            import re

            json_match = re.search(r"```json\s*(.*?)\s*```", response, re.DOTALL)
            if json_match:
                json_str = json_match.group(1)
            else:
                json_match = re.search(r"\{.*\}", response, re.DOTALL)
                if json_match:
                    json_str = json_match.group(0)
                else:
                    json_str = response.strip()

            selection = json.loads(json_str)

            if "tool_name" not in selection:
                selection["tool_name"] = None
            if "tool_params" not in selection:
                selection["tool_params"] = {}
            if "confidence" not in selection:
                selection["confidence"] = 0.5
            if "reasoning" not in selection:
                selection["reasoning"] = "无推理说明。"

            return selection

        except json.JSONDecodeError as error:
            self.logger.error("工具选择 JSON 解析失败: %s", str(error))
            return {
                "tool_name": None,
                "tool_params": {},
                "confidence": 0.0,
                "reasoning": "无法解析工具选择结果。",
            }

    def get_available_tools(self) -> List[str]:
        """返回当前对 Agent 可见且可用的工具名称列表。"""
        return [
            tool_name
            for tool_name in self.tool_config.get_enabled_tool_names(expose_to_agent_only=True)
            if self.tool_registry.is_tool_available(tool_name)
        ]

    def get_tools_by_category(self, category: str) -> List[str]:
        """按分类返回工具名列表。"""
        tools = self.tool_registry.get_tools_by_category(category)
        return [tool.get_name() for tool in tools]
