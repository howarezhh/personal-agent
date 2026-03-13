"""Conversation application service."""

from backend.infrastructure.persistence import ConversationRepositoryAdapter, MessageRepositoryAdapter
from backend.models.conversation import ConversationCreate, ConversationUpdate


class ConversationApplicationService:
    def __init__(self, conversation_repo=None, message_repo=None):
        self.conversation_repo = conversation_repo or ConversationRepositoryAdapter()
        self.message_repo = message_repo or MessageRepositoryAdapter()

    def list_conversations(self, *, user_id: str, page: int, page_size: int, only_active: bool):
        offset = (page - 1) * page_size
        summaries = self.conversation_repo.get_user_conversation_summaries(
            user_id=user_id,
            limit=page_size,
            offset=offset,
            only_active=only_active,
        )
        total = self.conversation_repo.count_user_conversations(user_id=user_id, only_active=only_active)
        return summaries, total

    def get_conversation(self, *, user_id: str, conversation_id: str):
        return self.conversation_repo.get_conversation_with_user_check(conversation_id=conversation_id, user_id=user_id)

    def get_messages(self, *, user_id: str, conversation_id: str, page: int, page_size: int):
        conversation = self.get_conversation(user_id=user_id, conversation_id=conversation_id)
        if not conversation:
            return None, []
        offset = (page - 1) * page_size
        if hasattr(self.message_repo, "get_messages_by_conversation_id"):
            messages = self.message_repo.get_messages_by_conversation_id(conversation_id, limit=page_size, offset=offset)
        else:
            messages = self.message_repo.get_conversation_messages(
                conversation_id,
                limit=page_size,
                offset=offset,
                order="ASC",
            )
        if hasattr(self.message_repo, "count_messages_by_conversation_id"):
            total = self.message_repo.count_messages_by_conversation_id(conversation_id)
        else:
            total = self.message_repo.count_conversation_messages(conversation_id)
        return total, messages

    def create_conversation(self, *, user_id: str, title: str | None, description: str | None):
        return self.conversation_repo.create_conversation(
            ConversationCreate(user_id=user_id, title=title or "新对话", description=description)
        )

    def update_conversation(self, *, user_id: str, conversation_id: str, title: str | None, description: str | None):
        conversation = self.get_conversation(user_id=user_id, conversation_id=conversation_id)
        if not conversation:
            return None
        self.conversation_repo.update_conversation(
            conversation_id,
            ConversationUpdate(title=title, description=description),
        )
        return self.get_conversation(user_id=user_id, conversation_id=conversation_id)

    def delete_conversation(self, *, user_id: str, conversation_id: str):
        conversation = self.get_conversation(user_id=user_id, conversation_id=conversation_id)
        if not conversation:
            return False
        return self.conversation_repo.delete_conversation(conversation_id, soft_delete=True)
