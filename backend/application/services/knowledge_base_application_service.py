"""Knowledge-base application service."""

from __future__ import annotations

from backend.infrastructure.persistence import KnowledgeBaseRepositoryAdapter
from backend.infrastructure.vector_store import EmbeddingGatewayAdapter, VectorStoreGatewayAdapter
from backend.models.knowledge_base import KnowledgeBaseCreate
from backend.utils.logger import get_logger


logger = get_logger(__name__)

DEFAULT_KNOWLEDGE_BASE_NAME = "默认知识库"
DEFAULT_KNOWLEDGE_BASE_DESCRIPTION = "系统自动创建的默认知识库"


class KnowledgeBaseApplicationService:
    """Application-layer orchestration for knowledge-base use cases."""

    def __init__(self, knowledge_repo=None, document_service=None, embedding_gateway=None, vector_store=None):
        self.knowledge_repo = knowledge_repo or KnowledgeBaseRepositoryAdapter()
        self.document_service = document_service
        self.embedding_gateway = embedding_gateway or EmbeddingGatewayAdapter()
        self.vector_store = vector_store or VectorStoreGatewayAdapter()

    def list_knowledge_bases(self, *, user_id: str):
        self.ensure_default_for_user(user_id=user_id)
        items = self.knowledge_repo.list_by_user(user_id)
        return items, len(items)

    def create_knowledge_base(self, *, user_id: str, name: str, description: str | None):
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
        knowledge_base = self.get_user_knowledge_base(user_id=user_id, knowledge_base_id=knowledge_base_id)
        if not knowledge_base:
            raise ValueError("知识库不存在或无权访问")

        logger.info(
            "Deleting knowledge base: request_id=%s user_id=%s knowledge_base_id=%s",
            request_id,
            user_id,
            knowledge_base_id,
        )

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

    def get_user_knowledge_base(self, *, user_id: str, knowledge_base_id: str):
        return self.knowledge_repo.get_by_id_for_user(knowledge_base_id, user_id)

    def search_knowledge(self, *, user_id: str, query: str, top_k: int, knowledge_base_id: str | None, request_id: str | None = None):
        where_filter = {"user_id": user_id}
        if knowledge_base_id:
            knowledge_base = self.get_user_knowledge_base(user_id=user_id, knowledge_base_id=knowledge_base_id)
            if not knowledge_base:
                raise ValueError("知识库不存在或无权访问")
            where_filter["knowledge_base_id"] = knowledge_base_id

        logger.info(
            "Searching knowledge: request_id=%s user_id=%s knowledge_base_id=%s top_k=%s",
            request_id,
            user_id,
            knowledge_base_id,
            top_k,
        )

        query_embedding = self.embedding_gateway.embed_text(query)
        if query_embedding is None:
            raise RuntimeError("生成查询向量失败")

        max_candidates = min(max(top_k * 5, top_k), 50)
        results = self.vector_store.query(
            query_embeddings=[query_embedding],
            n_results=max_candidates,
            where=where_filter,
        )

        search_results = []
        ids_list = results.get("ids", [[]]) or [[]]
        documents_list = results.get("documents", [[]]) or [[]]
        distances_list = results.get("distances", [[]]) or [[]]
        metadatas_list = results.get("metadatas", [[]]) or [[]]

        if ids_list and ids_list[0]:
            for index, chunk_id in enumerate(ids_list[0]):
                metadata = metadatas_list[0][index] if metadatas_list and len(metadatas_list[0]) > index else {}
                if not isinstance(metadata, dict) or not metadata.get("document_id"):
                    continue

                document = documents_list[0][index] if documents_list and len(documents_list[0]) > index else ""
                distance = distances_list[0][index] if distances_list and len(distances_list[0]) > index else 1.0
                similarity_score = 1.0 / (1.0 + distance)
                search_results.append(
                    {
                        "id": chunk_id,
                        "content": document,
                        "score": similarity_score,
                        "source": metadata.get("file_name") or metadata.get("original_filename") or metadata.get("source") or "Unknown",
                        "metadata": metadata,
                    }
                )
                if len(search_results) >= top_k:
                    break
        return search_results
