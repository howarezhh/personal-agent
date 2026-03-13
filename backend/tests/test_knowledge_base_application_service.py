from datetime import datetime

import pytest

from backend.application.services.knowledge_base_application_service import (
    DEFAULT_KNOWLEDGE_BASE_DESCRIPTION,
    DEFAULT_KNOWLEDGE_BASE_NAME,
    KnowledgeBaseApplicationService,
)
from backend.models.knowledge_base import KnowledgeBase, KnowledgeBaseCreate


def make_knowledge_base(
    knowledge_base_id: str,
    *,
    user_id: str = "user-1",
    name: str | None = None,
    description: str | None = None,
    is_default: bool = False,
    is_active: bool = True,
) -> KnowledgeBase:
    now = datetime.utcnow()
    return KnowledgeBase(
        knowledge_base_id=knowledge_base_id,
        user_id=user_id,
        name=name or knowledge_base_id,
        description=description,
        is_default=is_default,
        is_active=is_active,
        created_at=now,
        updated_at=now,
    )


class FakeKnowledgeBaseRepository:
    def __init__(self, items: list[KnowledgeBase] | None = None):
        self.items = items or []

    def list_by_user(self, user_id: str, active_only: bool = True):
        items = [item for item in self.items if item.user_id == user_id]
        if active_only:
            items = [item for item in items if item.is_active]
        return sorted(items, key=lambda item: (not item.is_default, item.created_at))

    def create_knowledge_base(self, knowledge_base_create: KnowledgeBaseCreate):
        knowledge_base = knowledge_base_create.to_knowledge_base()
        self.items.append(knowledge_base)
        return knowledge_base

    def get_by_id_for_user(self, knowledge_base_id: str, user_id: str):
        for item in self.items:
            if item.knowledge_base_id == knowledge_base_id and item.user_id == user_id and item.is_active:
                return item
        return None

    def get_default_by_user(self, user_id: str):
        for item in self.items:
            if item.user_id == user_id and item.is_active and item.is_default:
                return item
        return None

    def exists_by_name(self, user_id: str, name: str) -> bool:
        normalized = name.strip()
        return any(
            item.user_id == user_id and item.is_active and item.name == normalized
            for item in self.items
        )

    def clear_default(self, user_id: str) -> int:
        affected = 0
        for index, item in enumerate(self.items):
            if item.user_id == user_id and item.is_active and item.is_default:
                self.items[index] = make_knowledge_base(
                    item.knowledge_base_id,
                    user_id=item.user_id,
                    name=item.name,
                    description=item.description,
                    is_default=False,
                    is_active=item.is_active,
                )
                affected += 1
        return affected

    def set_default_by_id(self, knowledge_base_id: str, user_id: str) -> bool:
        for index, item in enumerate(self.items):
            if item.knowledge_base_id == knowledge_base_id and item.user_id == user_id and item.is_active:
                self.items[index] = make_knowledge_base(
                    item.knowledge_base_id,
                    user_id=item.user_id,
                    name=item.name,
                    description=item.description,
                    is_default=True,
                    is_active=item.is_active,
                )
                return True
        return False

    def soft_delete_knowledge_base(self, knowledge_base_id: str, user_id: str) -> bool:
        for index, item in enumerate(self.items):
            if item.knowledge_base_id == knowledge_base_id and item.user_id == user_id and item.is_active:
                self.items[index] = make_knowledge_base(
                    item.knowledge_base_id,
                    user_id=item.user_id,
                    name=item.name,
                    description=item.description,
                    is_default=False,
                    is_active=False,
                )
                return True
        return False


def test_ensure_default_for_user_promotes_first_active_knowledge_base():
    repository = FakeKnowledgeBaseRepository(
        [
            make_knowledge_base("kb-1", name="Alpha", is_default=False),
            make_knowledge_base("kb-2", name="Beta", is_default=False),
        ]
    )
    service = KnowledgeBaseApplicationService(knowledge_repo=repository, embedding_gateway=object(), vector_store=object())

    default_base = service.ensure_default_for_user(user_id="user-1")

    assert default_base.knowledge_base_id == "kb-1"
    assert repository.get_default_by_user("user-1").knowledge_base_id == "kb-1"


def test_ensure_default_for_user_creates_default_when_none_exists():
    repository = FakeKnowledgeBaseRepository()
    service = KnowledgeBaseApplicationService(knowledge_repo=repository, embedding_gateway=object(), vector_store=object())

    default_base = service.ensure_default_for_user(user_id="user-1")

    assert default_base.name == DEFAULT_KNOWLEDGE_BASE_NAME
    assert default_base.description == DEFAULT_KNOWLEDGE_BASE_DESCRIPTION
    assert default_base.is_default is True


def test_list_knowledge_bases_promotes_default_before_returning_items():
    repository = FakeKnowledgeBaseRepository(
        [
            make_knowledge_base("kb-1", name="Alpha", is_default=False),
            make_knowledge_base("kb-2", name="Beta", is_default=False),
        ]
    )
    service = KnowledgeBaseApplicationService(knowledge_repo=repository, embedding_gateway=object(), vector_store=object())

    knowledge_bases, total = service.list_knowledge_bases(user_id="user-1")

    assert total == 2
    assert knowledge_bases[0].knowledge_base_id == "kb-1"
    assert knowledge_bases[0].is_default is True
    assert repository.get_default_by_user("user-1").knowledge_base_id == "kb-1"


def test_delete_default_knowledge_base_reassigns_next_default():
    repository = FakeKnowledgeBaseRepository(
        [
            make_knowledge_base("kb-1", name="Alpha", is_default=True),
            make_knowledge_base("kb-2", name="Beta", is_default=False),
        ]
    )
    service = KnowledgeBaseApplicationService(knowledge_repo=repository, embedding_gateway=object(), vector_store=object())

    deleted = service.delete_knowledge_base(knowledge_base_id="kb-1", user_id="user-1")

    assert deleted.knowledge_base_id == "kb-1"
    assert repository.get_default_by_user("user-1").knowledge_base_id == "kb-2"
    assert repository.get_by_id_for_user("kb-1", "user-1") is None


def test_create_knowledge_base_rejects_duplicate_name():
    repository = FakeKnowledgeBaseRepository([make_knowledge_base("kb-1", name="Alpha", is_default=True)])
    service = KnowledgeBaseApplicationService(knowledge_repo=repository, embedding_gateway=object(), vector_store=object())

    with pytest.raises(ValueError, match="已存在"):
        service.create_knowledge_base(user_id="user-1", name="Alpha", description=None)
