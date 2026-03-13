"""User repository adapter."""

from backend.database.repositories.user_repository import get_user_repository


class UserRepositoryAdapter:
    def __init__(self, repository=None):
        self.repository = repository or get_user_repository()

    def __getattr__(self, item):
        return getattr(self.repository, item)

