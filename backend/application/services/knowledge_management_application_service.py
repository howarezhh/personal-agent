from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Optional

from backend.application.services.document_query_application_service import DocumentQueryApplicationService
from backend.application.services.document_upload_application_service import DocumentUploadApplicationService
from backend.application.services.document_vector_rebuild_application_service import DocumentVectorRebuildApplicationService
from backend.application.services.knowledge_base_crud_application_service import KnowledgeBaseCrudApplicationService
from backend.application.services.knowledge_search_application_service import KnowledgeSearchApplicationService


@dataclass
class PendingDocumentUpload:
    file_id: str
    document: dict[str, Any]


@dataclass
class StartedFullVectorRebuildTask:
    task_id: str
    knowledge_base_id: Optional[str]
    task: dict[str, Any]


class KnowledgeManagementApplicationService:
    """知识管理应用服务。

    该服务负责组合知识库 CRUD、检索、文档上传、文档查询与向量重建，
    对外提供统一的知识管理用例入口。
    """

    def __init__(
        self,
        *,
        knowledge_base_crud_service: KnowledgeBaseCrudApplicationService | None = None,
        knowledge_search_service: KnowledgeSearchApplicationService | None = None,
        document_upload_service: DocumentUploadApplicationService | None = None,
        document_query_service: DocumentQueryApplicationService | None = None,
        document_vector_rebuild_service: DocumentVectorRebuildApplicationService | None = None,
    ):
        # 采用延迟初始化，避免轻量接口在首个请求时拉起检索、向量与重排组件。
        self.knowledge_base_crud_service = knowledge_base_crud_service
        self.knowledge_search_service = knowledge_search_service
        self.document_upload_service = document_upload_service
        self.document_query_service = document_query_service
        self.document_vector_rebuild_service = document_vector_rebuild_service

    def _get_knowledge_base_crud_service(self) -> KnowledgeBaseCrudApplicationService:
        if self.knowledge_base_crud_service is None:
            from backend.application.service_factory import build_knowledge_base_crud_application_service

            self.knowledge_base_crud_service = build_knowledge_base_crud_application_service()
        return self.knowledge_base_crud_service

    def _get_knowledge_search_service(self) -> KnowledgeSearchApplicationService:
        if self.knowledge_search_service is None:
            from backend.application.service_factory import build_knowledge_search_application_service

            self.knowledge_search_service = build_knowledge_search_application_service()
        return self.knowledge_search_service

    def _get_document_upload_service(self) -> DocumentUploadApplicationService:
        if self.document_upload_service is None:
            from backend.application.service_factory import build_document_upload_application_service

            self.document_upload_service = build_document_upload_application_service()
        return self.document_upload_service

    def _get_document_query_service(self) -> DocumentQueryApplicationService:
        if self.document_query_service is None:
            from backend.application.service_factory import build_document_query_application_service

            self.document_query_service = build_document_query_application_service()
        return self.document_query_service

    def _get_document_vector_rebuild_service(self) -> DocumentVectorRebuildApplicationService:
        if self.document_vector_rebuild_service is None:
            from backend.application.service_factory import build_document_vector_rebuild_application_service

            self.document_vector_rebuild_service = build_document_vector_rebuild_application_service()
        return self.document_vector_rebuild_service

    def list_knowledge_bases(self, *, user_id: str) -> dict[str, Any]:
        knowledge_bases, total = self._get_knowledge_base_crud_service().list_knowledge_bases(user_id=user_id)
        return {
            'knowledge_bases': [item.to_dict() for item in knowledge_bases],
            'total': total,
        }

    def create_knowledge_base(self, *, user_id: str, name: str, description: str | None = None) -> dict[str, Any]:
        knowledge_base = self._get_knowledge_base_crud_service().create_knowledge_base(
            user_id=user_id,
            name=name,
            description=description,
        )
        return knowledge_base.to_dict()

    def delete_knowledge_base(self, *, knowledge_base_id: str, user_id: str, request_id: str | None = None) -> dict[str, Any]:
        knowledge_base = self._get_knowledge_base_crud_service().delete_knowledge_base(
            knowledge_base_id=knowledge_base_id,
            user_id=user_id,
            request_id=request_id,
        )
        return knowledge_base.to_dict()

    def _resolve_target_knowledge_base_id(self, *, user_id: str, knowledge_base_id: str | None) -> str:
        knowledge_base = (
            self._get_knowledge_base_crud_service().get_user_knowledge_base(user_id=user_id, knowledge_base_id=knowledge_base_id)
            if knowledge_base_id
            else self._get_knowledge_base_crud_service().ensure_default_for_user(user_id=user_id)
        )
        if knowledge_base is None:
            raise FileNotFoundError('Knowledge base not found or inaccessible')
        return knowledge_base.knowledge_base_id

    async def create_document_upload(
        self,
        *,
        user_id: str,
        upload_file,
        knowledge_base_id: str | None,
        request_id: str | None = None,
        idempotency_key: str | None = None,
    ) -> PendingDocumentUpload:
        target_knowledge_base_id = self._resolve_target_knowledge_base_id(
            user_id=user_id,
            knowledge_base_id=knowledge_base_id,
        )
        file_record = await self._get_document_upload_service().create_document_upload(
            user_id=user_id,
            upload_file=upload_file,
            knowledge_base_id=target_knowledge_base_id,
            request_id=request_id,
            idempotency_key=idempotency_key,
        )
        document = self._get_document_query_service().get_document_status(document_id=file_record.file_id, user_id=user_id)
        return PendingDocumentUpload(file_id=file_record.file_id, document=document)

    async def process_uploaded_document(self, file_id: str, request_id: str | None = None) -> dict[str, Any]:
        return await self._get_document_upload_service().process_uploaded_document(file_id, request_id=request_id)

    async def upload_documents_batch(
        self,
        *,
        user_id: str,
        upload_files: list,
        knowledge_base_id: str | None,
        request_id: str | None = None,
    ) -> dict[str, Any]:
        if not upload_files:
            raise ValueError('Upload file list cannot be empty')
        target_knowledge_base_id = self._resolve_target_knowledge_base_id(
            user_id=user_id,
            knowledge_base_id=knowledge_base_id,
        )
        return await self._get_document_upload_service().upload_documents_batch(
            user_id=user_id,
            upload_files=upload_files,
            knowledge_base_id=target_knowledge_base_id,
            request_id=request_id,
        )

    def get_document_status(self, *, document_id: str, user_id: str) -> dict[str, Any]:
        return self._get_document_query_service().get_document_status(document_id=document_id, user_id=user_id)

    def list_documents(self, *, user_id: str, knowledge_base_id: str | None) -> dict[str, Any]:
        validated_knowledge_base_id = knowledge_base_id
        if knowledge_base_id:
            validated_knowledge_base_id = self._resolve_target_knowledge_base_id(
                user_id=user_id,
                knowledge_base_id=knowledge_base_id,
            )
        documents = self._get_document_query_service().list_documents(
            user_id=user_id,
            knowledge_base_id=validated_knowledge_base_id,
        )
        return {'documents': documents, 'total': len(documents)}

    def delete_document(self, *, document_id: str, user_id: str, request_id: str | None = None) -> dict[str, Any]:
        return self._get_document_query_service().delete_document(
            document_id=document_id,
            user_id=user_id,
            request_id=request_id,
        )

    def retry_pending_vectorizations(
        self,
        *,
        user_id: str,
        knowledge_base_id: str | None,
        request_id: str | None = None,
    ) -> dict[str, Any]:
        validated_knowledge_base_id = knowledge_base_id
        if knowledge_base_id:
            validated_knowledge_base_id = self._resolve_target_knowledge_base_id(
                user_id=user_id,
                knowledge_base_id=knowledge_base_id,
            )
        return self._get_document_vector_rebuild_service().retry_pending_vectorizations(
            user_id=user_id,
            knowledge_base_id=validated_knowledge_base_id,
            request_id=request_id,
        )

    def start_full_vector_rebuild_task(
        self,
        *,
        user_id: str,
        knowledge_base_id: str | None,
        request_id: str | None = None,
        idempotency_key: str | None = None,
    ) -> StartedFullVectorRebuildTask:
        validated_knowledge_base_id = knowledge_base_id
        if knowledge_base_id:
            validated_knowledge_base_id = self._resolve_target_knowledge_base_id(
                user_id=user_id,
                knowledge_base_id=knowledge_base_id,
            )
        task = self._get_document_vector_rebuild_service().start_full_vector_rebuild_task(
            user_id=user_id,
            knowledge_base_id=validated_knowledge_base_id,
            request_id=request_id,
            idempotency_key=idempotency_key,
        )
        return StartedFullVectorRebuildTask(
            task_id=task['task_id'],
            knowledge_base_id=validated_knowledge_base_id,
            task=task,
        )

    def run_full_vector_rebuild_task(
        self,
        *,
        task_id: str,
        user_id: str,
        knowledge_base_id: str | None,
        request_id: str | None = None,
    ) -> None:
        self._get_document_vector_rebuild_service().run_full_vector_rebuild_task(
            task_id=task_id,
            user_id=user_id,
            knowledge_base_id=knowledge_base_id,
            request_id=request_id,
        )

    def get_full_vector_rebuild_task(self, *, task_id: str, user_id: str) -> dict[str, Any]:
        return self._get_document_vector_rebuild_service().get_full_vector_rebuild_task(task_id=task_id, user_id=user_id)

    def rebuild_all_vectors_for_current_model(
        self,
        *,
        user_id: str,
        knowledge_base_id: str | None,
        request_id: str | None = None,
    ) -> dict[str, Any]:
        validated_knowledge_base_id = knowledge_base_id
        if knowledge_base_id:
            validated_knowledge_base_id = self._resolve_target_knowledge_base_id(
                user_id=user_id,
                knowledge_base_id=knowledge_base_id,
            )
        return self._get_document_vector_rebuild_service().rebuild_all_vectors_for_current_model(
            user_id=user_id,
            knowledge_base_id=validated_knowledge_base_id,
            request_id=request_id,
        )

    async def search_knowledge(
        self,
        *,
        user_id: str,
        query: str,
        top_k: int,
        knowledge_base_id: str | None,
        file_type: str | None = None,
        retrieval_options: dict[str, Any] | None = None,
        request_id: str | None = None,
    ) -> dict[str, Any]:
        results = await self._get_knowledge_search_service().search_knowledge(
            user_id=user_id,
            query=query,
            top_k=top_k,
            knowledge_base_id=knowledge_base_id,
            file_type=file_type,
            retrieval_options=retrieval_options,
            request_id=request_id,
        )
        return {
            'query': query,
            'knowledge_base_id': knowledge_base_id,
            'results': results,
            'total': len(results),
        }
