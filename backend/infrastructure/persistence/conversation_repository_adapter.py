
from backend.database.repositories.conversation_repository import get_conversation_repository


class ConversationRepositoryAdapter:
    def __init__(self, repository=None):
        self.repository = repository or get_conversation_repository()

    def __getattr__(self, item):
        return getattr(self.repository, item)

