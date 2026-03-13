import logging
from types import SimpleNamespace

import pytest

from backend.agents.base.agent_input import AgentInput
from backend.agents.router.router_agent import RouterAgent


class FakeExecutionRepo:
    def create_execution(self, execution_create):
        return SimpleNamespace(execution_id="exec-1")

    def update_execution(self, execution_id, execution_update):
        return True


class FakePromptManager:
    def get_prompt(self, key, default=""):
        return "system prompt"

    def build_messages(self, **kwargs):
        return [{"role": "user", "content": kwargs["user_content"]}]


class FakeDecisionMaker:
    def analyze_question(self, question, conversation_history, llm_decision=None):
        return {
            "action": "direct_answer",
            "confidence": 0.91,
            "reason": "simple answer",
            "suggested_tools": [],
        }

    def validate_decision(self, decision):
        return True


class FakeLlmClient:
    async def chat_completion(self, **kwargs):
        return '{"action": "direct_answer", "confidence": 0.88, "reason": "simple", "suggested_tools": []}'


@pytest.mark.asyncio
async def test_router_keeps_direct_answer_when_knowledge_base_enabled():
    agent = RouterAgent.__new__(RouterAgent)
    agent.agent_name = "router_agent"
    agent.agent_type = "router"
    agent.logger = logging.getLogger("test_router_agent")
    agent.execution_repo = FakeExecutionRepo()
    agent.prompt_manager = FakePromptManager()
    agent.decision_maker = FakeDecisionMaker()
    agent.llm_client = FakeLlmClient()
    agent._get_config_value = lambda key, default=None: default

    agent_input = AgentInput(
        user_id="user-1",
        conversation_id="conv-1",
        message_id="msg-1",
        content="你好",
        metadata={"enable_knowledge_base": True, "conversation_history": []},
    )

    output = await agent.execute(agent_input)

    assert output.status == "success"
    assert output.metadata["decision"]["action"] == "direct_answer"
