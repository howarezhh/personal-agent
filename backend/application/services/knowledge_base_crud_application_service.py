from __future__ import annotations

from backend.application.services.knowledge_base_service_support import (
    DEFAULT_KNOWLEDGE_BASE_DESCRIPTION,
    DEFAULT_KNOWLEDGE_BASE_NAME,
    KnowledgeBaseServiceSupport,
    logger,
)
from backend.models.knowledge_base import KnowledgeBaseCreate


class KnowledgeBaseCrudApplicationService(KnowledgeBaseServiceSupport):
    """知识库 CRUD 应用服务。"""

    def list_knowledge_bases(self, *, user_id: str):
        """列出用户知识库，并确保默认知识库存在。"""
        self.ensure_default_for_user(user_id=user_id)
        items = self.knowledge_repo.list_by_user(user_id)
        return items, len(items)

    def create_knowledge_base(self, *, user_id: str, name: str, description: str | None):
        """创建知识库，并处理默认知识库规则。"""
        knowledge_base_create = KnowledgeBaseCreate(user_id=user_id, name=name, description=description)
        is_valid, error_msg = knowledge_base_create.validate()
        if not is_valid:
            raise ValueError(error_msg)

        if self.knowledge_repo.exists_by_name(user_id, knowledge_base_create.name):
            raise ValueError(f"知识库名称 '{knowledge_base_create.name.strip()}' 已存在")

        is_first = len(self.knowledge_repo.list_by_user(user_id)) == 0
        if is_first:
            self.knowledge_repo.clear_default(user_id)

        return self.knowledge_repo.create_knowledge_base(
            KnowledgeBaseCreate(
                user_id=user_id,
                name=knowledge_base_create.name,
                description=knowledge_base_create.description,
                is_default=is_first,
            )
        )

    def ensure_default_for_user(self, *, user_id: str):
        """确保用户始终拥有一个默认知识库。"""
        default_base = self.knowledge_repo.get_default_by_user(user_id)
        if default_base:
            return default_base

        existing = self.knowledge_repo.list_by_user(user_id)
        if existing:
            first_base = existing[0]
            self.knowledge_repo.clear_default(user_id)
            self.knowledge_repo.set_default_by_id(first_base.knowledge_base_id, user_id)
            return self.knowledge_repo.get_by_id_for_user(first_base.knowledge_base_id, user_id) or first_base

        return self.create_knowledge_base(
            user_id=user_id,
            name=DEFAULT_KNOWLEDGE_BASE_NAME,
            description=DEFAULT_KNOWLEDGE_BASE_DESCRIPTION,
        )

    def delete_knowledge_base(self, *, knowledge_base_id: str, user_id: str, request_id: str | None = None):
        """删除知识库，并联动删除该库下的文档。"""
        knowledge_base = self.get_user_knowledge_base(user_id=user_id, knowledge_base_id=knowledge_base_id)
        if not knowledge_base:
            raise ValueError("知识库不存在或无权访问")

        logger.info(
            "Deleting knowledge base: request_id=%s user_id=%s knowledge_base_id=%s",
            request_id,
            user_id,
            knowledge_base_id,
        )

        # 文档查询服务仅在真正删除知识库时才需要，避免列表接口提前初始化整套文档链路。
        if self.document_service is None:
            from backend.application.service_factory import build_document_query_application_service

            self.document_service = build_document_query_application_service()

        if self.document_service is not None:
            documents = self.document_service.list_documents(user_id=user_id, knowledge_base_id=knowledge_base_id)
            for document in documents:
                self.document_service.delete_document(
                    document_id=document["document_id"],
                    user_id=user_id,
                    request_id=request_id,
                )

        self.knowledge_repo.soft_delete_knowledge_base(knowledge_base_id, user_id)

        if knowledge_base.is_default:
            remaining = self.knowledge_repo.list_by_user(user_id)
            remaining = [item for item in remaining if item.knowledge_base_id != knowledge_base_id]
            if remaining:
                self.knowledge_repo.clear_default(user_id)
                self.knowledge_repo.set_default_by_id(remaining[0].knowledge_base_id, user_id)

        return knowledge_base
