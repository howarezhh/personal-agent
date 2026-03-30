from __future__ import annotations

from backend.application.services.document_service_support import (
    DocumentServiceSupport,
    _recent_document_statuses,
    logger,
)
from backend.domain.knowledge import delete_file_knowledge_data, is_knowledge_managed_file


class DocumentQueryApplicationService(DocumentServiceSupport):
    def get_document_status(self, *, document_id: str, user_id: str) -> dict[str, Any]:
        self._purge_expired_document_statuses()

        file_record = self.file_repo.get_file_by_id(document_id)
        if file_record and is_knowledge_managed_file(file_record):
            if file_record.user_id != user_id:
                raise PermissionError("You do not have permission to access this document")
            document = self._build_document_snapshot(file_record)
            self._remember_document_status(document)
            return document

        cached = _recent_document_statuses.get(document_id)
        if cached and cached.get("user_id") == user_id:
            return {key: value for key, value in cached.items() if key != "cached_at"}

        raise FileNotFoundError("Document not found")


    def list_documents(self, *, user_id: str, knowledge_base_id: str | None):
        documents = [
            self._build_document_snapshot(file_record)
            for file_record in self.file_repo.get_files_by_user_id(user_id)
            if is_knowledge_managed_file(file_record)
        ]
        if knowledge_base_id:
            documents = [item for item in documents if item.get("knowledge_base_id") == knowledge_base_id]
        documents.sort(key=lambda item: item.get("created_at") or item.get("upload_time") or "", reverse=True)
        return documents


    def delete_document(self, *, document_id: str, user_id: str, request_id: str | None = None):
        file_record = self.file_repo.get_file_by_id(document_id)
        if not file_record or not is_knowledge_managed_file(file_record):
            raise FileNotFoundError("Document not found")
        if file_record.user_id != user_id:
            raise PermissionError("You do not have permission to delete this document")

        knowledge_base_id = None
        metadata = getattr(file_record, "metadata", None)
        if isinstance(metadata, dict):
            knowledge_base_id = metadata.get("knowledge_base_id")

        logger.info(
            "Deleting document: request_id=%s user_id=%s knowledge_base_id=%s document_id=%s",
            request_id,
            user_id,
            knowledge_base_id,
            document_id,
        )

        cleanup_result = delete_file_knowledge_data(
            file_id=document_id,
            vector_store=self.vector_store,
            log=logger,
        )
        self.storage_gateway.delete(file_record.storage_path)
        self.file_repo.delete_file(document_id)
        _recent_document_statuses.pop(document_id, None)
        if isinstance(cleanup_result, dict):
            cleanup_result.setdefault("request_id", request_id)
            cleanup_result.setdefault("document_id", document_id)
        return cleanup_result


