# -*- coding: utf-8 -*-
"""Minimal router agent implementation."""

from __future__ import annotations

import re
import time
from typing import Any, AsyncGenerator

from backend.agents.base.agent_input import AgentInput
from backend.agents.base.agent_output import AgentOutput
from backend.agents.base.base_agent import BaseAgent
from backend.agents.base.stream_chunk import StreamChunk


class RouterAgent(BaseAgent):
    """Rule-based router for tool / retrieval / generation flows."""

    _TOOL_KEYWORDS = (
        "计算",
        "算",
        "天气",
        "搜索",
        "查询",
        "调用工具",
        "tool",
        "calculate",
        "search",
        "weather",
    )
    _INFO_REQUEST_PATTERN = re.compile(
        r"什么|怎么|如何|为何|为什么|多少|是否|能否|请帮我|介绍|说明|总结|概括|分析|对比|列出|告诉我|解读|梳理|依据|根据"
    )
    _INFO_CUE_KEYWORDS = (
        "要求",
        "字数",
        "规定",
        "标准",
        "条件",
        "流程",
        "办法",
        "规范",
        "格式",
        "模板",
        "示例",
        "材料",
        "时间",
        "节点",
        "比例",
        "评分",
        "评审",
        "抽检",
        "存档",
        "提交",
    )

    def __init__(self) -> None:
        super().__init__(agent_name="router_agent", agent_type="router")

    async def execute(self, agent_input: AgentInput) -> AgentOutput:
        start_time = time.perf_counter()
        try:
            route_payload = self._resolve_route(agent_input)
            execution_time_ms = int((time.perf_counter() - start_time) * 1000)
            return self._create_output(
                content=route_payload["route_action"],
                status="success",
                execution_time_ms=execution_time_ms,
                execution_id=agent_input.get_execution_id(),
                request_id=agent_input.get_request_id(),
                conversation_id=agent_input.conversation_id,
                message_id=agent_input.message_id,
                **route_payload,
            )
        except Exception as error:
            execution_time_ms = int((time.perf_counter() - start_time) * 1000)
            return self._create_error_output(
                error=error,
                fallback="router execution failed",
                execution_time_ms=execution_time_ms,
                execution_id=agent_input.get_execution_id(),
                request_id=agent_input.get_request_id(),
                conversation_id=agent_input.conversation_id,
                message_id=agent_input.message_id,
            )

    async def execute_stream(self, agent_input: AgentInput) -> AsyncGenerator[StreamChunk, None]:
        try:
            route_payload = self._resolve_route(agent_input)
            yield StreamChunk.create_thinking(
                f"开始判定路由：{route_payload['route_action']}",
                route_action=route_payload["route_action"],
                route_reason=route_payload["route_reason"],
            )
            yield StreamChunk.create_done(route_payload, route_action=route_payload["route_action"])
        except Exception as error:
            yield self._create_error_chunk(error=error, fallback="router execution failed")

    def _resolve_route(self, agent_input: AgentInput) -> dict[str, Any]:
        normalized_text = self._normalize_text(agent_input.content)
        metadata = dict(agent_input.metadata or {})

        preferred_route = metadata.get("preferred_route")
        if isinstance(preferred_route, str) and preferred_route.strip():
            normalized_route = preferred_route.strip().lower()
            if normalized_route in {"retrieval", "tool", "generation"}:
                return {
                    "route_action": normalized_route,
                    "route_reason": "metadata_preferred_route",
                    "knowledge_base_enabled": agent_input.is_knowledge_enabled(default=False),
                }

        if self._looks_like_tool_request(normalized_text):
            return {
                "route_action": "tool",
                "route_reason": "tool_keyword_matched",
                "knowledge_base_enabled": agent_input.is_knowledge_enabled(default=False),
            }

        if agent_input.is_knowledge_enabled(default=False) and self._looks_like_information_request(normalized_text):
            return {
                "route_action": "retrieval",
                "route_reason": "knowledge_request_detected",
                "knowledge_base_enabled": True,
                "knowledge_base_id": agent_input.get_knowledge_base_id(),
            }

        return {
            "route_action": "generation",
            "route_reason": "default_generation_route",
            "knowledge_base_enabled": agent_input.is_knowledge_enabled(default=False),
        }

    @classmethod
    def _looks_like_tool_request(cls, normalized_text: str) -> bool:
        if not normalized_text:
            return False
        lowered_text = normalized_text.lower()
        return any(keyword in lowered_text for keyword in cls._TOOL_KEYWORDS)

    @classmethod
    def _looks_like_information_request(cls, normalized_text: str) -> bool:
        if not normalized_text:
            return False
        if cls._INFO_REQUEST_PATTERN.search(normalized_text):
            return True
        if "?" in normalized_text or "？" in normalized_text:
            return True
        return any(keyword in normalized_text for keyword in cls._INFO_CUE_KEYWORDS)

    @staticmethod
    def _normalize_text(value: Any) -> str:
        return re.sub(r"\s+", " ", str(value or "")).strip()
