from __future__ import annotations

import importlib
import sys
import types
from typing import AsyncGenerator

import pytest

from backend.agents.base.agent_input import AgentInput, WorkflowContext
from backend.agents.base.stream_chunk import StreamChunk
from backend.utils.logger import get_logger
from backend.workflows.multi_agent_workflow import get_workflow_template
from backend.workflows import workflow_executor as workflow_executor_module
from backend.workflows.workflow_executor import WorkflowExecutor


def test_decision_maker_emits_multi_agent_template_for_complex_request(monkeypatch):
    fake_config_module = types.ModuleType("backend.core.config_manager")
    fake_config_module.ConfigManager = object
    fake_config_module.get_config_manager = lambda: None
    monkeypatch.setitem(sys.modules, "backend.core.config_manager", fake_config_module)

    decision_maker_module = importlib.import_module("backend.agents.router.decision_maker")
    DecisionMaker = decision_maker_module.DecisionMaker

    class _Registry:
        @staticmethod
        def get_tool_count():
            return 1

        @staticmethod
        def get_all_tools():
            return {}

    monkeypatch.setattr(decision_maker_module, "ensure_tools_initialized", lambda strict=False: {"initialized": True})
    monkeypatch.setattr(decision_maker_module, "get_tool_registry", lambda: _Registry())

    decision_maker = DecisionMaker()
    decision_maker._match_tools = lambda _question: {
        "matched_tools": [{"name": "web_search", "score": 3, "category": "search", "description": "联网搜索"}],
        "has_matches": True,
        "best_match": {"name": "web_search", "score": 3, "category": "search", "description": "联网搜索"},
    }

    decision = decision_maker.analyze_question(
        "请结合知识库文档和最新新闻，先检索内部资料，再联网搜索并汇总结论",
        conversation_history=[],
    )

    assert decision["action"] in {"multi_agent", "tool_call"}
    if decision["action"] == "multi_agent":
        assert decision["workflow_template"] in {"retrieval_then_tool", "tool_then_retrieval"}
    assert "web_search" in decision["suggested_tools"]


def test_augment_chunk_sanitizes_error_content():
    executor = WorkflowExecutor.__new__(WorkflowExecutor)
    agent_input = AgentInput(user_id="u1", conversation_id="c1", content="hello", message_id="m1", metadata={})
    chunk = StreamChunk.create_error("token=abc123 password=secret Bearer xyz")

    augmented = executor._augment_chunk(chunk, agent_input)

    assert augmented.chunk_type == "error"
    assert "abc123" not in str(augmented.content)
    assert "secret" not in str(augmented.content)
    assert "[REDACTED]" in str(augmented.content)


async def test_tool_error_falls_back_to_generation():
    class FakeToolAgent:
        async def execute_stream(self, _agent_input: AgentInput) -> AsyncGenerator[StreamChunk, None]:
            yield StreamChunk.create_error("token=abc123")

    class FakeGenerationAgent:
        async def execute_stream(self, _agent_input: AgentInput) -> AsyncGenerator[StreamChunk, None]:
            yield StreamChunk.create_content("fallback answer")
            yield StreamChunk.create_result({"ok": True})

    executor = WorkflowExecutor.__new__(WorkflowExecutor)
    executor.logger = get_logger("test_workflow_executor")
    executor.tool_agent = FakeToolAgent()
    executor.generation_agent = FakeGenerationAgent()

    agent_input = AgentInput(user_id="u1", conversation_id="c1", content="hello", message_id="m1", metadata={})
    chunks = [chunk async for chunk in executor._execute_tool_call_workflow(agent_input)]

    assert chunks[0].chunk_type == "thinking"
    assert "工具调用失败" in str(chunks[0].content)
    assert "abc123" not in str(chunks[0].content)
    assert [chunk.chunk_type for chunk in chunks[1:]] == ["content", "result"]


def test_retrieval_then_tool_template_passes_previous_output():
    workflow_template = get_workflow_template("retrieval_then_tool")

    assert workflow_template is not None
    assert workflow_template["steps"][1]["config"]["use_previous_output"] is True



def test_get_conversation_history_prefers_explicit_empty_list():
    agent_input = AgentInput(
        user_id="u1",
        conversation_id="c1",
        message_id="m1",
        content="hello",
        conversation_history=[],
        metadata={"conversation_history": [{"role": "user", "content": "stale"}]},
    )

    assert WorkflowExecutor._get_conversation_history(agent_input) == []


def test_augment_chunk_injects_execution_id_and_corrects_trace_fields():
    executor = WorkflowExecutor.__new__(WorkflowExecutor)
    agent_input = AgentInput(
        user_id="u1",
        conversation_id="c1",
        message_id="m1",
        content="hello",
        metadata={"request_id": "req-1", "execution_id": "stale-exec"},
    )
    chunk = StreamChunk.create_result(
        {"execution_id": "exec-1", "status": "ok"},
        conversation_id="wrong-conv",
        request_id="wrong-req",
    )

    augmented = executor._augment_chunk(chunk, agent_input)

    assert augmented.metadata["execution_id"] == "exec-1"
    assert augmented.metadata["conversation_id"] == "c1"
    assert augmented.metadata["request_id"] == "req-1"


def test_clone_agent_input_preserves_workflow_context():
    executor = WorkflowExecutor.__new__(WorkflowExecutor)
    agent_input = AgentInput(
        user_id="u1",
        conversation_id="c1",
        message_id="m1",
        content="hello",
        metadata={"request_id": "req-1"},
        workflow_context=WorkflowContext(
            step_results={"retrieve": {"success": True}},
            step_config={"use_previous_output": True},
            previous_output={"step_key": "retrieve"},
        ),
    )

    cloned = executor._clone_agent_input(agent_input)

    assert isinstance(cloned.workflow_context, WorkflowContext)
    assert cloned.workflow_context is not agent_input.workflow_context
    assert cloned.workflow_context.step_results == {"retrieve": {"success": True}}
    assert cloned.workflow_context.step_config == {"use_previous_output": True}
    assert cloned.workflow_context.previous_output == {"step_key": "retrieve"}


def test_workflow_executor_requires_registered_agents(monkeypatch):
    class _Registry:
        def create(self, agent_type: str):
            if agent_type == "router":
                return None
            return object()

    monkeypatch.setattr(workflow_executor_module, "_get_agent_registry", lambda: _Registry())

    with pytest.raises(RuntimeError, match="router"):
        WorkflowExecutor()


def test_resolve_multi_agent_workflow_config_returns_none_for_invalid_config():
    executor = WorkflowExecutor.__new__(WorkflowExecutor)
    executor.logger = get_logger("test_workflow_executor_invalid_config")
    executor.multi_agent_workflow = workflow_executor_module.MultiAgentWorkflow()

    agent_input = AgentInput(
        user_id="u1",
        conversation_id="c1",
        message_id="m1",
        content="hello",
        metadata={},
    )

    workflow_config, note = executor._resolve_multi_agent_workflow_config(
        agent_input,
        {"workflow_config": {"steps": []}},
    )

    assert workflow_config is None
    assert note == "invalid_workflow_config"


def test_resolve_multi_agent_workflow_config_uses_template_without_default_fallback(monkeypatch):
    executor = WorkflowExecutor.__new__(WorkflowExecutor)
    executor.logger = get_logger("test_workflow_executor_template_config")
    executor.multi_agent_workflow = workflow_executor_module.MultiAgentWorkflow()

    class _Registry:
        @staticmethod
        def registered_types() -> list[str]:
            return ["router", "retrieval", "generation", "tool"]

    monkeypatch.setattr("backend.workflows.multi_agent_workflow._get_agent_registry", lambda: _Registry())

    agent_input = AgentInput(
        user_id="u1",
        conversation_id="c1",
        message_id="m1",
        content="hello",
        metadata={},
    )

    workflow_config, note = executor._resolve_multi_agent_workflow_config(
        agent_input,
        {"workflow_template": "retrieval_then_tool"},
    )

    assert workflow_config is not None
    assert workflow_config["steps"][0]["agent_type"] == "retrieval"
    assert note == "workflow_template:retrieval_then_tool"
