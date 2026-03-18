
from __future__ import annotations

import json
from typing import Any, AsyncGenerator, Dict, Optional

from backend.agents.base.agent_input import AgentInput
from backend.agents.base.base_agent import BaseAgent
from backend.agents.base.stream_chunk import StreamChunk
from backend.core.config_manager import get_config_manager
from backend.core.llm_manager import get_langchain_model_manager
from backend.core.prompt_manager import get_prompt_manager
from backend.tools.tool_registry import get_tool


class CreativeWritingAgent(BaseAgent):
    def __init__(self):
        super().__init__(agent_name="creative_writing_agent", agent_type="generation")
        self.llm_manager = get_langchain_model_manager()
        self.config_manager = get_config_manager()
        self.prompt_manager = get_prompt_manager()
        self.logger.info("CreativeWritingAgent initialized")

    async def execute(self, agent_input: AgentInput, context: Optional[Dict[str, Any]] = None):
        request_context = context
        if request_context is None and isinstance(agent_input.metadata, dict):
            request_context = agent_input.metadata

        result = await self._execute(agent_input.content, request_context)
        if not result.get("success"):
            return self._create_output(content="", status="failed", error_message=result.get("error"))

        data = result.get("data", {})
        return self._create_output(
            content=data.get("response", ""),
            tool_result=data.get("tool_result"),
            tool_used=data.get("tool_used"),
            action=data.get("action"),
        )

    async def execute_stream(self, agent_input: AgentInput) -> AsyncGenerator[StreamChunk, None]:
        result = await self.execute(agent_input)
        if getattr(result, "status", None) == "failed":
            yield StreamChunk.create_error(result.error_message or "creative writing failed")
            return

        metadata = result.metadata or {}
        if metadata:
            yield StreamChunk.create_metadata(metadata)
        if result.content:
            yield StreamChunk.create_content(result.content)
        yield StreamChunk.create_result(result.content or "", **metadata)

    async def _execute(self, user_input: str, context: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        try:
            self.logger.info("Creative writing execution started")
            analysis = await self._analyze_request(user_input, context)
            tool_name = analysis.get("tool")
            action = analysis.get("action")
            parameters = analysis.get("parameters", {})

            tool = get_tool(tool_name)
            if not tool:
                return {"success": False, "error": f"未找到工具: {tool_name}"}

            result = await tool.safe_execute(action=action, **parameters)
            response = await self._generate_response(user_input, result)
            return {
                "success": True,
                "data": {
                    "response": response,
                    "tool_result": result,
                    "tool_used": tool_name,
                    "action": action,
                },
            }
        except Exception as error:
            self.logger.error("Creative writing execution failed: %s", error, exc_info=True)
            return {"success": False, "error": str(error)}

    async def _analyze_request(self, user_input: str, context: Optional[Dict[str, Any]]) -> Dict[str, Any]:
        tool_catalog = json.dumps(self.get_supported_tools(), ensure_ascii=False, indent=2)
        prompt_template = self.prompt_manager.get_prompt_template(
            "generation.creative_writing_request_analysis_prompt"
        )
        response = await self.llm_manager.invoke_prompt_template(
            prompt_template,
            {
                "user_input": user_input,
                "tool_catalog": tool_catalog,
            },
            temperature=0.3,
        )

        try:
            json_start = response.find('{')
            json_end = response.rfind('}') + 1
            if json_start >= 0 and json_end > json_start:
                return json.loads(response[json_start:json_end])
        except Exception as error:
            self.logger.warning("Failed to parse creative writing analysis: %s", error)

        return {"tool": "novel_generator", "action": "outline", "parameters": {}}

    async def _generate_response(self, user_input: str, tool_result: Dict[str, Any]) -> str:
        if not tool_result.get("success"):
            return f"工具执行失败：{tool_result.get('error', '未知错误')}"

        data = tool_result.get("data", {})
        prompt_template = self.prompt_manager.get_prompt_template(
            "generation.creative_writing_response_prompt"
        )
        response = await self.llm_manager.invoke_prompt_template(
            prompt_template,
            {
                "user_input": user_input,
                "tool_result_json": json.dumps(data, ensure_ascii=False, indent=2),
            },
            temperature=0.7,
        )
        return response.strip()

    def get_supported_tools(self) -> Dict[str, Dict[str, Any]]:
        return {
            "novel_generator": {
                "name": "小说生成器",
                "actions": ["outline", "chapter", "character", "worldview", "continue"],
                "description": "用于生成小说大纲、章节、角色与世界观等内容",
            },
            "script_generator": {
                "name": "剧本生成器",
                "actions": ["outline", "scene", "dialogue", "storyboard", "complete"],
                "description": "用于生成剧本大纲、场景、对白与分镜等内容",
            },
            "content_optimizer": {
                "name": "内容优化器",
                "actions": ["polish", "rewrite", "expand", "summarize", "style_transfer", "grammar_check", "seo_optimize"],
                "description": "用于润色、改写、扩写、总结等内容优化任务",
            },
        }
