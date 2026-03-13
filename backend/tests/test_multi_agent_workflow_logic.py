import json
from types import SimpleNamespace

import pytest

from backend.api import chat
from backend.agents.base.agent_input import AgentInput
from backend.agents.base.stream_chunk import StreamChunk
from backend.workflows.multi_agent_workflow import MultiAgentWorkflow, get_workflow_template


class DummyStreamAgent:
    def __init__(self, chunks):
        self._chunks = chunks

    async def execute_stream(self, agent_input):
        for chunk in self._chunks:
            yield chunk


@pytest.mark.asyncio
async def test_multi_agent_workflow_normalizes_router_stream_result_for_conditions(monkeypatch):
    workflow = MultiAgentWorkflow()
    template = get_workflow_template("conditional_retrieval")

    agents = {
        "router": DummyStreamAgent([
            StreamChunk.create_result({"action": "retrieval", "confidence": 0.9, "reason": "need kb"})
        ]),
        "retrieval": DummyStreamAgent([
            StreamChunk.create_result({
                "execution_id": "ret-1",
                "retrieval_results": [{"id": "doc-1", "content": "knowledge"}],
                "total_results": 1,
            })
        ]),
        "generation": DummyStreamAgent([
            StreamChunk.create_content("final answer"),
            StreamChunk.create_result({"execution_id": "gen-1"}),
        ]),
    }

    monkeypatch.setattr(workflow, "_get_agent_instance", lambda agent_type: agents.get(agent_type))

    agent_input = AgentInput(
        user_id="user-1",
        conversation_id="conv-1",
        message_id="msg-1",
        content="需要知识库回答",
        metadata={"conversation_history": []},
    )

    final_result = None
    async for chunk in workflow.execute(agent_input, template):
        if chunk.chunk_type == "result":
            final_result = chunk.content

    assert final_result is not None
    assert final_result["status"] == "completed"
    assert "检索知识" in final_result["context"]
    assert "直接生成" not in final_result["context"]
    assert final_result["context"]["路由分析"]["data"]["decision"]["action"] == "retrieval"
    assert final_result["final_content"] == "final answer"


def test_update_input_with_context_respects_use_previous_output_flag():
    workflow = MultiAgentWorkflow()
    agent_input = AgentInput(
        user_id="user-1",
        conversation_id="conv-1",
        message_id="msg-1",
        content="question",
        metadata={"foo": "bar"},
    )
    previous_result = workflow._build_step_result(
        success=True,
        agent_type="retrieval",
        step_name="检索知识",
        step_key="检索知识",
        data={"retrieval_results": [{"id": "doc-1"}]},
    )

    without_previous = workflow._update_input_with_context(
        agent_input=agent_input,
        context={},
        step_config={"use_previous_output": False},
        previous_result=previous_result,
    )
    assert "previous_output" not in without_previous.metadata
    assert "retrieval_results" not in without_previous.metadata

    with_previous = workflow._update_input_with_context(
        agent_input=agent_input,
        context={},
        step_config={"use_previous_output": True},
        previous_result=previous_result,
    )
    assert with_previous.metadata["previous_output"]["step_key"] == "检索知识"
    assert with_previous.metadata["retrieval_results"] == [{"id": "doc-1"}]


def test_chat_sse_payload_preserves_structured_tool_and_result_data():
    tool_chunk = StreamChunk.create_tool_call("weather", {"city": "Shanghai"}, status="starting")
    tool_payload = chat._build_sse_event_payload(tool_chunk)
    assert tool_payload["tool_name"] == "weather"
    assert tool_payload["tool_input"] == {"city": "Shanghai"}
    assert tool_payload["status"] == "starting"
    assert "message" in tool_payload

    result_chunk = StreamChunk.create_result({"citations": [{"source": "doc-1"}]}, step_key="生成回答")
    result_payload = chat._build_sse_event_payload(result_chunk)
    assert result_payload["citations"] == [{"source": "doc-1"}]

    formatted = chat._format_sse_data("tool_call", tool_payload)
    assert formatted.startswith("event: tool_call\n")
    assert '"tool_name": "weather"' in formatted
    envelope = json.loads(formatted.split("data: ", 1)[1].strip())
    assert envelope["type"] == "tool_call"
    assert envelope["content"]["status"] == "starting"
    assert envelope["timestamp"]
