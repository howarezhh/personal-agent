from __future__ import annotations

import uuid
from os import SEEK_END
from typing import Any

from backend.contracts.async_task import AsyncTaskStatus
from backend.application.services.document_service_support import DocumentServiceSupport, logger
from backend.domain.knowledge import MAX_FILE_SIZE, get_file_type, get_upload_dir
from backend.models.file import FileCreate


class DocumentUploadApplicationService(DocumentServiceSupport):
    async def _measure_upload_file_size(self, upload_file) -> int:
        file_obj = getattr(upload_file, "file", None)
        if file_obj is not None and hasattr(file_obj, "tell") and hasattr(file_obj, "seek"):
            current_position = file_obj.tell()
            file_obj.seek(0, SEEK_END)
            file_size = int(file_obj.tell() or 0)
            file_obj.seek(0)
            if hasattr(upload_file, "seek"):
                await upload_file.seek(0)
            else:
                file_obj.seek(current_position)
            return file_size

        file_content = await upload_file.read()
        if hasattr(upload_file, "seek"):
            await upload_file.seek(0)
        return len(file_content)

    async def _persist_upload_file(self, *, upload_file, storage_path: str) -> None:
        file_obj = getattr(upload_file, "file", None)
        if file_obj is not None and hasattr(self.storage_gateway, "write_fileobj"):
            file_obj.seek(0)
            self.storage_gateway.write_fileobj(storage_path, file_obj)
            if hasattr(upload_file, "seek"):
                await upload_file.seek(0)
            return

        file_content = await upload_file.read()
        if hasattr(upload_file, "seek"):
            await upload_file.seek(0)
        self.storage_gateway.write_bytes(storage_path, file_content)

    async def upload_document(
        self,
        *,
        user_id: str,
        upload_file,
        knowledge_base_id: str | None,
        request_id: str | None = None,
        idempotency_key: str | None = None,
    ):
        # 同一知识库下若存在同名文档，则在新文档处理成功后自动替换旧记录，避免列表出现重复文件。
        duplicate_file_records = self._find_same_name_documents(
            user_id=user_id,
            knowledge_base_id=knowledge_base_id,
            file_name=getattr(upload_file, "filename", ""),
        )

        file_record = await self.create_document_upload(
            user_id=user_id,
            upload_file=upload_file,
            knowledge_base_id=knowledge_base_id,
            request_id=request_id,
            idempotency_key=idempotency_key,
        )
        duplicate_file_records = [
            duplicate_file_record
            for duplicate_file_record in duplicate_file_records
            if getattr(duplicate_file_record, "file_id", None) != file_record.file_id
        ]

        process_result = await self.process_uploaded_document(file_record.file_id, request_id=request_id)
        if not process_result.get("success"):
            raise RuntimeError(process_result.get("error") or "文件处理失败")

        if duplicate_file_records:
            self._delete_replaced_documents(
                file_records=duplicate_file_records,
                request_id=request_id,
                replacement_document_id=file_record.file_id,
            )

        updated_file = self.file_repo.get_file_by_id(file_record.file_id)
        if not updated_file:
            raise RuntimeError("文件处理失败")

        document = self._build_document_snapshot(updated_file)
        document["process_result"] = process_result
        return document

    async def create_document_upload(
        self,
        *,
        user_id: str,
        upload_file,
        knowledge_base_id: str | None,
        request_id: str | None = None,
        idempotency_key: str | None = None,
    ):
        idempotent_record = self._get_idempotent_record(
            namespace="document_upload",
            user_id=user_id,
            idempotency_key=idempotency_key,
        )
        if idempotent_record:
            existing_file_id = idempotent_record.get("file_id")
            existing_file = self.file_repo.get_file_by_id(existing_file_id) if existing_file_id else None
            if existing_file:
                return existing_file

        knowledge_base = None
        if knowledge_base_id:
            knowledge_base = self.knowledge_base_repo.get_by_id_for_user(knowledge_base_id, user_id)
            if not knowledge_base:
                raise ValueError("Knowledge base not found or inaccessible")

        file_size = await self._measure_upload_file_size(upload_file)
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
        metadata = {
            "knowledge_managed": True,
            "knowledge_base_id": knowledge_base_id,
            "knowledge_base_name": knowledge_base.name if knowledge_base else None,
            "uploaded_via": "knowledge_api",
            "upload_content_type": getattr(upload_file, "content_type", None),
            "idempotency_key": idempotency_key,
            "request_id": request_id,
            "document_id": file_id,
            "processing_stage": "pending",
            "processing_progress": 0,
            "task_status": AsyncTaskStatus.PENDING.value,
        }

        try:
            await self._persist_upload_file(upload_file=upload_file, storage_path=storage_path)
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
            self._remember_idempotent_record(
                namespace="document_upload",
                user_id=user_id,
                idempotency_key=idempotency_key,
                payload={
                    "file_id": file_id,
                    "knowledge_base_id": knowledge_base_id,
                    "file_name": upload_file.filename,
                },
            )
            self._remember_document_status(self._build_document_snapshot(file_record))
            return file_record
        except Exception:
            self._cleanup_failed_upload(
                file_id=file_id,
                storage_path=storage_path,
                file_record=None,
                request_id=request_id,
            )
            raise


    async def process_uploaded_document(self, file_id: str, request_id: str | None = None) -> dict[str, Any]:
        file_record = self.file_repo.get_file_by_id(file_id)
        if not file_record:
            return {"success": False, "error": "File not found"}

        process_result = await self.processor_agent.process_file(file_id)
        updated_file = self.file_repo.get_file_by_id(file_id) or file_record

        if process_result.get("success"):
            document = self._build_document_snapshot(updated_file)
            self._remember_document_status(document)
            logger.info(
                "Uploaded document completed: request_id=%s user_id=%s knowledge_base_id=%s document_id=%s",
                request_id,
                updated_file.user_id,
                (updated_file.metadata or {}).get("knowledge_base_id") if isinstance(updated_file.metadata, dict) else None,
                file_id,
            )
            return process_result

        error_message = process_result.get("error") or getattr(updated_file, "error_message", None) or "文件处理失败"
        failed_snapshot = self._build_document_snapshot(updated_file)
        failed_snapshot["status"] = AsyncTaskStatus.FAILED.value
        failed_snapshot["error_message"] = error_message
        failed_snapshot["processing_stage"] = failed_snapshot.get("processing_stage") or "failed"
        failed_snapshot["processing_progress"] = failed_snapshot.get("processing_progress") or 100
        self._remember_document_status(failed_snapshot)
        self._cleanup_failed_upload(
            file_id=file_id,
            storage_path=getattr(updated_file, "storage_path", None),
            file_record=updated_file,
            request_id=request_id,
        )
        return {"success": False, "error": error_message}


    async def upload_documents_batch(
        self,
        *,
        user_id: str,
        upload_files: list,
        knowledge_base_id: str | None,
        request_id: str | None = None,
    ) -> dict[str, Any]:
        results: list[dict[str, Any]] = []

        for upload_file in upload_files:
            try:
                document = await self.upload_document(
                    user_id=user_id,
                    upload_file=upload_file,
                    knowledge_base_id=knowledge_base_id,
                    request_id=request_id,
                )
                results.append(
                    {
                        "file_name": document["file_name"],
                        "success": True,
                        "document": document,
                        "error": None,
                    }
                )
            except Exception as error:
                results.append(
                    {
                        "file_name": getattr(upload_file, "filename", None) or "unknown",
                        "success": False,
                        "document": None,
                        "error": str(error),
                    }
                )

        success_count = sum(1 for item in results if item["success"])
        failed_count = len(results) - success_count
        return {
            "total": len(upload_files),
            "success_count": success_count,
            "failed_count": failed_count,
            "results": results,
        }


