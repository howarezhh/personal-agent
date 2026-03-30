# -*- coding: utf-8 -*-
"""工具选择器。

该模块负责根据用户问题、可见工具列表以及会话上下文，
调用大模型判断是否需要使用工具，以及应该选择哪个工具。
"""

import logging
from typing import Any, Dict, List, Optional, Tuple

from langchain_core.messages import AIMessage
from langchain_core.prompts import ChatPromptTemplate
from pydantic import BaseModel, Field

from backend.core.llm_manager import get_langchain_model_manager
from backend.core.prompt_manager import get_prompt_manager
from backend.tools.langchain_tool_adapter import LangChainToolAdapter
from backend.tools.tool_config import get_tool_config
from backend.tools.tool_initializer import ensure_tools_initialized
from backend.tools.tool_registry import get_tool_registry


class ToolSelectionStructuredResult(BaseModel):
    """Structured result for tool selection."""

    tool_name: Optional[str] = None
    tool_params: Dict[str, object] = Field(default_factory=dict)
    confidence: float = 0.0
    reasoning: str = ""


class ToolSelector:
    """负责选择最合适工具的组件。"""

    def __init__(self):
        self.logger = logging.getLogger(self.__class__.__name__)
        self.model_manager = get_langchain_model_manager()
        self.tool_registry = get_tool_registry()
        if self.tool_registry.get_tool_count() == 0:
            ensure_tools_initialized(strict=False)
            self.logger.info("工具注册表为空，已触发自动初始化")
        self.prompt_manager = get_prompt_manager()
        self.tool_config = get_tool_config()
        self.tool_adapter = LangChainToolAdapter()

    async def select_tool(
        self,
        user_question: str,
        available_tools: Optional[List[str]] = None,
        conversation_history: Optional[List[Dict[str, Any]]] = None,
        retrieval_context: str = "",
    ) -> Dict[str, Any]:
        """根据问题与上下文选择工具。"""
        try:
            agent_visible_tools = {
                tool_name
                for tool_name in self.tool_config.get_enabled_tool_names(expose_to_agent_only=True)
                if self.tool_registry.is_tool_available(tool_name)
            }

            if available_tools is not None:
                candidate_tool_names = [
                    tool_name
                    for tool_name in available_tools
                    if tool_name in agent_visible_tools
                ]
            else:
                candidate_tool_names = sorted(agent_visible_tools)

            tool_definitions = [
                self.tool_registry.get_tool_definition(tool_name)
                for tool_name in candidate_tool_names
            ]
            tool_instances = [
                self.tool_registry.get_tool(tool_name)
                for tool_name in candidate_tool_names
            ]
            tool_instances = [tool_instance for tool_instance in tool_instances if tool_instance is not None]

            if not tool_definitions:
                return {
                    "tool_name": None,
                    "tool_params": {},
                    "confidence": 0.0,
                    "reasoning": "没有可用的工具。",
                }

            prompt_template, prompt_variables = self._build_selection_prompt_call(
                user_question=user_question,
                tool_definitions=tool_definitions,
                conversation_history=conversation_history or [],
                retrieval_context=retrieval_context,
            )

            langchain_tools = self.tool_adapter.adapt_tools(tool_instances)
            ai_message = await self.model_manager.bind_tools(langchain_tools).invoke_chat_prompt_template(
                prompt_template,
                prompt_variables,
                temperature=0.3,
                max_tokens=500,
            )
            if not isinstance(ai_message, AIMessage):
                raise TypeError("工具选择链路必须返回 AIMessage")

            tool_calls = list(getattr(ai_message, "tool_calls", []) or [])
            if not tool_calls:
                return {
                    "tool_name": None,
                    "tool_params": {},
                    "confidence": 0.0,
                    "reasoning": str(getattr(ai_message, "content", "") or "模型判断无需调用工具。"),
                }

            if len(tool_calls) > 1:
                self.logger.warning("Tool selector received multiple tool calls, keeping the first one: total=%s", len(tool_calls))

            selected_call = tool_calls[0]
            selection = {
                "tool_name": str(selected_call.get("name") or "") or None,
                "tool_params": selected_call.get("args") if isinstance(selected_call.get("args"), dict) else {},
                "confidence": 1.0,
                "reasoning": str(getattr(ai_message, "content", "") or "模型通过标准 tool calling 选择了该工具。"),
            }

            if selection["tool_name"] and not self.tool_registry.is_tool_available(selection["tool_name"]):
                self.logger.warning("Selected tool %s is not available", selection["tool_name"])
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

    def _build_selection_prompt_call(
        self,
        user_question: str,
        tool_definitions: List[dict],
        conversation_history: List[Dict[str, Any]],
        retrieval_context: str,
    ) -> Tuple[ChatPromptTemplate, Dict[str, Any]]:
        """构造工具选择用的 ChatPromptTemplate 调用参数。"""
        tools_text = ""
        for index, tool_def in enumerate(tool_definitions, start=1):
            tools_text += f"\n{index}. {tool_def['name']}\n"
            tools_text += f"   Description: {tool_def.get('description', '')}\n"
            tools_text += f"   Category: {tool_def.get('category', 'unknown')}\n"

            schema = tool_def.get("input_schema") or tool_def.get("parameters") or {}
            params = schema.get("properties", {}) if isinstance(schema, dict) else {}
            required = schema.get("required", []) if isinstance(schema, dict) else []
            if params:
                tools_text += "   Parameters:\n"
                for param_name, param_info in params.items():
                    required_mark = " (required)" if param_name in required else " (optional)"
                    description = ""
                    if isinstance(param_info, dict):
                        description = str(param_info.get("description", ""))
                    tools_text += f"     - {param_name}{required_mark}: {description}\n"

        return self.prompt_manager.build_chat_prompt_call(
            user_prompt_key="tool.tool_selector_user_prompt",
            system_prompt_key="tool.tool_selector_system_prompt",
            user_variables={
                "user_input": user_question,
                "available_tools": tools_text,
                "retrieval_context": retrieval_context or "",
            },
            conversation_history=conversation_history,
        )

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
