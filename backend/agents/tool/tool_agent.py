# -*- coding: utf-8 -*-
"""Tool agent built on LangChain tools and LangGraph ToolNode."""

from __future__ import annotations

import hashlib
import json
import time
from typing import Annotated, Any, AsyncGenerator, Dict, List, Optional, TypedDict

from langchain_core.messages import AIMessage, BaseMessage, HumanMessage, SystemMessage, ToolMessage
from langchain_core.tools import StructuredTool
from langgraph.graph import END, START, StateGraph
from langgraph.graph.message import add_messages
from langgraph.prebuilt import ToolNode
from langgraph.prebuilt.tool_node import ToolCallRequest

from backend.agents.base.agent_input import AgentInput
from backend.agents.base.agent_output import AgentOutput
from backend.agents.base.base_agent import BaseAgent
from backend.agents.base.stream_chunk import StreamChunk
from backend.agents.tool.result_interpreter import ResultInterpreter
from backend.application.service_factory import build_tool_application_service
from backend.core.config_manager import get_config_manager
from backend.core.llm_manager import get_langchain_model_manager
from backend.tools.adapters.base_adapter import BaseToolAdapter
from backend.tools.langchain_tool_adapter import LangChainToolAdapter, LangChainToolExecutionContext
from backend.tools.tool_config import get_tool_config
from backend.tools.tool_initializer import ensure_tools_initialized
from backend.tools.tool_registry import get_tool_registry


class _ToolLoopState(TypedDict, total=False):
    messages: Annotated[List[BaseMessage], add_messages]
    llm_turns: int
    loop_error: Optional[str]


class ToolAgent(BaseAgent):
    """Execute explicit tools or a native LangGraph ToolNode loop."""

    def __init__(self):
        super().__init__(agent_name="tool_agent", agent_type="tool")

        self.result_interpreter = ResultInterpreter()
        self.tool_registry = get_tool_registry()
        if self.tool_registry.get_tool_count() == 0:
            ensure_tools_initialized(strict=False)

        self.tool_service = build_tool_application_service()
        self.tool_adapter = LangChainToolAdapter(self.tool_service)
        self.model_manager = get_langchain_model_manager()
        self.config_manager = get_config_manager()
        self.global_tool_config = get_tool_config()

        self.tool_config = self.config_manager.get_agent_config("tool_agent")
        self.tool_timeout = int(self.tool_config.get("tool_timeout", 30))
        self.max_retries = int(self.tool_config.get("max_retries", 2))
        self.retry_delay = float(self.tool_config.get("retry_delay", 1.0))
        self.max_tool_iterations = int(self.tool_config.get("max_tool_iterations", 5))

        self._performance_stats = {
            "total_calls": 0,
            "successful_calls": 0,
            "failed_calls": 0,
            "total_execution_time_ms": 0,
            "retry_count": 0,
        }

    @staticmethod
    def _safe_preview(value: Any, max_length: int = 120) -> str:
        text = str(value).replace("\n", "\\n")
        return text if len(text) <= max_length else f"{text[:max_length]}..."

    def _update_performance_stats(self, success: bool, execution_time_ms: int) -> None:
        self._performance_stats["total_calls"] += 1
        self._performance_stats["total_execution_time_ms"] += max(0, int(execution_time_ms))
        if success:
            self._performance_stats["successful_calls"] += 1
        else:
            self._performance_stats["failed_calls"] += 1

    def _build_execution_context(self, agent_input: AgentInput) -> LangChainToolExecutionContext:
        return LangChainToolExecutionContext(
            user_id=agent_input.user_id,
            conversation_id=agent_input.conversation_id,
            message_id=agent_input.message_id,
            is_admin=bool((agent_input.metadata or {}).get("is_admin", False)),
            metadata=dict(agent_input.metadata or {}),
        )

    def _resolve_available_tool_names(self, agent_input: AgentInput) -> List[str]:
        explicit_names = getattr(agent_input, "available_tools", None)
        if isinstance(explicit_names, list) and explicit_names:
            requested_names = [str(name) for name in explicit_names if name]
        else:
            requested_names = []
            enabled_names_getter = getattr(self.global_tool_config, "get_enabled_tool_names", None)
            if callable(enabled_names_getter):
                requested_names = [str(name) for name in enabled_names_getter(expose_to_agent_only=True) or []]
            if not requested_names and hasattr(self.tool_registry, "get_tool_names"):
                requested_names = [str(name) for name in self.tool_registry.get_tool_names()]

        is_exposed = getattr(self.global_tool_config, "is_tool_exposed_to_agent", None)
        normalized_names: List[str] = []
        for tool_name in requested_names:
            if not tool_name:
                continue
            if callable(is_exposed) and not is_exposed(tool_name):
                continue
            if hasattr(self.tool_registry, "is_tool_available") and not self.tool_registry.is_tool_available(tool_name):
                continue
            normalized_names.append(tool_name)
        return normalized_names

    def _resolve_available_tools(self, agent_input: AgentInput) -> List[BaseToolAdapter]:
        tools: List[BaseToolAdapter] = []
        for tool_name in self._resolve_available_tool_names(agent_input):
            tool = self.tool_registry.get_tool(tool_name)
            if tool is not None:
                tools.append(tool)
        return tools

    @staticmethod
    def _format_available_tools(tools: List[BaseToolAdapter]) -> str:
        lines: List[str] = []
        for tool in tools:
            definition = tool.get_definition()
            description = getattr(definition, "description", "") or ""
            lines.append(f"- {definition.name}: {description}")
        return "\n".join(lines)

    @staticmethod
    def _format_retrieval_context(agent_input: AgentInput) -> str:
        retrieval_results = getattr(agent_input, "retrieval_results", None)
        if not retrieval_results:
            return ""
        try:
            return json.dumps(retrieval_results, ensure_ascii=False)
        except TypeError:
            return str(retrieval_results)

    @staticmethod
    def _deserialize_history_message(message: Dict[str, Any]) -> BaseMessage:
        role = str(message.get("role") or "user")
        content = str(message.get("content") or "")
        if role == "system":
            return SystemMessage(content=content)
        if role == "assistant":
            raw_tool_calls = message.get("tool_calls") if isinstance(message.get("tool_calls"), list) else []
            normalized_tool_calls = []
            for tool_call in raw_tool_calls:
                if not isinstance(tool_call, dict):
                    continue
                normalized_tool_calls.append(
                    {
                        "id": tool_call.get("id"),
                        "type": "tool_call",
                        "name": tool_call.get("name"),
                        "args": tool_call.get("args") if isinstance(tool_call.get("args"), dict) else {},
                    }
                )
            if normalized_tool_calls:
                return AIMessage(content=content, tool_calls=normalized_tool_calls)
            return AIMessage(content=content)
        if role == "tool":
            return ToolMessage(
                content=content,
                tool_call_id=str(message.get("tool_call_id") or ""),
                name=str(message.get("name") or "") or None,
                status="error" if str(message.get("status") or "success") == "error" else "success",
            )
        return HumanMessage(content=content)

    def _build_langchain_messages(self, agent_input: AgentInput, tools: List[BaseToolAdapter]) -> List[BaseMessage]:
        """构建 ToolAgent 原生 tool calling 所需的 LangChain 消息。"""
        user_variables = {
            "question": agent_input.content,
            "user_input": agent_input.content,
            "available_tools": self._format_available_tools(tools),
            "retrieval_context": self._format_retrieval_context(agent_input),
        }
        conversation_history = list(agent_input.conversation_history or [])
        prompt_template, prompt_variables = self.prompt_manager.build_chat_prompt_call(
            user_prompt_key="tool.tool_agent_user_prompt",
            system_prompt_key="tool.tool_agent_system_prompt",
            user_variables=user_variables,
            conversation_history=conversation_history,
        )
        return list(prompt_template.format_messages(**prompt_variables))

    @staticmethod
    def _serialize_message_for_model(message: BaseMessage) -> Dict[str, Any]:
        if isinstance(message, SystemMessage):
            return {"role": "system", "content": str(message.content or "")}
        if isinstance(message, HumanMessage):
            return {"role": "user", "content": str(message.content or "")}
        if isinstance(message, ToolMessage):
            return {
                "role": "tool",
                "content": str(message.content or ""),
                "tool_call_id": getattr(message, "tool_call_id", None),
                "name": getattr(message, "name", None),
                "status": "error" if getattr(message, "status", "success") == "error" else "success",
            }
        tool_calls = []
        for tool_call in list(getattr(message, "tool_calls", None) or []):
            if not isinstance(tool_call, dict):
                continue
            tool_calls.append(
                {
                    "id": tool_call.get("id"),
                    "type": "tool_call",
                    "name": tool_call.get("name"),
                    "args": tool_call.get("args") if isinstance(tool_call.get("args"), dict) else {},
                }
            )
        payload: Dict[str, Any] = {"role": "assistant", "content": str(message.content or "")}
        if tool_calls:
            payload["tool_calls"] = tool_calls
        return payload

    def _skip_tool_result(self, reasoning: str) -> Dict[str, Any]:
        return {
            "skipped": True,
            "reasoning": reasoning,
        }

    @staticmethod
    def _normalize_tool_result_payload(value: Any, *, tool_name: str, tool_call_id: Optional[str]) -> Dict[str, Any]:
        if isinstance(value, dict):
            metadata = value.get("metadata") if isinstance(value.get("metadata"), dict) else {}
            metadata.setdefault("tool_name", tool_name)
            if tool_call_id and not metadata.get("tool_call_id"):
                metadata["tool_call_id"] = tool_call_id
            normalized = dict(value)
            normalized["metadata"] = metadata
            normalized.setdefault("success", metadata.get("status") != "error")
            return normalized
        return {
            "success": True,
            "data": value,
            "error": None,
            "error_code": None,
            "error_type": None,
            "metadata": {"tool_name": tool_name, "tool_call_id": tool_call_id},
        }

    async def _execute_structured_tool(
        self,
        *,
        structured_tool: StructuredTool,
        tool_name: str,
        tool_params: Dict[str, Any],
        tool_call_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        result = await structured_tool.ainvoke(tool_params)
        return self._normalize_tool_result_payload(result, tool_name=tool_name, tool_call_id=tool_call_id)

    def _build_tool_graph_config(self, agent_input: AgentInput) -> Dict[str, Any]:
        stable_request_id = agent_input.get_execution_id() or agent_input.get_request_id()
        if stable_request_id:
            thread_id = str(stable_request_id)
        else:
            fallback_basis = "|".join(
                [
                    str(agent_input.conversation_id or ""),
                    str(agent_input.message_id or ""),
                    str(agent_input.content or ""),
                ]
            )
            digest = hashlib.sha1(fallback_basis.encode("utf-8")).hexdigest()[:16]
            thread_id = f"{agent_input.conversation_id}:{agent_input.message_id or 'message'}:{digest}:{time.time_ns()}"
        return {
            "configurable": {
                "thread_id": f"tool_agent:{thread_id}",
                "checkpoint_ns": "tool_agent",
            }
        }

    async def _invoke_tool_calling_model(
        self,
        messages: List[BaseMessage],
        structured_tools: List[StructuredTool],
    ) -> AIMessage:
        bound_model = self.model_manager.bind_tools(structured_tools)

        if hasattr(bound_model, "invoke_messages"):
            ai_message = await bound_model.invoke_messages(
                messages=[self._serialize_message_for_model(message) for message in messages],
                temperature=0.3,
                max_tokens=500,
            )
        elif hasattr(bound_model, "ainvoke"):
            ai_message = await bound_model.ainvoke(messages)
        else:
            raise TypeError("Bound tool-calling model does not support invoke_messages or ainvoke")

        if not isinstance(ai_message, AIMessage):
            raise TypeError("Tool-calling model must return AIMessage")
        return ai_message

    async def _awrap_tool_call_with_events(self, request: ToolCallRequest, execute):
        tool_name = str(request.tool_call.get("name") or "")
        tool_call_id = request.tool_call.get("id")
        tool_args = request.tool_call.get("args") if isinstance(request.tool_call.get("args"), dict) else {}
        stream_writer = getattr(request.runtime, "stream_writer", None)
        writer = stream_writer if callable(stream_writer) else (lambda *_args, **_kwargs: None)

        writer(
            StreamChunk.create_tool_call(
                tool_name=tool_name,
                tool_input=tool_args,
                status="starting",
                tool_call_id=tool_call_id,
            )
        )

        try:
            result = await execute(request)
        except Exception as error:
            writer(
                StreamChunk.create_tool_call(
                    tool_name=tool_name,
                    tool_input=tool_args,
                    status="failed",
                    tool_call_id=tool_call_id,
                    error_message=str(error),
                )
            )
            raise

        tool_result = self._normalize_tool_result_payload(
            self._parse_tool_message_content(getattr(result, "content", "")),
            tool_name=tool_name,
            tool_call_id=tool_call_id,
        )
        tool_success = bool(tool_result.get("success", False))
        writer(
            StreamChunk.create_tool_call(
                tool_name=tool_name,
                tool_input=tool_args,
                tool_result=tool_result,
                status="completed" if tool_success else "failed",
                tool_call_id=tool_call_id,
                error_message=None if tool_success else str(tool_result.get("error") or "tool execution failed"),
                error_code=None if tool_success else tool_result.get("error_code"),
            )
        )
        return result

    def _build_tool_loop_graph(self, structured_tools: List[StructuredTool], *, max_tool_iterations: int):
        async def agent_node(state: _ToolLoopState) -> Dict[str, Any]:
            messages = list(state.get("messages", []))
            llm_turns = int(state.get("llm_turns", 0)) + 1
            ai_message = await self._invoke_tool_calling_model(messages, structured_tools)
            return {"messages": [ai_message], "llm_turns": llm_turns}

        def route_after_agent(state: _ToolLoopState):
            messages = list(state.get("messages", []))
            final_ai_message = next(
                (message for message in reversed(messages) if isinstance(message, AIMessage)),
                None,
            )
            if final_ai_message is None or not list(getattr(final_ai_message, "tool_calls", None) or []):
                return END
            if int(state.get("llm_turns", 0)) >= max_tool_iterations:
                return "loop_exhausted"
            return "tools"

        def loop_exhausted_node(_state: _ToolLoopState) -> Dict[str, Any]:
            return {"loop_error": f"Exceeded max tool iterations ({max_tool_iterations})"}

        graph = StateGraph(_ToolLoopState)
        graph.add_node("agent", agent_node)
        graph.add_node(
            "tools",
            ToolNode(
                structured_tools,
                awrap_tool_call=self._awrap_tool_call_with_events,
            ),
        )
        graph.add_node("loop_exhausted", loop_exhausted_node)
        graph.add_edge(START, "agent")
        graph.add_conditional_edges("agent", route_after_agent, ["tools", "loop_exhausted", END])
        graph.add_edge("tools", "agent")
        graph.add_edge("loop_exhausted", END)
        return graph.compile()

    @staticmethod
    def _parse_tool_message_content(content: Any) -> Any:
        if isinstance(content, list):
            text = "".join(str(item.get("text", item)) if isinstance(item, dict) else str(item) for item in content)
        else:
            text = str(content or "")
        try:
            return json.loads(text)
        except Exception:
            return text

    def _collect_executed_tools_from_messages(self, messages: List[BaseMessage]) -> List[Dict[str, Any]]:
        executed_tools: List[Dict[str, Any]] = []
        tool_calls_by_id: Dict[str, Dict[str, Any]] = {}

        for message in messages:
            if isinstance(message, AIMessage):
                for tool_call in list(getattr(message, "tool_calls", None) or []):
                    if not isinstance(tool_call, dict):
                        continue
                    entry = {
                        "tool_name": str(tool_call.get("name") or ""),
                        "tool_params": tool_call.get("args") if isinstance(tool_call.get("args"), dict) else {},
                        "tool_call_id": tool_call.get("id"),
                        "tool_result": None,
                    }
                    executed_tools.append(entry)
                    if entry["tool_call_id"]:
                        tool_calls_by_id[str(entry["tool_call_id"])] = entry
                continue

            if not isinstance(message, ToolMessage):
                continue

            tool_call_id = str(getattr(message, "tool_call_id", "") or "")
            target = tool_calls_by_id.get(tool_call_id)
            if target is None:
                target = {
                    "tool_name": str(getattr(message, "name", "") or ""),
                    "tool_params": {},
                    "tool_call_id": tool_call_id or None,
                    "tool_result": None,
                }
                executed_tools.append(target)
                if tool_call_id:
                    tool_calls_by_id[tool_call_id] = target

            parsed_content = self._parse_tool_message_content(message.content)
            tool_result = self._normalize_tool_result_payload(
                parsed_content,
                tool_name=target["tool_name"],
                tool_call_id=target["tool_call_id"],
            )
            if getattr(message, "status", "success") == "error":
                tool_result["success"] = False
                tool_result.setdefault("error", str(parsed_content))
            target["tool_result"] = tool_result

        return [item for item in executed_tools if item.get("tool_result") is not None]

    def _build_tool_loop_summary(
        self,
        executed_tools: List[Dict[str, Any]],
        final_ai_message: Optional[AIMessage],
    ) -> Dict[str, Any]:
        deduped_tools: List[Dict[str, Any]] = []
        seen_keys: set[str] = set()
        for item in executed_tools:
            dedupe_key = str(item.get("tool_call_id") or json.dumps([item.get("tool_name"), item.get("tool_params")], ensure_ascii=False, sort_keys=True))
            if dedupe_key in seen_keys:
                continue
            seen_keys.add(dedupe_key)
            deduped_tools.append(item)

        executed_tools = deduped_tools
        last_tool = executed_tools[-1]
        tool_calls = [
            {
                "tool_name": item.get("tool_name"),
                "tool_params": item.get("tool_params") or {},
                "tool_call_id": item.get("tool_call_id"),
            }
            for item in executed_tools
        ]
        tool_results = [
            {
                "tool_name": item.get("tool_name"),
                "tool_params": item.get("tool_params") or {},
                "tool_call_id": item.get("tool_call_id"),
                "tool_result": item.get("tool_result") or {},
            }
            for item in executed_tools
        ]

        last_tool_result = dict(last_tool.get("tool_result") or {})
        last_tool_data = last_tool_result.get("data")
        last_tool_result["data"] = {
            "latest_tool_result": last_tool_data,
            "tool_results": tool_results,
            "final_response": str(getattr(final_ai_message, "content", "") or "") if final_ai_message else "",
        }

        interpreted_text_parts = []
        for item in executed_tools:
            interpreted = self.result_interpreter.interpret(item["tool_name"], item["tool_result"])
            formatted_text = str(interpreted.get("formatted_text") or "")
            if formatted_text:
                interpreted_text_parts.append(formatted_text)
        final_response = str(getattr(final_ai_message, "content", "") or "") if final_ai_message else ""
        combined_interpretation = "\n\n".join(interpreted_text_parts + ([final_response] if final_response else []))

        return {
            "tool_name": last_tool.get("tool_name"),
            "tool_params": last_tool.get("tool_params") or {},
            "tool_call_id": last_tool.get("tool_call_id"),
            "tool_calls": tool_calls,
            "tool_results": tool_results,
            "tool_result": last_tool_result,
            "interpreted_result": {
                "formatted_text": combined_interpretation,
                "final_response": final_response,
            },
            "llm_message": final_ai_message,
            "llm_final_response": final_response,
        }

    async def _execute_explicit_tool(
        self,
        *,
        tool_name: str,
        tool_params: Dict[str, Any],
        agent_input: AgentInput,
    ) -> Dict[str, Any]:
        if not self.tool_registry.is_tool_available(tool_name):
            raise ValueError(f"Tool not available: {tool_name}")

        tool = self.tool_registry.get_tool(tool_name)
        if tool is None:
            raise ValueError(f"Tool not found: {tool_name}")

        structured_tool = self.tool_adapter.adapt_tool(
            tool,
            execution_context=self._build_execution_context(agent_input),
        )
        tool_result = await self._execute_structured_tool(
            structured_tool=structured_tool,
            tool_name=tool_name,
            tool_params=tool_params,
            tool_call_id=None,
        )
        interpreted_result = self.result_interpreter.interpret(tool_name, tool_result)
        metadata = tool_result.get("metadata") if isinstance(tool_result.get("metadata"), dict) else {}
        return {
            "tool_name": tool_name,
            "tool_params": tool_params,
            "tool_call_id": metadata.get("tool_call_id"),
            "tool_calls": [{"tool_name": tool_name, "tool_params": tool_params, "tool_call_id": metadata.get("tool_call_id")}],
            "tool_results": [{"tool_name": tool_name, "tool_params": tool_params, "tool_call_id": metadata.get("tool_call_id"), "tool_result": tool_result}],
            "tool_result": tool_result,
            "interpreted_result": interpreted_result,
            "llm_message": None,
            "llm_final_response": interpreted_result.get("formatted_text", ""),
        }

    def _prepare_native_tool_graph(self, agent_input: AgentInput):
        tools = self._resolve_available_tools(agent_input)
        if not tools:
            return None, None

        execution_context = self._build_execution_context(agent_input)
        structured_tools = self.tool_adapter.adapt_tools(tools, execution_context=execution_context)
        initial_messages = self._build_langchain_messages(agent_input, tools)
        compiled_graph = self._build_tool_loop_graph(
            structured_tools,
            max_tool_iterations=self.max_tool_iterations,
        )
        return compiled_graph, {"messages": initial_messages, "llm_turns": 0}

    async def _execute_native_bound_tools(self, agent_input: AgentInput) -> Dict[str, Any]:
        compiled_graph, graph_state = self._prepare_native_tool_graph(agent_input)
        if compiled_graph is None or graph_state is None:
            return self._skip_tool_result("当前请求范围内没有可用工具。")

        final_state = await compiled_graph.ainvoke(
            graph_state,
            config=self._build_tool_graph_config(agent_input),
        )
        if (final_state or {}).get("loop_error"):
            raise RuntimeError(str(final_state["loop_error"]))

        final_messages = list((final_state or {}).get("messages", []))
        final_ai_message = next(
            (message for message in reversed(final_messages) if isinstance(message, AIMessage)),
            None,
        )
        executed_tools = self._collect_executed_tools_from_messages(final_messages)
        if not executed_tools:
            return self._skip_tool_result(
                str(getattr(final_ai_message, "content", "") or "当前问题无需调用工具。")
            )
        return self._build_tool_loop_summary(executed_tools, final_ai_message)

    async def execute(self, agent_input: AgentInput) -> AgentOutput:
        start_time = time.time()
        try:
            explicit_tool_name = getattr(agent_input, "tool_name", None)
            explicit_tool_params = getattr(agent_input, "tool_params", None) or {}

            if explicit_tool_name:
                execution_payload = await self._execute_explicit_tool(
                    tool_name=explicit_tool_name,
                    tool_params=explicit_tool_params,
                    agent_input=agent_input,
                )
            else:
                execution_payload = await self._execute_native_bound_tools(agent_input)

            if execution_payload.get("skipped"):
                return self._create_output(
                    content="当前问题无需调用工具。",
                    status="success",
                    reasoning=execution_payload.get("reasoning", ""),
                )

            tool_name = execution_payload["tool_name"]
            tool_params = execution_payload.get("tool_params", {})
            tool_result = execution_payload["tool_result"]
            execution_time_ms = int((time.time() - start_time) * 1000)
            self._update_performance_stats(bool(tool_result.get("success", False)), execution_time_ms)
            interpreted_result = execution_payload.get("interpreted_result") or self.result_interpreter.interpret(tool_name, tool_result)
            metadata = tool_result.get("metadata") if isinstance(tool_result.get("metadata"), dict) else {}

            return self._create_output(
                content=str(interpreted_result.get("formatted_text", "")),
                status="success" if tool_result.get("success") else "failed",
                execution_id=metadata.get("execution_id"),
                tool_name=tool_name,
                tool_params=tool_params,
                tool_result=tool_result,
                interpreted_result=interpreted_result,
                tool_calls=execution_payload.get("tool_calls", []),
                tool_call_id=metadata.get("tool_call_id") or execution_payload.get("tool_call_id"),
                reasoning=execution_payload.get("llm_final_response"),
                execution_time_ms=execution_time_ms,
                llm_tool_call=execution_payload.get("llm_message"),
            )
        except Exception as error:
            execution_time_ms = int((time.time() - start_time) * 1000)
            self.logger.error("Tool agent execution failed: %s", str(error), exc_info=True)
            return self._create_error_output(error=error, execution_time_ms=execution_time_ms)

    async def execute_stream(self, agent_input: AgentInput) -> AsyncGenerator[StreamChunk, None]:
        start_time = time.time()
        try:
            explicit_tool_name = getattr(agent_input, "tool_name", None)
            explicit_tool_params = getattr(agent_input, "tool_params", None) or {}

            if explicit_tool_name:
                execution_payload = await self._execute_explicit_tool(
                    tool_name=explicit_tool_name,
                    tool_params=explicit_tool_params,
                    agent_input=agent_input,
                )
            else:
                compiled_graph, graph_state = self._prepare_native_tool_graph(agent_input)
                if compiled_graph is None or graph_state is None:
                    execution_payload = self._skip_tool_result("当前请求范围内没有可用工具。")
                else:
                    final_state = None
                    async for stream_mode, payload in compiled_graph.astream(
                        graph_state,
                        config=self._build_tool_graph_config(agent_input),
                        stream_mode=["custom", "values"],
                    ):
                        if stream_mode == "custom" and isinstance(payload, StreamChunk):
                            yield payload
                            continue
                        if stream_mode == "values" and isinstance(payload, dict):
                            final_state = payload

                    if (final_state or {}).get("loop_error"):
                        raise RuntimeError(str(final_state["loop_error"]))

                    final_messages = list((final_state or {}).get("messages", []))
                    final_ai_message = next(
                        (message for message in reversed(final_messages) if isinstance(message, AIMessage)),
                        None,
                    )
                    executed_tools = self._collect_executed_tools_from_messages(final_messages)
                    if not executed_tools:
                        execution_payload = self._skip_tool_result(
                            str(getattr(final_ai_message, "content", "") or "当前问题无需调用工具。")
                        )
                    else:
                        execution_payload = self._build_tool_loop_summary(executed_tools, final_ai_message)

            if execution_payload.get("skipped"):
                yield StreamChunk.create_result(execution_payload)
                return

            tool_name = execution_payload["tool_name"]
            tool_params = execution_payload.get("tool_params", {})
            tool_result = execution_payload["tool_result"]
            execution_time_ms = int((time.time() - start_time) * 1000)
            self._update_performance_stats(bool(tool_result.get("success", False)), execution_time_ms)

            interpreted_result = execution_payload.get("interpreted_result") or self.result_interpreter.interpret(tool_name, tool_result)
            yield StreamChunk.create_result(
                {
                    "tool_name": tool_name,
                    "tool_params": tool_params,
                    "tool_result": tool_result,
                    "tool_call_id": execution_payload.get("tool_call_id"),
                    "tool_calls": execution_payload.get("tool_calls", []),
                    "interpreted_result": interpreted_result,
                    "reasoning": execution_payload.get("llm_final_response"),
                    "execution_time_ms": execution_time_ms,
                }
            )
        except Exception as error:
            self.logger.error("Tool agent streaming failed: %s", str(error), exc_info=True)
            yield StreamChunk.create_error(str(error))
