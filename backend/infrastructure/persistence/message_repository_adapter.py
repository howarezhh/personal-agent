
from backend.database.repositories.message_repository import get_message_repository


class MessageRepositoryAdapter:
    def __init__(self, repository=None):
        self.repository = repository or get_message_repository()

    def get_messages_by_conversation_id(self, conversation_id: str, limit: int | None = None, offset: int | None = None):
        if hasattr(self.repository, "get_messages_by_conversation_id"):
            return self.repository.get_messages_by_conversation_id(conversation_id, limit=limit, offset=offset)
        return self.repository.get_conversation_messages(conversation_id, limit=limit, offset=offset, order="ASC")

    def count_messages_by_conversation_id(self, conversation_id: str) -> int:
        if hasattr(self.repository, "count_messages_by_conversation_id"):
            return self.repository.count_messages_by_conversation_id(conversation_id)
        return self.repository.count_conversation_messages(conversation_id)

    def __getattr__(self, item):
        return getattr(self.repository, item)

