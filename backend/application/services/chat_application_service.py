"""Chat application service for orchestrating chat use cases."""

from typing import Any, Optional

from backend.agents.base.agent_input import AgentInput
from backend.application.services.workflow_application_service import WorkflowApplicationService
from backend.infrastructure.persistence import (
    ConversationRepositoryAdapter,
    KnowledgeBaseRepositoryAdapter,
    MessageRepositoryAdapter,
)
from backend.models.conversation import ConversationCreate
from backend.models.message import MessageCreate
from backend.utils.citation_utils import normalize_message_content_with_citations, replace_citation_placeholders


class ChatApplicationService:
    def __init__(
        self,
        workflow_service: WorkflowApplicationService | None = None,
        conversation_repo=None,
        message_repo=None,
        knowledge_base_repo=None,
    ):
        self.workflow_service = workflow_service or WorkflowApplicationService()
        self.conversation_repo = conversation_repo or ConversationRepositoryAdapter()
        self.message_repo = message_repo or MessageRepositoryAdapter()
        self.knowledge_base_repo = knowledge_base_repo or KnowledgeBaseRepositoryAdapter()

    def ensure_conversation(self, *, user_id: str, conversation_id: Optional[str], question: str):
        if conversation_id:
            conversation = self.conversation_repo.get_conversation_with_user_check(
                conversation_id=conversation_id,
                user_id=user_id,
            )
            return conversation, conversation_id

        conversation = self.conversation_repo.create_conversation(
            ConversationCreate(
                user_id=user_id,
                title=question[:50] + ("..." if len(question) > 50 else ""),
            )
        )
        return conversation, conversation.conversation_id

    def ensure_knowledge_base(self, *, user_id: str, knowledge_base_id: Optional[str]):
        if not knowledge_base_id:
            return None
        return self.knowledge_base_repo.get_by_id_for_user(knowledge_base_id, user_id)

    def get_history(self, *, conversation_id: str, limit: int):
        history = self.message_repo.get_conversation_history(conversation_id=conversation_id, limit=limit)
        for message in history:
            if message.message_type == "assistant":
                message.content = normalize_message_content_with_citations(message.content, message.metadata)
        return history, [
            {"role": "user" if msg.message_type == "user" else "assistant", "content": msg.content}
            for msg in history
        ]

    def save_user_message(self, *, conversation_id: str, question: str, metadata: dict[str, Any] | None = None):
        sequence_number = self.message_repo.get_next_sequence_number(conversation_id)
        message = self.message_repo.create_message(
            MessageCreate(
                conversation_id=conversation_id,
                message_type="user",
                content=question,
                sequence_number=sequence_number,
                metadata=metadata,
            )
        )
        self.conversation_repo.update_message_count(conversation_id, increment=1)
        return message

    def build_agent_input(
        self,
        *,
        user_id: str,
        conversation_id: str,
        user_message_id: str,
        question: str,
        conversation_history: list[dict[str, Any]],
        enable_knowledge_base: bool,
        knowledge_base_id: Optional[str],
        request_id: Optional[str] = None,
    ) -> AgentInput:
        return AgentInput(
            user_id=user_id,
            conversation_id=conversation_id,
            message_id=user_message_id,
            content=question,
            conversation_history=conversation_history,
            metadata={
                "conversation_history": conversation_history,
                "enable_knowledge_base": enable_knowledge_base,
                "knowledge_base_id": knowledge_base_id,
                "vector_search_filter": {"knowledge_base_id": knowledge_base_id} if knowledge_base_id else None,
                "request_id": request_id,
            },
        )

    def save_assistant_message(
        self,
        *,
        conversation_id: str,
        content: str,
        citations: list[Any],
        parent_message_id: str | None = None,
        metadata: dict[str, Any] | None = None,
    ):
        if not content:
            return None
        normalized_content = replace_citation_placeholders(content, citations)
        message_metadata = {"citations": citations} if citations else {}
        if metadata:
            message_metadata.update(metadata)
        sequence_number = self.message_repo.get_next_sequence_number(conversation_id)
        message = self.message_repo.create_message(
            MessageCreate(
                conversation_id=conversation_id,
                message_type="assistant",
                content=normalized_content,
                sequence_number=sequence_number,
                parent_message_id=parent_message_id,
                metadata=message_metadata or None,
            )
        )
        self.conversation_repo.update_message_count(conversation_id, increment=1)
        self.conversation_repo.update_conversation_timestamp(conversation_id)
        return message

    async def generate_non_stream_answer(self, *, agent_input: AgentInput) -> tuple[str, list[Any]]:
        answer = ""
        citations: list[Any] = []
        async for chunk in self.workflow_service.execute_stream(agent_input):
            if chunk.chunk_type == "content":
                answer += chunk.content
            elif chunk.chunk_type == "result" and isinstance(chunk.content, dict):
                citations = chunk.content.get("citations", []) or citations
            elif chunk.chunk_type == "error":
                raise RuntimeError(str(chunk.content))
        return answer, citations
