from backend.agents.base.agent_input import AgentInput
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
