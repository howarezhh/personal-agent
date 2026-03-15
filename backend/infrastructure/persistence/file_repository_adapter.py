
from backend.database.repositories.file_repository import get_file_repository


class FileRepositoryAdapter:
    def __init__(self, repository=None):
        self.repository = repository or get_file_repository()

    def __getattr__(self, item):
        return getattr(self.repository, item)

