from datetime import datetime, timezone
from types import SimpleNamespace

import httpx
import pytest
from fastapi import FastAPI

from backend.api import chat, conversations
from backend.api.dependencies import get_current_user_id
from backend.agents.base.stream_chunk import StreamChunk
from backend.application.services.chat_application_service import ChatApplicationService


class FakeConversationRepo:
    def __init__(self):
        self.allowed = {
            "conv-a": {"user_id": "user-1", "is_active": True},
            "conv-b": {"user_id": "user-1", "is_active": True},
            "conv-inactive": {"user_id": "user-1", "is_active": False},
        }
        self.message_count_updates = []
        self.user_check_calls = []

    def get_conversation_with_user_check(self, conversation_id, user_id, only_active=True):
        self.user_check_calls.append((conversation_id, user_id, only_active))
        record = self.allowed.get(conversation_id)
        if not record or record["user_id"] != user_id:
            return None
        if only_active and not record["is_active"]:
            return None
        return SimpleNamespace(
            conversation_id=conversation_id,
            user_id=user_id,
            title=conversation_id,
            description=None,
            message_count=0,
            is_active=record["is_active"],
            created_at=datetime.now(timezone.utc),
            updated_at=datetime.now(timezone.utc),
        )

    def create_conversation(self, conversation_create):
        conversation_id = "conv-new"
        self.allowed[conversation_id] = {"user_id": conversation_create.user_id, "is_active": True}
        return SimpleNamespace(conversation_id=conversation_id, user_id=conversation_create.user_id)

    def update_message_count(self, conversation_id, increment=1):
        self.message_count_updates.append((conversation_id, increment))
        return True

    def update_conversation_timestamp(self, conversation_id):
        return True


class FakeMessageRepo:
    def __init__(self):
        self.created_counter = 100
        self.messages = {
            "conv-a": [
                self._msg("conv-a", "user", "old question A", 1),
                self._msg("conv-a", "assistant", "old answer A", 2),
            ],
            "conv-b": [
                self._msg("conv-b", "user", "old question B", 1),
            ],
        }
        self.history_calls = []

    def _msg(self, conversation_id, message_type, content, sequence_number, parent_message_id=None, metadata=None):
        self.created_counter += 1
        return SimpleNamespace(
            message_id=f"msg-{self.created_counter}",
            conversation_id=conversation_id,
            message_type=message_type,
            content=content,
            sequence_number=sequence_number,
            parent_message_id=parent_message_id,
            metadata=metadata,
            created_at=datetime.now(timezone.utc),
        )

    def get_conversation_history(self, conversation_id, limit=None):
        current = list(self.messages.get(conversation_id, []))
        result = current[-limit:] if limit else current
        self.history_calls.append(
            {
                "conversation_id": conversation_id,
                "limit": limit,
                "returned_contents": [item.content for item in result],
            }
        )
        return result

    def get_conversation_messages(self, conversation_id, limit=None, offset=None, order="ASC"):
        items = list(self.messages.get(conversation_id, []))
        if order == "DESC":
            items.reverse()
        if offset:
            items = items[offset:]
        if limit is not None:
            items = items[:limit]
        return items

    def count_conversation_messages(self, conversation_id):
        return len(self.messages.get(conversation_id, []))

    def get_next_sequence_number(self, conversation_id):
        return len(self.messages.get(conversation_id, [])) + 1

    def create_message(self, message_create):
        msg = self._msg(
            message_create.conversation_id,
            message_create.message_type,
            message_create.content,
            message_create.sequence_number,
            parent_message_id=message_create.parent_message_id,
            metadata=message_create.metadata,
        )
        self.messages.setdefault(message_create.conversation_id, []).append(msg)
        return msg


class FakeWorkflowService:
    async def execute_stream(self, agent_input):
        yield StreamChunk.create_thinking("working")
        yield StreamChunk.create_content(f"answer for {agent_input.conversation_id}")
        yield StreamChunk.create_result({"citations": [{"id": "c1"}], "execution_id": "exec-flow-1"})


class FakeKnowledgeRepo:
    def get_by_id_for_user(self, knowledge_base_id, user_id):
        return SimpleNamespace(knowledge_base_id=knowledge_base_id, user_id=user_id)


def build_chat_service(conversation_repo, message_repo):
    return ChatApplicationService(
        workflow_service=FakeWorkflowService(),
        conversation_repo=conversation_repo,
        message_repo=message_repo,
        knowledge_base_repo=FakeKnowledgeRepo(),
    )


def build_client(monkeypatch):
    app = FastAPI()
    app.include_router(chat.router)
    app.include_router(conversations.router)
    app.dependency_overrides[get_current_user_id] = lambda: "user-1"

    conversation_repo = FakeConversationRepo()
    message_repo = FakeMessageRepo()

    monkeypatch.setattr(chat, "get_chat_application_service", lambda: build_chat_service(conversation_repo, message_repo))
    monkeypatch.setattr(chat, "_get_chat_history_limit", lambda: 5)

    monkeypatch.setattr(conversations, "get_conversation_repository", lambda: conversation_repo)
    monkeypatch.setattr(conversations, "get_message_repository", lambda: message_repo)

    transport = httpx.ASGITransport(app=app)
    client = httpx.AsyncClient(transport=transport, base_url="http://testserver")
    return client, conversation_repo, message_repo


@pytest.mark.asyncio
async def test_api_continue_history_keeps_conversation_isolation(monkeypatch):
    client, conversation_repo, message_repo = build_client(monkeypatch)

    try:
        response = await client.post(
            "/api/v1/chat/ask",
            json={
                "question": "follow up on A",
                "conversation_id": "conv-a",
                "stream": False,
                "enable_knowledge_base": False,
            },
        )

        assert response.status_code == 200
        payload = response.json()
        assert payload["data"]["conversation_id"] == "conv-a"
        assert payload["data"]["answer"] == "answer for conv-a"
        assert payload["data"]["execution_id"] == "exec-flow-1"

        assert message_repo.history_calls == [
            {
                "conversation_id": "conv-a",
                "limit": 5,
                "returned_contents": ["old question A", "old answer A"],
            }
        ]
        assert conversation_repo.message_count_updates == [("conv-a", 1), ("conv-a", 1)]

        messages_a = await client.get("/api/v1/conversations/conv-a/messages")
        assert messages_a.status_code == 200
        contents_a = [item["content"] for item in messages_a.json()["data"]]
        assert contents_a == [
            "old question A",
            "old answer A",
            "follow up on A",
            "answer for conv-a",
        ]
        assert messages_a.json()["data"][3]["parent_message_id"] == payload["data"]["message_id"]

        messages_b = await client.get("/api/v1/conversations/conv-b/messages")
        assert messages_b.status_code == 200
        contents_b = [item["content"] for item in messages_b.json()["data"]]
        assert contents_b == ["old question B"]
    finally:
        await client.aclose()


@pytest.mark.asyncio
async def test_api_blocks_inactive_conversation_for_history_and_continue(monkeypatch):
    client, _, _ = build_client(monkeypatch)

    try:
        ask_response = await client.post(
            "/api/v1/chat/ask",
            json={
                "question": "continue deleted conversation",
                "conversation_id": "conv-inactive",
                "stream": False,
            },
        )
        assert ask_response.status_code == 404

        messages_response = await client.get("/api/v1/conversations/conv-inactive/messages")
        assert messages_response.status_code == 404
    finally:
        await client.aclose()


@pytest.mark.asyncio
async def test_stream_api_returns_same_conversation_metadata_and_done(monkeypatch):
    client, conversation_repo, _ = build_client(monkeypatch)

    try:
        async with client.stream(
            "POST",
            "/api/v1/chat/ask",
            json={
                "question": "stream follow up",
                "conversation_id": "conv-a",
                "stream": True,
            },
        ) as response:
            assert response.status_code == 200
            body = ""
            async for chunk in response.aiter_text():
                body += chunk

        assert "event: thinking" in body
        assert '"stream_started"' in body
        assert '"conversation_id": "conv-a"' in body
        assert '"assistant_message_id":' in body
        assert "event: done" in body
        assert conversation_repo.message_count_updates == [("conv-a", 1), ("conv-a", 1)]
    finally:
        await client.aclose()
