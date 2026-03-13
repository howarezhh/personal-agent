"""Knowledge-base repository adapter."""

from backend.database.repositories.knowledge_base_repository import get_knowledge_base_repository


class KnowledgeBaseRepositoryAdapter:
    def __init__(self, repository=None):
        self.repository = repository or get_knowledge_base_repository()

    def __getattr__(self, item):
        return getattr(self.repository, item)

