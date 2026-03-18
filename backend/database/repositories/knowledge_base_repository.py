"""知识库仓储模块。

本文件使用 UTF-8 编码，负责知识库实体的创建、查询、更新与删除。
"""

from __future__ import annotations

from typing import List, Optional

from backend.database.database_manager import DatabaseManager, get_database_manager
from backend.database.repositories.user_repository import BaseRepository
from backend.models.knowledge_base import KnowledgeBase, KnowledgeBaseCreate
from backend.utils.logger import get_logger
from backend.utils.time_utils import utc_now


logger = get_logger(__name__)


class KnowledgeBaseRepository(BaseRepository):
    TABLE_NAME = "knowledge_bases"

    def __init__(self, db_manager: Optional[DatabaseManager] = None):
        super().__init__(db_manager)

    def create_knowledge_base(self, knowledge_base_create: KnowledgeBaseCreate) -> KnowledgeBase:
        knowledge_base = knowledge_base_create.to_knowledge_base()
        data = {
            "knowledge_base_id": knowledge_base.knowledge_base_id,
            "user_id": knowledge_base.user_id,
            "name": knowledge_base.name,
            "description": knowledge_base.description,
            "is_default": 1 if knowledge_base.is_default else 0,
            "is_active": 1 if knowledge_base.is_active else 0,
            "created_at": knowledge_base.created_at,
            "updated_at": knowledge_base.updated_at,
        }
        self.db.insert_one(self.TABLE_NAME, data, return_id=False)
        return knowledge_base

    def list_by_user(self, user_id: str, active_only: bool = True) -> List[KnowledgeBase]:
        where = {"user_id": user_id}
        if active_only:
            where["is_active"] = 1
        results = self.db.select_many(
            table=self.TABLE_NAME,
            where=where,
            order_by="is_default DESC, created_at ASC",
        )
        return self._dicts_to_models(results, KnowledgeBase)

    def get_by_id(self, knowledge_base_id: str) -> Optional[KnowledgeBase]:
        result = self.db.select_one(
            table=self.TABLE_NAME,
            where={"knowledge_base_id": knowledge_base_id, "is_active": 1},
        )
        return self._dict_to_model(result, KnowledgeBase)

    def get_by_id_for_user(self, knowledge_base_id: str, user_id: str) -> Optional[KnowledgeBase]:
        result = self.db.select_one(
            table=self.TABLE_NAME,
            where={
                "knowledge_base_id": knowledge_base_id,
                "user_id": user_id,
                "is_active": 1,
            },
        )
        return self._dict_to_model(result, KnowledgeBase)

    def get_default_by_user(self, user_id: str) -> Optional[KnowledgeBase]:
        result = self.db.select_one(
            table=self.TABLE_NAME,
            where={"user_id": user_id, "is_default": 1, "is_active": 1},
        )
        return self._dict_to_model(result, KnowledgeBase)

    def exists_by_name(self, user_id: str, name: str) -> bool:
        sql = f"SELECT 1 FROM {self.TABLE_NAME} WHERE user_id = %s AND name = %s AND is_active = 1 LIMIT 1"
        result = self.db.execute_query(sql, (user_id, name.strip()), fetch_one=True)
        return bool(result)

    def clear_default(self, user_id: str) -> int:
        return self.db.update_one(
            table=self.TABLE_NAME,
            data={"is_default": 0, "updated_at": utc_now()},
            where={"user_id": user_id, "is_active": 1},
        )

    def set_default_by_id(self, knowledge_base_id: str, user_id: str) -> bool:
        affected = self.db.update_one(
            table=self.TABLE_NAME,
            data={"is_default": 1, "updated_at": utc_now()},
            where={"knowledge_base_id": knowledge_base_id, "user_id": user_id, "is_active": 1},
        )
        return affected > 0

    def soft_delete_knowledge_base(self, knowledge_base_id: str, user_id: str) -> bool:
        affected = self.db.update_one(
            table=self.TABLE_NAME,
            data={"is_active": 0, "is_default": 0, "updated_at": utc_now()},
            where={"knowledge_base_id": knowledge_base_id, "user_id": user_id, "is_active": 1},
        )
        return affected > 0


_knowledge_base_repository: Optional[KnowledgeBaseRepository] = None


def get_knowledge_base_repository() -> KnowledgeBaseRepository:
    global _knowledge_base_repository
    if _knowledge_base_repository is None:
        _knowledge_base_repository = KnowledgeBaseRepository(get_database_manager())
    return _knowledge_base_repository
