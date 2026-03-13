import pytest
from types import SimpleNamespace

from backend.api import chat
from backend.api.chat import AskRequest
from backend.application.services.chat_application_service import ChatApplicationService


class FakeConversationRepo:
    def __init__(self):
        self.user_check_calls = []
        self.message_count_updates = []

    def get_conversation_with_user_check(self, conversation_id, user_id, only_active=True):
        self.user_check_calls.append(
            {
                "conversation_id": conversation_id,
                "user_id": user_id,
                "only_active": only_active,
            }
        )
        return SimpleNamespace(conversation_id=conversation_id, user_id=user_id, is_active=True)

    def create_conversation(self, conversation_create):
        return SimpleNamespace(conversation_id="new-conv", user_id=conversation_create.user_id)

    def update_message_count(self, conversation_id, increment=1):
        self.message_count_updates.append((conversation_id, increment))
        return True

    def update_conversation_timestamp(self, conversation_id):
        return True


class FakeMessageRepo:
    def __init__(self):
        self.history_limits = []
        self.created_messages = []
        self.sequence = 0

    def get_conversation_history(self, conversation_id, limit=None):
        self.history_limits.append((conversation_id, limit))
        return [
            SimpleNamespace(message_type="user", content="history question"),
            SimpleNamespace(message_type="assistant", content="history answer"),
        ]

    def get_next_sequence_number(self, conversation_id):
        self.sequence += 1
        return self.sequence

    def create_message(self, message_create):
        message_id = f"msg-{len(self.created_messages) + 1}"
        message = SimpleNamespace(
            message_id=message_id,
            conversation_id=message_create.conversation_id,
            message_type=message_create.message_type,
            content=message_create.content,
            sequence_number=message_create.sequence_number,
            parent_message_id=message_create.parent_message_id,
            metadata=message_create.metadata,
        )
        self.created_messages.append(message)
        return message


class FakeKnowledgeRepo:
    def get_by_id_for_user(self, knowledge_base_id, user_id):
        return SimpleNamespace(knowledge_base_id=knowledge_base_id, user_id=user_id)


class FakeWorkflowService:
    async def execute_stream(self, agent_input):
        yield SimpleNamespace(chunk_type="content", content="assistant reply", metadata={})
        yield SimpleNamespace(chunk_type="result", content={"citations": [], "execution_id": "exec-123"}, metadata={})


def build_chat_service(conversation_repo, message_repo, workflow_service=None):
    return ChatApplicationService(
        workflow_service=workflow_service or FakeWorkflowService(),
        conversation_repo=conversation_repo,
        message_repo=message_repo,
        knowledge_base_repo=FakeKnowledgeRepo(),
    )


@pytest.mark.asyncio
async def test_ask_uses_active_conversation_check_and_configured_history_limit(monkeypatch):
    conversation_repo = FakeConversationRepo()
    message_repo = FakeMessageRepo()

    async def fake_non_stream_response(**kwargs):
        return {"answer": "assistant answer", "execution_id": "exec-ask-1"}

    monkeypatch.setattr(chat, "get_chat_application_service", lambda: build_chat_service(conversation_repo, message_repo))
    monkeypatch.setattr(chat, "_non_stream_response", fake_non_stream_response)
    monkeypatch.setattr(chat, "_get_chat_history_limit", lambda: 7)

    response = await chat.ask(
        AskRequest(question="continue this topic", conversation_id="conv-1", stream=False),
        user_id="user-1",
    )

    assert conversation_repo.user_check_calls == [
        {"conversation_id": "conv-1", "user_id": "user-1", "only_active": True}
    ]
    assert message_repo.history_limits == [("conv-1", 7)]
    assert conversation_repo.message_count_updates == [("conv-1", 1)]
    assert response.data.conversation_id == "conv-1"
    assert response.data.answer == "assistant answer"
    assert response.data.execution_id == "exec-ask-1"


@pytest.mark.asyncio
async def test_non_stream_response_saves_assistant_message_and_updates_count(monkeypatch):
    conversation_repo = FakeConversationRepo()
    message_repo = FakeMessageRepo()

    monkeypatch.setattr(chat, "get_chat_application_service", lambda: build_chat_service(conversation_repo, message_repo))

    result = await chat._non_stream_response(
        user_id="user-1",
        conversation_id="conv-2",
        user_message_id="msg-user",
        question="hello",
        conversation_history=[{"role": "user", "content": "previous question"}],
        enable_knowledge_base=False,
    )

    assert result["answer"] == "assistant reply"
    assert result["execution_id"] == "exec-123"
    assert [(item.message_type, item.content) for item in message_repo.created_messages] == [
        ("assistant", "assistant reply")
    ]
    assert message_repo.created_messages[0].parent_message_id == "msg-user"
    assert message_repo.created_messages[0].metadata["execution_id"] == "exec-123"
    assert conversation_repo.message_count_updates == [("conv-2", 1)]


def test_build_agent_input_keeps_history_in_field_and_metadata():
    service = build_chat_service(FakeConversationRepo(), FakeMessageRepo())

    agent_input = service.build_agent_input(
        user_id="user-1",
        conversation_id="conv-1",
        user_message_id="msg-1",
        question="hello",
        conversation_history=[{"role": "user", "content": "history question"}],
        enable_knowledge_base=True,
        knowledge_base_id="kb-1",
        request_id="req-1",
    )

    assert agent_input.conversation_history == [{"role": "user", "content": "history question"}]
    assert agent_input.metadata["conversation_history"] == [{"role": "user", "content": "history question"}]
    assert agent_input.metadata["knowledge_base_id"] == "kb-1"
