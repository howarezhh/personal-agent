from __future__ import annotations

from backend.agents.base.agent_input import AgentInput
from backend.agents.base.stream_chunk import StreamChunk
from backend.workflows.multi_agent_workflow import MultiAgentWorkflow, get_workflow_template
from backend.workflows.state_graph import WorkflowState


class _FakeRegistry:
    def __init__(self, agents: dict[str, object]):
        self._agents = agents

    def create(self, agent_type: str):
        return self._agents.get(agent_type)

    def registered_types(self) -> list[str]:
        return sorted(self._agents.keys())


class _FakeRouterAgent:
    async def execute_stream(self, _agent_input: AgentInput):
        yield StreamChunk.create_result({"route_decision": {"action": "retrieval"}})


class _FakeRetrievalAgent:
    async def execute_stream(self, _agent_input: AgentInput):
        yield StreamChunk.create_content("检索命中")
        yield StreamChunk.create_result({"retrieval_results": [{"document_id": "doc-1"}], "content": "检索命中"})


class _FakeGenerationAgent:
    async def execute_stream(self, _agent_input: AgentInput):
        yield StreamChunk.create_content("最终回答")
        yield StreamChunk.create_result({"final_content": "最终回答"})


async def test_multi_agent_workflow_executes_via_langgraph(monkeypatch):
    fake_registry = _FakeRegistry(
        {
            "router": _FakeRouterAgent(),
            "retrieval": _FakeRetrievalAgent(),
            "generation": _FakeGenerationAgent(),
        }
    )
    monkeypatch.setattr("backend.workflows.multi_agent_workflow._get_agent_registry", lambda: fake_registry)

    workflow = MultiAgentWorkflow()
    agent_input = AgentInput(
        user_id="u1",
        conversation_id="c1",
        message_id="m1",
        content="请先判断是否要检索，再回答",
        metadata={},
    )
    workflow_config = get_workflow_template("conditional_retrieval")

    chunks = [chunk async for chunk in workflow.execute(agent_input, workflow_config)]

    assert workflow.get_current_state() == WorkflowState.COMPLETED
    assert all(chunk.chunk_type != "error" for chunk in chunks)
    assert any(chunk.chunk_type == "result" and (chunk.metadata or {}).get("result_scope") == "workflow" for chunk in chunks)

    step_names = {(chunk.metadata or {}).get("step_name") for chunk in chunks if chunk.metadata}
    assert "路由分析" in step_names
    assert "检索知识" in step_names
    assert "生成回答" in step_names


def test_multi_agent_workflow_legacy_entrypoints_removed():
    assert not hasattr(MultiAgentWorkflow, "execute_sequential")
    assert not hasattr(MultiAgentWorkflow, "execute_parallel")
