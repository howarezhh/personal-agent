import asyncio

from backend.agents.base.agent_input import AgentInput
from backend.agents.base.agent_output import AgentOutput
from backend.agents.base.stream_chunk import StreamChunk
from backend.contracts.errors import ErrorCode
from backend.utils.logger import get_logger
from backend.workflows.multi_agent_workflow import MultiAgentWorkflow, get_workflow_template
from backend.workflows.workflow_executor import WorkflowExecutor


def test_workflow_executor_accepts_conditional_workflow_template():
    executor = WorkflowExecutor.__new__(WorkflowExecutor)
    executor.multi_agent_workflow = MultiAgentWorkflow()

    workflow_config = get_workflow_template("conditional_retrieval")

    assert executor._is_valid_workflow_config(workflow_config) is True


def test_multi_agent_workflow_respects_use_previous_output_flag():
    workflow = MultiAgentWorkflow()
    agent_input = AgentInput(
        user_id="user-1",
        conversation_id="conv-3",
        message_id="msg-1",
        content="follow up",
        conversation_history=[{"role": "user", "content": "first line"}],
        metadata={},
    )
    previous_result = {
        "success": True,
        "agent_type": "retrieval",
        "step_name": "step",
        "step_key": "step",
        "execution_id": None,
        "content": "retrieved",
        "metadata": {},
        "data": {"retrieval_results": [{"id": 1}]},
        "error": None,
    }

    without_handoff = workflow._update_input_with_context(
        agent_input=agent_input,
        context={},
        step_config={},
        previous_result=previous_result,
    )
    with_handoff = workflow._update_input_with_context(
        agent_input=agent_input,
        context={},
        step_config={"use_previous_output": True},
        previous_result=previous_result,
    )

    assert "previous_output" not in without_handoff.metadata
    assert "retrieval_results" not in without_handoff.metadata
    assert with_handoff.metadata["previous_output"]["step_key"] == "step"
    assert with_handoff.metadata["retrieval_results"] == [{"id": 1}]


class _DummyRouterAgent:
    def __init__(self, action="direct_answer", suggested_tools=None):
        self.action = action
        self.suggested_tools = suggested_tools or []

    async def execute(self, agent_input):
        decision = {"action": self.action}
        if self.suggested_tools:
            decision["suggested_tools"] = list(self.suggested_tools)
        return AgentOutput(status="success", metadata={"decision": decision})


class _ThinkingGenerationAgent:
    async def execute_stream(self, agent_input):
        yield StreamChunk.create_thinking("正在生成回答...")
        yield StreamChunk.create_content("answer")


class _CaptureGenerationAgent:
    def __init__(self):
        self.context_call = None
        self.tool_call = None

    async def execute_stream(self, agent_input):
        yield StreamChunk.create_content("fallback answer")

    async def generate_with_context_stream(self, agent_input, retrieval_results):
        self.context_call = (agent_input, retrieval_results)
        yield StreamChunk.create_content("context answer")

    async def generate_with_tool_result_stream(self, agent_input, tool_result):
        self.tool_call = (agent_input, tool_result)
        yield StreamChunk.create_content("tool answer")


class _DummyRetrievalAgent:
    async def execute_stream(self, agent_input):
        yield StreamChunk.create_thinking("正在检索知识库...")
        yield StreamChunk.create_result(
            {
                "execution_id": "ret-1",
                "retrieval_results": [{"id": "doc-1", "content": "knowledge"}],
                "total_results": 1,
            }
        )


class _DummyToolAgentSuccess:
    async def execute_stream(self, agent_input):
        yield StreamChunk.create_tool_call("weather", {"city": "Shanghai"}, status="starting")
        yield StreamChunk.create_result(
            {
                "execution_id": "tool-1",
                "tool_name": "weather",
                "tool_result": {"success": True, "data": {"temp": 25}, "error": None},
                "interpreted_result": {"success": True, "formatted_text": "25C"},
                "execution_time_ms": 12,
            }
        )


def _build_executor():
    executor = WorkflowExecutor.__new__(WorkflowExecutor)
    executor.logger = get_logger("WorkflowExecutorRegressionTest")
    executor.router_agent = _DummyRouterAgent()
    executor.generation_agent = _ThinkingGenerationAgent()
    executor.retrieval_agent = _DummyRetrievalAgent()
    executor.tool_agent = _DummyToolAgentSuccess()
    executor.multi_agent_workflow = MultiAgentWorkflow()
    executor.workflow_planner = None
    return executor


def test_workflow_planner_builds_stateful_retrieval_path():
    executor = _build_executor()
    executor.router_agent = _DummyRouterAgent(action="retrieval")

    agent_input = AgentInput(
        user_id="user-1",
        conversation_id="conv-1",
        message_id="msg-1",
        content="需要检索知识库",
        metadata={"request_id": "req-1"},
    )

    plan_state = asyncio.run(executor._get_workflow_planner().plan(agent_input))

    assert plan_state["execution_action"] == "retrieval"
    assert plan_state["execution_path"] == ["intent_recognition", "retrieval", "generation"]
    assert plan_state["workflow_engine"] in {"builtin", "langgraph"}


def test_execute_workflow_returns_structured_validation_error_without_mutation():
    executor = _build_executor()
    agent_input = AgentInput(
        user_id="user-1",
        conversation_id="conv-1",
        message_id="msg-1",
        content="",
        conversation_history=[{"role": "user", "content": "hello"}],
        metadata=None,
    )

    async def _collect():
        return [chunk async for chunk in executor.execute_workflow(agent_input)]

    chunks = asyncio.run(_collect())

    assert len(chunks) == 1
    assert chunks[0].chunk_type == "error"
    assert chunks[0].metadata["error_code"] == ErrorCode.WORKFLOW_INVALID_INPUT.value
    assert chunks[0].metadata["error_type"] == "validation_error"
    assert agent_input.metadata is None


def test_direct_answer_workflow_does_not_duplicate_thinking_chunks():
    executor = _build_executor()
    agent_input = AgentInput(
        user_id="user-1",
        conversation_id="conv-1",
        message_id="msg-1",
        content="直接回答",
        metadata={},
    )

    async def _collect():
        return [chunk async for chunk in executor._execute_direct_answer_workflow(agent_input)]

    chunks = asyncio.run(_collect())
    thinking_chunks = [chunk for chunk in chunks if chunk.chunk_type == "thinking"]

    assert len(thinking_chunks) == 1
    assert thinking_chunks[0].content == "正在生成回答..."


def test_retrieval_handoff_keeps_flow_payload_out_of_metadata():
    executor = _build_executor()
    capture_generation = _CaptureGenerationAgent()
    executor.generation_agent = capture_generation

    agent_input = AgentInput(
        user_id="user-1",
        conversation_id="conv-1",
        message_id="msg-1",
        content="检索后回答",
        conversation_history=[{"role": "user", "content": "历史问题"}],
        metadata=None,
    )

    async def _collect():
        return [chunk async for chunk in executor._execute_retrieval_workflow(agent_input)]

    chunks = asyncio.run(_collect())

    assert any(chunk.chunk_type == "content" and chunk.content == "context answer" for chunk in chunks)
    assert capture_generation.context_call is not None
    generation_input, retrieval_results = capture_generation.context_call
    assert generation_input.metadata["conversation_history"] == [{"role": "user", "content": "历史问题"}]
    assert "retrieval_results" not in generation_input.metadata
    assert retrieval_results == [{"id": "doc-1", "content": "knowledge"}]
    assert agent_input.metadata is None


def test_tool_handoff_keeps_flow_payload_out_of_metadata():
    executor = _build_executor()
    capture_generation = _CaptureGenerationAgent()
    executor.generation_agent = capture_generation

    agent_input = AgentInput(
        user_id="user-1",
        conversation_id="conv-1",
        message_id="msg-1",
        content="先调工具再回答",
        conversation_history=[{"role": "user", "content": "历史消息"}],
        metadata=None,
    )

    async def _collect():
        return [chunk async for chunk in executor._execute_tool_call_workflow(agent_input)]

    chunks = asyncio.run(_collect())

    assert any(chunk.chunk_type == "content" and chunk.content == "tool answer" for chunk in chunks)
    assert capture_generation.tool_call is not None
    generation_input, tool_result = capture_generation.tool_call
    assert generation_input.metadata["conversation_history"] == [{"role": "user", "content": "历史消息"}]
    assert "tool_result" not in generation_input.metadata
    assert "tool_name" not in generation_input.metadata
    assert tool_result["tool_name"] == "weather"
    assert agent_input.metadata is None
