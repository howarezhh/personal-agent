"""Document application service."""

from __future__ import annotations

import uuid

from backend.infrastructure.persistence import FileRepositoryAdapter, KnowledgeBaseRepositoryAdapter
from backend.infrastructure.storage import LocalFileStorageGateway
from backend.models.file import FileCreate, FileType
from backend.services.knowledge_base_service import (
    MAX_FILE_SIZE,
    delete_file_knowledge_data,
    format_file_as_document,
    get_file_type,
    get_upload_dir,
    is_knowledge_managed_file,
)
from backend.utils.logger import get_logger
from backend.utils.vector_db_client import get_vector_db_client


logger = get_logger(__name__)


class DocumentApplicationService:
    """Application-layer orchestration for upload and file-processing use cases."""

    def __init__(
        self,
        file_repo=None,
        knowledge_base_repo=None,
        storage_gateway=None,
        processor_agent=None,
        vector_store=None,
    ):
        self.file_repo = file_repo or FileRepositoryAdapter()
        self.knowledge_base_repo = knowledge_base_repo or KnowledgeBaseRepositoryAdapter()
        self.storage_gateway = storage_gateway or LocalFileStorageGateway()
        self.processor_agent = processor_agent
        self.vector_store = vector_store or get_vector_db_client()

    async def upload_document(self, *, user_id: str, upload_file, knowledge_base_id: str | None, request_id: str | None = None):
        knowledge_base = None
        if knowledge_base_id:
            knowledge_base = self.knowledge_base_repo.get_by_id_for_user(knowledge_base_id, user_id)
            if not knowledge_base:
                raise ValueError("知识库不存在或无权访问")

        file_content = await upload_file.read()
        file_size = len(file_content)
        if file_size <= 0:
            raise ValueError("上传文件不能为空")
        if file_size > MAX_FILE_SIZE:
            raise ValueError(f"文件大小超过限制，最大允许 {MAX_FILE_SIZE // (1024 * 1024)}MB")

        file_type = get_file_type(upload_file.filename)
        if getattr(file_type, "value", str(file_type)) == "other":
            raise ValueError("不支持的文件类型")

        self._validate_upload_content_type(upload_file, file_type)

        file_id = str(uuid.uuid4())
        logger.info(
            "Uploading document: request_id=%s user_id=%s knowledge_base_id=%s document_id=%s filename=%s",
            request_id,
            user_id,
            knowledge_base_id,
            file_id,
            upload_file.filename,
        )

        upload_dir = get_upload_dir(user_id=user_id, knowledge_base_id=knowledge_base_id)
        storage_path = self.storage_gateway.build_path(upload_dir, file_id, upload_file.filename)
        self.storage_gateway.write_bytes(storage_path, file_content)

        metadata = {
            "knowledge_managed": True,
            "knowledge_base_id": knowledge_base_id,
            "knowledge_base_name": knowledge_base.name if knowledge_base else None,
            "uploaded_via": "knowledge_api",
            "request_id": request_id,
            "document_id": file_id,
        }

        file_record = self.file_repo.create_file(
            FileCreate(
                file_id=file_id,
                user_id=user_id,
                original_filename=upload_file.filename,
                file_type=file_type,
                file_size=file_size,
                storage_path=storage_path,
                metadata=metadata,
            )
        )

        process_result = await self.processor_agent.process_file(file_record.file_id)
        updated_file = self.file_repo.get_file_by_id(file_record.file_id) or file_record

        if not process_result.get("success"):
            error_message = process_result.get("error") or getattr(updated_file, "error_message", None) or "文件处理失败"
            logger.error(
                "Document post-processing failed: request_id=%s user_id=%s knowledge_base_id=%s document_id=%s error=%s",
                request_id,
                user_id,
                knowledge_base_id,
                file_id,
                error_message,
            )
            raise RuntimeError(error_message)

        document = format_file_as_document(updated_file)
        document["process_result"] = process_result
        logger.info(
            "Uploaded document completed: request_id=%s user_id=%s knowledge_base_id=%s document_id=%s",
            request_id,
            user_id,
            knowledge_base_id,
            file_id,
        )
        return document

    def _validate_upload_content_type(self, upload_file, file_type) -> None:
        content_type = (getattr(upload_file, "content_type", None) or "").strip().lower()
        if not content_type:
            return

        allowed_content_types = {
            FileType.PDF: {"application/pdf"},
            FileType.DOCX: {
                "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
                "application/zip",
            },
            FileType.XLSX: {
                "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                "application/zip",
            },
            FileType.TEXT: {"text/plain"},
            FileType.MARKDOWN: {"text/markdown", "text/plain"},
            FileType.JSON: {"application/json", "text/plain"},
            FileType.XML: {"application/xml", "text/xml", "text/plain"},
            FileType.CODE: {
                "text/plain",
                "text/x-python",
                "application/javascript",
                "text/javascript",
                "text/typescript",
                "application/x-sh",
                "text/x-shellscript",
                "text/html",
                "text/css",
                "application/sql",
            },
        }

        expected_types = allowed_content_types.get(file_type)
        if expected_types and content_type not in expected_types:
            raise ValueError(
                f"上传文件 MIME 类型与扩展名不匹配: filename={upload_file.filename}, content_type={content_type}"
            )

    def list_documents(self, *, user_id: str, knowledge_base_id: str | None):
        documents = [
            format_file_as_document(file_record)
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
            raise FileNotFoundError("文档不存在")
        if file_record.user_id != user_id:
            raise PermissionError("无权删除该知识库文档")

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
        if isinstance(cleanup_result, dict):
            cleanup_result.setdefault("request_id", request_id)
            cleanup_result.setdefault("document_id", document_id)
        return cleanup_result
