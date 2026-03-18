from __future__ import annotations

import uuid
from typing import Any

from backend.application.services.document_service_support import DocumentServiceSupport, logger
from backend.domain.knowledge import MAX_FILE_SIZE, get_file_type, get_upload_dir
from backend.models.file import FileCreate


class DocumentUploadApplicationService(DocumentServiceSupport):
    async def upload_document(self, *, user_id: str, upload_file, knowledge_base_id: str | None, request_id: str | None = None):
        file_record = await self.create_document_upload(
            user_id=user_id,
            upload_file=upload_file,
            knowledge_base_id=knowledge_base_id,
            request_id=request_id,
        )
        process_result = await self.process_uploaded_document(file_record.file_id, request_id=request_id)
        if not process_result.get("success"):
            raise RuntimeError(process_result.get("error") or "鏂囦欢澶勭悊澶辫触")

        updated_file = self.file_repo.get_file_by_id(file_record.file_id)
        if not updated_file:
            raise RuntimeError("鏂囦欢澶勭悊澶辫触")

        document = self._build_document_snapshot(updated_file)
        document["process_result"] = process_result
        return document


    async def create_document_upload(self, *, user_id: str, upload_file, knowledge_base_id: str | None, request_id: str | None = None):
        knowledge_base = None
        if knowledge_base_id:
            knowledge_base = self.knowledge_base_repo.get_by_id_for_user(knowledge_base_id, user_id)
            if not knowledge_base:
                raise ValueError("Knowledge base not found or inaccessible")

        file_content = await upload_file.read()
        file_size = len(file_content)
        if file_size <= 0:
            raise ValueError("涓婁紶鏂囦欢涓嶈兘涓虹┖")
        if file_size > MAX_FILE_SIZE:
            raise ValueError(f"鏂囦欢澶у皬瓒呰繃闄愬埗锛屾渶澶у厑璁?{MAX_FILE_SIZE // (1024 * 1024)}MB")

        file_type = get_file_type(upload_file.filename)
        if getattr(file_type, "value", str(file_type)) == "other":
            raise ValueError("涓嶆敮鎸佺殑鏂囦欢绫诲瀷")

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
            "request_id": request_id,
            "document_id": file_id,
            "processing_stage": "pending",
            "processing_progress": 0,
        }

        try:
            self.storage_gateway.write_bytes(storage_path, file_content)
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

        error_message = process_result.get("error") or getattr(updated_file, "error_message", None) or "鏂囦欢澶勭悊澶辫触"
        failed_snapshot = self._build_document_snapshot(updated_file)
        failed_snapshot["status"] = "failed"
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


