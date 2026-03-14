"""Document application service."""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta
from threading import Lock
from typing import Any

from backend.infrastructure.persistence import FileRepositoryAdapter, KnowledgeBaseRepositoryAdapter
from backend.infrastructure.storage import LocalFileStorageGateway
from backend.models.file import FileChunk, FileCreate, FileType, FileUpdate
from backend.services.knowledge_base_service import (
    MAX_FILE_SIZE,
    build_chunk_vector_metadata,
    delete_file_knowledge_data,
    format_file_as_document,
    get_file_type,
    get_upload_dir,
    is_knowledge_managed_file,
)
from backend.utils.embedding_client import get_embedding_client
from backend.utils.logger import get_logger
from backend.utils.vector_db_client import get_vector_db_client


logger = get_logger(__name__)
_STATUS_CACHE_TTL = timedelta(minutes=10)
_FULL_REBUILD_TASK_TTL = timedelta(hours=6)
_recent_document_statuses: dict[str, dict[str, Any]] = {}
_full_vector_rebuild_tasks: dict[str, dict[str, Any]] = {}
_full_vector_rebuild_tasks_lock = Lock()


def _utcnow_iso() -> str:
    return datetime.utcnow().isoformat(timespec="seconds") + "Z"


def _clone_full_rebuild_task(task: dict[str, Any]) -> dict[str, Any]:
    snapshot = {key: value for key, value in task.items() if not key.startswith("_")}
    snapshot["details"] = [dict(item) for item in task.get("details", [])]
    return snapshot


class DocumentApplicationService:
    """Application-layer orchestration for upload and file-processing use cases."""

    def __init__(
        self,
        file_repo=None,
        knowledge_base_repo=None,
        storage_gateway=None,
        processor_agent=None,
        vector_store=None,
        db_manager=None,
    ):
        self.file_repo = file_repo or FileRepositoryAdapter()
        self.knowledge_base_repo = knowledge_base_repo or KnowledgeBaseRepositoryAdapter()
        self.storage_gateway = storage_gateway or LocalFileStorageGateway()
        self.processor_agent = processor_agent
        self.vector_store = vector_store or get_vector_db_client()
        self._db_manager = db_manager

    @property
    def db_manager(self):
        if self._db_manager is None:
            from backend.database.database_manager import get_database_manager

            self._db_manager = get_database_manager()
        return self._db_manager

    async def upload_document(self, *, user_id: str, upload_file, knowledge_base_id: str | None, request_id: str | None = None):
        file_record = await self.create_document_upload(
            user_id=user_id,
            upload_file=upload_file,
            knowledge_base_id=knowledge_base_id,
            request_id=request_id,
        )
        process_result = await self.process_uploaded_document(file_record.file_id, request_id=request_id)
        if not process_result.get("success"):
            raise RuntimeError(process_result.get("error") or "文件处理失败")

        updated_file = self.file_repo.get_file_by_id(file_record.file_id)
        if not updated_file:
            raise RuntimeError("文件处理失败")

        document = self._build_document_snapshot(updated_file)
        document["process_result"] = process_result
        return document

    async def create_document_upload(self, *, user_id: str, upload_file, knowledge_base_id: str | None, request_id: str | None = None):
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
            return {"success": False, "error": "文档不存在"}

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

    def get_document_status(self, *, document_id: str, user_id: str) -> dict[str, Any]:
        self._purge_expired_document_statuses()

        file_record = self.file_repo.get_file_by_id(document_id)
        if file_record and is_knowledge_managed_file(file_record):
            if file_record.user_id != user_id:
                raise PermissionError("无权访问该知识库文档")
            document = self._build_document_snapshot(file_record)
            self._remember_document_status(document)
            return document

        cached = _recent_document_statuses.get(document_id)
        if cached and cached.get("user_id") == user_id:
            return {key: value for key, value in cached.items() if key != "cached_at"}

        raise FileNotFoundError("文档不存在")

    def _remember_document_status(self, document: dict[str, Any]) -> None:
        snapshot = dict(document)
        snapshot["cached_at"] = datetime.utcnow()
        _recent_document_statuses[snapshot["document_id"]] = snapshot

    def _purge_expired_document_statuses(self) -> None:
        now = datetime.utcnow()
        expired_ids = [
            document_id
            for document_id, snapshot in _recent_document_statuses.items()
            if now - snapshot.get("cached_at", now) > _STATUS_CACHE_TTL
        ]
        for document_id in expired_ids:
            _recent_document_statuses.pop(document_id, None)

    def _cleanup_failed_upload(
        self,
        *,
        file_id: str | None,
        storage_path: str | None,
        file_record,
        request_id: str | None,
    ) -> None:
        if file_id:
            try:
                delete_file_knowledge_data(
                    file_id=file_id,
                    vector_store=self.vector_store,
                    log=logger,
                )
            except Exception as cleanup_error:
                logger.error(
                    "Failed to cleanup knowledge data for failed upload: request_id=%s document_id=%s error=%s",
                    request_id,
                    file_id,
                    cleanup_error,
                    exc_info=True,
                )

        target_path = storage_path or getattr(file_record, "storage_path", None)
        if target_path:
            try:
                self.storage_gateway.delete(target_path)
            except Exception as cleanup_error:
                logger.error(
                    "Failed to delete local file for failed upload: request_id=%s document_id=%s path=%s error=%s",
                    request_id,
                    file_id,
                    target_path,
                    cleanup_error,
                    exc_info=True,
                )

        target_file_id = file_id or getattr(file_record, "file_id", None)
        if target_file_id:
            try:
                existing_file = self.file_repo.get_file_by_id(target_file_id)
                if existing_file:
                    self.file_repo.delete_file(target_file_id)
            except Exception as cleanup_error:
                logger.error(
                    "Failed to delete file record for failed upload: request_id=%s document_id=%s error=%s",
                    request_id,
                    target_file_id,
                    cleanup_error,
                    exc_info=True,
                )

    def _build_document_snapshot(self, file_record) -> dict[str, Any]:
        document = format_file_as_document(file_record)
        document.update(self._get_vectorization_stats(file_record.file_id))
        return document

    def _get_vectorization_stats(self, file_id: str) -> dict[str, Any]:
        try:
            result = self.db_manager.execute_query(
                """
                SELECT
                    COUNT(*) AS total_chunks,
                    COALESCE(SUM(CASE WHEN vector_id IS NOT NULL AND vector_id <> '' THEN 1 ELSE 0 END), 0) AS vectorized_chunks
                FROM file_chunks
                WHERE file_id = %s
                """,
                (file_id,),
            )
        except Exception as error:
            logger.warning("Failed to load vectorization stats for file_id=%s: %s", file_id, error)
            return {
                "total_chunk_count": 0,
                "vectorized_chunk_count": 0,
                "missing_vector_chunk_count": 0,
                "vectorization_status": "unknown",
                "can_retry_vectorization": False,
            }

        row = result[0] if result else {}
        total_chunks = int((row.get("total_chunks") if isinstance(row, dict) else 0) or 0)
        vectorized_chunks = int((row.get("vectorized_chunks") if isinstance(row, dict) else 0) or 0)
        missing_chunks = max(0, total_chunks - vectorized_chunks)

        if total_chunks == 0:
            vectorization_status = "not_started"
        elif missing_chunks == 0:
            vectorization_status = "completed"
        elif vectorized_chunks == 0:
            vectorization_status = "pending"
        else:
            vectorization_status = "partial"

        return {
            "total_chunk_count": total_chunks,
            "vectorized_chunk_count": vectorized_chunks,
            "missing_vector_chunk_count": missing_chunks,
            "vectorization_status": vectorization_status,
            "can_retry_vectorization": missing_chunks > 0,
        }

    def _update_vectorization_metadata(
        self,
        file_record,
        *,
        stage: str,
        progress: int,
        status: str,
        error_message: str | None,
    ):
        metadata = dict(getattr(file_record, "metadata", {}) or {})
        metadata["processing_stage"] = stage
        metadata["processing_progress"] = progress
        metadata["vectorization_status"] = status
        metadata["vectorization_last_attempt_at"] = datetime.utcnow().isoformat()
        if error_message:
            metadata["vectorization_last_error"] = error_message
        else:
            metadata.pop("vectorization_last_error", None)

        self.file_repo.update_file(file_record.file_id, FileUpdate(metadata=metadata))
        refreshed_file = self.file_repo.get_file_by_id(file_record.file_id) or file_record
        self._remember_document_status(self._build_document_snapshot(refreshed_file))
        return refreshed_file

    def retry_document_vectorization(
        self,
        *,
        document_id: str,
        user_id: str,
        request_id: str | None = None,
    ) -> dict[str, Any]:
        file_record = self.file_repo.get_file_by_id(document_id)
        if not file_record or not is_knowledge_managed_file(file_record):
            raise FileNotFoundError("?????")
        if file_record.user_id != user_id:
            raise PermissionError("??????????")

        stats_before = self._get_vectorization_stats(document_id)
        missing_before = int(stats_before.get("missing_vector_chunk_count", 0) or 0)
        if missing_before == 0:
            snapshot = self._build_document_snapshot(file_record)
            return {
                "document_id": document_id,
                "file_name": file_record.original_filename,
                "missing_before": 0,
                "vectorized_now": 0,
                "missing_after": 0,
                "success": True,
                "error": None,
                "document": snapshot,
            }

        logger.info(
            "Retrying vectorization for document: request_id=%s user_id=%s document_id=%s missing_before=%s",
            request_id,
            user_id,
            document_id,
            missing_before,
        )

        self._update_vectorization_metadata(
            file_record,
            stage="vectorizing",
            progress=85,
            status="retrying",
            error_message=None,
        )

        chunk_rows = self.db_manager.execute_query(
            """
            SELECT chunk_id, file_id, chunk_index, content, page_number, start_char, end_char,
                   token_count, vector_id, created_at, metadata
            FROM file_chunks
            WHERE file_id = %s AND (vector_id IS NULL OR vector_id = '')
            ORDER BY chunk_index ASC
            """,
            (document_id,),
        )
        logger.info(
            "Loaded pending chunks for vector rebuild: request_id=%s document_id=%s chunk_rows=%s",
            request_id,
            document_id,
            len(chunk_rows or []),
        )

        chunks: list[FileChunk] = []
        for row in chunk_rows:
            chunk_metadata = row.get("metadata") if isinstance(row, dict) else None
            chunks.append(
                FileChunk(
                    chunk_id=row.get("chunk_id"),
                    file_id=row.get("file_id"),
                    chunk_index=row.get("chunk_index"),
                    content=row.get("content") or "",
                    page_number=row.get("page_number"),
                    start_char=row.get("start_char"),
                    end_char=row.get("end_char"),
                    token_count=row.get("token_count"),
                    vector_id=row.get("vector_id"),
                    created_at=row.get("created_at"),
                    metadata=chunk_metadata if isinstance(chunk_metadata, dict) else None,
                )
            )

        documents = [chunk.content for chunk in chunks]
        metadatas = [build_chunk_vector_metadata(file_record, chunk) for chunk in chunks]
        chunk_ids = [chunk.chunk_id for chunk in chunks]

        if not documents:
            error_message = "????????????????????"
            logger.warning(
                "Vector rebuild skipped because no pending chunks found: request_id=%s document_id=%s",
                request_id,
                document_id,
            )
            refreshed_file = self._update_vectorization_metadata(
                file_record,
                stage="vectorizing_failed",
                progress=100,
                status="failed",
                error_message=error_message,
            )
            snapshot = self._build_document_snapshot(refreshed_file)
            return {
                "document_id": document_id,
                "file_name": file_record.original_filename,
                "missing_before": missing_before,
                "vectorized_now": 0,
                "missing_after": missing_before,
                "success": False,
                "error": error_message,
                "document": snapshot,
            }

        embedding_client = get_embedding_client()
        embeddings = embedding_client.embed_texts(documents)
        valid_data = [
            (document, embedding, metadata, chunk_id)
            for document, embedding, metadata, chunk_id in zip(documents, embeddings, metadatas, chunk_ids)
            if embedding is not None
        ]
        logger.info(
            "Embedding generation finished for vector rebuild: request_id=%s document_id=%s total_chunks=%s valid_embeddings=%s",
            request_id,
            document_id,
            len(documents),
            len(valid_data),
        )

        if not valid_data:
            error_message = getattr(embedding_client, "last_error", None) or "????????????? embedding ????"
            logger.error(
                "Vector rebuild failed because no valid embeddings were generated: request_id=%s document_id=%s error=%s",
                request_id,
                document_id,
                error_message,
            )
            refreshed_file = self._update_vectorization_metadata(
                file_record,
                stage="vectorizing_failed",
                progress=100,
                status="failed",
                error_message=error_message,
            )
            snapshot = self._build_document_snapshot(refreshed_file)
            return {
                "document_id": document_id,
                "file_name": file_record.original_filename,
                "missing_before": missing_before,
                "vectorized_now": 0,
                "missing_after": missing_before,
                "success": False,
                "error": error_message,
                "document": snapshot,
            }

        valid_documents, valid_embeddings, valid_metadatas, valid_ids = zip(*valid_data)
        self.vector_store.delete_documents(ids=list(valid_ids))
        success = self.vector_store.add_documents(
            documents=list(valid_documents),
            embeddings=list(valid_embeddings),
            metadatas=list(valid_metadatas),
            ids=list(valid_ids),
        )

        if not success:
            error_message = getattr(self.vector_store, "last_error", None) or "?????????"
            logger.error(
                "Vector rebuild write failed: request_id=%s document_id=%s chunk_count=%s error=%s",
                request_id,
                document_id,
                len(valid_ids),
                error_message,
            )
            refreshed_file = self._update_vectorization_metadata(
                file_record,
                stage="vectorizing_failed",
                progress=100,
                status="failed",
                error_message=error_message,
            )
            snapshot = self._build_document_snapshot(refreshed_file)
            return {
                "document_id": document_id,
                "file_name": file_record.original_filename,
                "missing_before": missing_before,
                "vectorized_now": 0,
                "missing_after": missing_before,
                "success": False,
                "error": error_message,
                "document": snapshot,
            }

        for chunk_id in valid_ids:
            self.db_manager.execute_update(
                "UPDATE file_chunks SET vector_id = %s WHERE chunk_id = %s",
                (chunk_id, chunk_id),
            )
        logger.info(
            "Vector rebuild write succeeded: request_id=%s document_id=%s vectorized_now=%s",
            request_id,
            document_id,
            len(valid_ids),
        )

        stats_after = self._get_vectorization_stats(document_id)
        missing_after = int(stats_after.get("missing_vector_chunk_count", 0) or 0)
        vectorized_now = len(valid_ids)
        error_message = None if missing_after == 0 else f"?? {missing_after} ?????????"
        logger.info(
            "Vector rebuild result: request_id=%s document_id=%s missing_before=%s vectorized_now=%s missing_after=%s success=%s",
            request_id,
            document_id,
            missing_before,
            vectorized_now,
            missing_after,
            missing_after == 0,
        )
        refreshed_file = self._update_vectorization_metadata(
            file_record,
            stage="completed" if missing_after == 0 else "vectorizing_partial",
            progress=100,
            status="completed" if missing_after == 0 else "partial",
            error_message=error_message,
        )
        snapshot = self._build_document_snapshot(refreshed_file)
        return {
            "document_id": document_id,
            "file_name": file_record.original_filename,
            "missing_before": missing_before,
            "vectorized_now": vectorized_now,
            "missing_after": missing_after,
            "success": missing_after == 0,
            "error": error_message,
            "document": snapshot,
        }

    def retry_pending_vectorizations(
        self,
        *,
        user_id: str,
        knowledge_base_id: str | None = None,
        request_id: str | None = None,
    ) -> dict[str, Any]:
        logger.info(
            "Starting bulk vector rebuild: request_id=%s user_id=%s knowledge_base_id=%s",
            request_id,
            user_id,
            knowledge_base_id,
        )
        file_records = [
            file_record
            for file_record in self.file_repo.get_files_by_user_id(user_id)
            if is_knowledge_managed_file(file_record)
        ]
        if knowledge_base_id:
            file_records = [
                file_record
                for file_record in file_records
                if (getattr(file_record, "metadata", {}) or {}).get("knowledge_base_id") == knowledge_base_id
            ]

        retry_candidates = []
        for file_record in file_records:
            stats = self._get_vectorization_stats(file_record.file_id)
            if int(stats.get("missing_vector_chunk_count", 0) or 0) > 0:
                retry_candidates.append(file_record)
        logger.info(
            "Bulk vector rebuild candidates prepared: request_id=%s knowledge_base_id=%s candidates=%s",
            request_id,
            knowledge_base_id,
            len(retry_candidates),
        )

        details = [
            self.retry_document_vectorization(
                document_id=file_record.file_id,
                user_id=user_id,
                request_id=request_id,
            )
            for file_record in retry_candidates
        ]

        result = {
            "total_documents": len(retry_candidates),
            "processed_documents": len(details),
            "succeeded_documents": sum(1 for item in details if item.get("success")),
            "failed_documents": sum(1 for item in details if not item.get("success")),
            "total_missing_chunks_before": sum(int(item.get("missing_before", 0) or 0) for item in details),
            "total_vectorized_chunks_now": sum(int(item.get("vectorized_now", 0) or 0) for item in details),
            "total_missing_chunks_after": sum(int(item.get("missing_after", 0) or 0) for item in details),
            "details": details,
        }
        logger.info(
            "Bulk vector rebuild finished: request_id=%s knowledge_base_id=%s succeeded=%s failed=%s missing_before=%s missing_after=%s",
            request_id,
            knowledge_base_id,
            result["succeeded_documents"],
            result["failed_documents"],
            result["total_missing_chunks_before"],
            result["total_missing_chunks_after"],
        )
        return result

    def _list_knowledge_managed_files(
        self,
        *,
        user_id: str | None = None,
        knowledge_base_id: str | None = None,
    ):
        if user_id:
            file_records = self.file_repo.get_files_by_user_id(user_id)
        else:
            rows = self.db_manager.execute_query("SELECT file_id FROM files ORDER BY created_at DESC")
            file_records = []
            for row in rows:
                if not isinstance(row, dict):
                    continue
                file_id = row.get("file_id")
                if not file_id:
                    continue
                file_record = self.file_repo.get_file_by_id(file_id)
                if file_record:
                    file_records.append(file_record)

        file_records = [file_record for file_record in file_records if is_knowledge_managed_file(file_record)]
        if knowledge_base_id:
            file_records = [
                file_record
                for file_record in file_records
                if (getattr(file_record, "metadata", {}) or {}).get("knowledge_base_id") == knowledge_base_id
            ]
        return file_records

    def _purge_expired_full_rebuild_tasks(self) -> None:
        now = datetime.utcnow()
        with _full_vector_rebuild_tasks_lock:
            expired_task_ids = [
                task_id
                for task_id, task in _full_vector_rebuild_tasks.items()
                if now - task.get("_updated_at_dt", now) > _FULL_REBUILD_TASK_TTL
            ]
            for task_id in expired_task_ids:
                _full_vector_rebuild_tasks.pop(task_id, None)

    def _update_full_rebuild_task(self, *, task_id: str, updates: dict[str, Any]) -> dict[str, Any]:
        self._purge_expired_full_rebuild_tasks()
        with _full_vector_rebuild_tasks_lock:
            task = _full_vector_rebuild_tasks.get(task_id)
            if task is None:
                raise FileNotFoundError("???????????")

            for key, value in updates.items():
                if key == "details" and value is not None:
                    task[key] = [dict(item) for item in value]
                else:
                    task[key] = value

            task["updated_at"] = _utcnow_iso()
            task["_updated_at_dt"] = datetime.utcnow()
            return _clone_full_rebuild_task(task)

    def start_full_vector_rebuild_task(
        self,
        *,
        user_id: str,
        knowledge_base_id: str | None = None,
        request_id: str | None = None,
    ) -> dict[str, Any]:
        self._purge_expired_full_rebuild_tasks()
        task_id = str(uuid.uuid4())
        task = {
            "task_id": task_id,
            "user_id": user_id,
            "knowledge_base_id": knowledge_base_id,
            "scope": "knowledge_base" if knowledge_base_id else "all_knowledge_bases",
            "request_id": request_id,
            "status": "pending",
            "total_documents": 0,
            "processed_documents": 0,
            "succeeded_documents": 0,
            "failed_documents": 0,
            "total_missing_chunks_before": 0,
            "total_vectorized_chunks_now": 0,
            "total_missing_chunks_after": 0,
            "details": [],
            "reset_collection": False,
            "target_dimension": 0,
            "current_document_id": None,
            "current_file_name": None,
            "error": None,
            "created_at": _utcnow_iso(),
            "started_at": None,
            "finished_at": None,
            "updated_at": _utcnow_iso(),
            "_updated_at_dt": datetime.utcnow(),
        }
        with _full_vector_rebuild_tasks_lock:
            _full_vector_rebuild_tasks[task_id] = task

        logger.warning(
            "Created full vector rebuild task: task_id=%s request_id=%s user_id=%s knowledge_base_id=%s",
            task_id,
            request_id,
            user_id,
            knowledge_base_id,
        )
        return _clone_full_rebuild_task(task)

    def get_full_vector_rebuild_task(self, *, task_id: str, user_id: str) -> dict[str, Any]:
        self._purge_expired_full_rebuild_tasks()
        with _full_vector_rebuild_tasks_lock:
            task = _full_vector_rebuild_tasks.get(task_id)
            if task is None:
                raise FileNotFoundError("???????????")
            if task.get("user_id") != user_id:
                raise PermissionError("?????????????")
            return _clone_full_rebuild_task(task)

    def run_full_vector_rebuild_task(
        self,
        *,
        task_id: str,
        user_id: str,
        knowledge_base_id: str | None = None,
        request_id: str | None = None,
    ) -> None:
        logger.warning(
            "Starting full vector rebuild task runner: task_id=%s request_id=%s user_id=%s knowledge_base_id=%s",
            task_id,
            request_id,
            user_id,
            knowledge_base_id,
        )
        self._update_full_rebuild_task(
            task_id=task_id,
            updates={
                "status": "running",
                "started_at": _utcnow_iso(),
                "error": None,
            },
        )

        def progress_callback(progress: dict[str, Any]) -> None:
            logger.info(
                "Full vector rebuild task progress: task_id=%s request_id=%s processed=%s/%s succeeded=%s failed=%s current_document_id=%s current_file_name=%s",
                task_id,
                request_id,
                progress.get("processed_documents"),
                progress.get("total_documents"),
                progress.get("succeeded_documents"),
                progress.get("failed_documents"),
                progress.get("current_document_id"),
                progress.get("current_file_name"),
            )
            self._update_full_rebuild_task(task_id=task_id, updates=progress)

        try:
            result = self.rebuild_all_vectors_for_current_model(
                user_id=user_id,
                knowledge_base_id=knowledge_base_id,
                request_id=request_id,
                progress_callback=progress_callback,
            )
            final_status = "succeeded" if not result.get("error") and int(result.get("failed_documents", 0) or 0) == 0 else "failed"
            self._update_full_rebuild_task(
                task_id=task_id,
                updates={
                    **result,
                    "status": final_status,
                    "current_document_id": None,
                    "current_file_name": None,
                    "finished_at": _utcnow_iso(),
                },
            )
            logger.warning(
                "Full vector rebuild task finished: task_id=%s request_id=%s status=%s succeeded=%s failed=%s vectorized_now=%s remaining=%s",
                task_id,
                request_id,
                final_status,
                result.get("succeeded_documents"),
                result.get("failed_documents"),
                result.get("total_vectorized_chunks_now"),
                result.get("total_missing_chunks_after"),
            )
        except Exception as error:
            self._update_full_rebuild_task(
                task_id=task_id,
                updates={
                    "status": "failed",
                    "error": str(error),
                    "current_document_id": None,
                    "current_file_name": None,
                    "finished_at": _utcnow_iso(),
                },
            )
            logger.error(
                "Full vector rebuild task failed unexpectedly: task_id=%s request_id=%s error=%s",
                task_id,
                request_id,
                error,
                exc_info=True,
            )

    def rebuild_all_vectors_for_current_model(
        self,
        *,
        user_id: str | None = None,
        knowledge_base_id: str | None = None,
        request_id: str | None = None,
        progress_callback=None,
    ) -> dict[str, Any]:
        logger.warning(
            "Starting full vector migration to current embedding dimension: request_id=%s user_id=%s knowledge_base_id=%s",
            request_id,
            user_id,
            knowledge_base_id,
        )
        embedding_client = get_embedding_client()
        target_dimension = embedding_client.get_dimension()
        file_records = self._list_knowledge_managed_files(user_id=user_id, knowledge_base_id=knowledge_base_id)

        candidates = []
        for file_record in file_records:
            stats = self._get_vectorization_stats(file_record.file_id)
            if int(stats.get("total_chunk_count", 0) or 0) > 0:
                candidates.append(file_record)

        logger.warning(
            "Full vector migration candidates prepared: request_id=%s candidates=%s target_dimension=%s",
            request_id,
            len(candidates),
            target_dimension,
        )

        if progress_callback:
            progress_callback({
                "total_documents": len(candidates),
                "processed_documents": 0,
                "succeeded_documents": 0,
                "failed_documents": 0,
                "total_missing_chunks_before": 0,
                "total_vectorized_chunks_now": 0,
                "total_missing_chunks_after": 0,
                "details": [],
                "reset_collection": False,
                "target_dimension": target_dimension,
                "current_document_id": None,
                "current_file_name": None,
                "error": None,
            })

        if not self.vector_store.reset_collection():
            error_message = getattr(self.vector_store, "last_error", None) or "????????"
            logger.error(
                "Full vector migration aborted because collection reset failed: request_id=%s error=%s",
                request_id,
                error_message,
            )
            result = {
                "total_documents": len(candidates),
                "processed_documents": 0,
                "succeeded_documents": 0,
                "failed_documents": len(candidates),
                "total_missing_chunks_before": 0,
                "total_vectorized_chunks_now": 0,
                "total_missing_chunks_after": 0,
                "details": [],
                "reset_collection": False,
                "target_dimension": target_dimension,
                "current_document_id": None,
                "current_file_name": None,
                "error": error_message,
            }
            if progress_callback:
                progress_callback(result)
            return result

        for file_record in candidates:
            self.db_manager.execute_update(
                "UPDATE file_chunks SET vector_id = NULL WHERE file_id = %s",
                (file_record.file_id,),
            )
            metadata = dict(getattr(file_record, "metadata", {}) or {})
            metadata["processing_stage"] = "vectorizing"
            metadata["processing_progress"] = 80
            metadata["vectorization_status"] = "pending"
            metadata["vector_dimension"] = target_dimension
            metadata["vector_model"] = embedding_client.model_name
            self.file_repo.update_file(file_record.file_id, FileUpdate(metadata=metadata))

        details = []
        processed_documents = 0
        succeeded_documents = 0
        failed_documents = 0
        total_missing_chunks_before = 0
        total_vectorized_chunks_now = 0
        total_missing_chunks_after = 0

        for file_record in candidates:
            try:
                detail = self.retry_document_vectorization(
                    document_id=file_record.file_id,
                    user_id=file_record.user_id,
                    request_id=request_id,
                )
            except Exception as error:
                logger.error(
                    "Full vector migration item failed: request_id=%s document_id=%s file_name=%s error=%s",
                    request_id,
                    file_record.file_id,
                    file_record.original_filename,
                    error,
                    exc_info=True,
                )
                self._update_vectorization_metadata(
                    file_record,
                    stage="failed",
                    progress=100,
                    status="failed",
                    error_message=str(error),
                )
                stats_after_failure = self._get_vectorization_stats(file_record.file_id)
                detail = {
                    "document_id": file_record.file_id,
                    "file_name": file_record.original_filename,
                    "missing_before": int(stats_after_failure.get("total_chunk_count", 0) or 0),
                    "vectorized_now": 0,
                    "missing_after": int(stats_after_failure.get("missing_vector_chunk_count", 0) or 0),
                    "success": False,
                    "error": str(error),
                }

            details.append(detail)
            processed_documents += 1
            succeeded_documents += 1 if detail.get("success") else 0
            failed_documents += 0 if detail.get("success") else 1
            total_missing_chunks_before += int(detail.get("missing_before", 0) or 0)
            total_vectorized_chunks_now += int(detail.get("vectorized_now", 0) or 0)
            total_missing_chunks_after += int(detail.get("missing_after", 0) or 0)

            logger.info(
                "Full vector migration progress: request_id=%s processed=%s/%s current_document_id=%s current_file_name=%s success=%s vectorized_now=%s remaining=%s",
                request_id,
                processed_documents,
                len(candidates),
                detail.get("document_id"),
                detail.get("file_name"),
                detail.get("success"),
                total_vectorized_chunks_now,
                total_missing_chunks_after,
            )

            if progress_callback:
                progress_callback({
                    "total_documents": len(candidates),
                    "processed_documents": processed_documents,
                    "succeeded_documents": succeeded_documents,
                    "failed_documents": failed_documents,
                    "total_missing_chunks_before": total_missing_chunks_before,
                    "total_vectorized_chunks_now": total_vectorized_chunks_now,
                    "total_missing_chunks_after": total_missing_chunks_after,
                    "details": details,
                    "reset_collection": True,
                    "target_dimension": target_dimension,
                    "current_document_id": detail.get("document_id"),
                    "current_file_name": detail.get("file_name"),
                    "error": None,
                })

        result = {
            "total_documents": len(candidates),
            "processed_documents": processed_documents,
            "succeeded_documents": succeeded_documents,
            "failed_documents": failed_documents,
            "total_missing_chunks_before": total_missing_chunks_before,
            "total_vectorized_chunks_now": total_vectorized_chunks_now,
            "total_missing_chunks_after": total_missing_chunks_after,
            "details": details,
            "reset_collection": True,
            "target_dimension": target_dimension,
            "error": None,
        }
        logger.warning(
            "Full vector migration finished: request_id=%s succeeded=%s failed=%s vectorized_now=%s remaining=%s target_dimension=%s",
            request_id,
            result["succeeded_documents"],
            result["failed_documents"],
            result["total_vectorized_chunks_now"],
            result["total_missing_chunks_after"],
            target_dimension,
        )
        return result

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
        _recent_document_statuses.pop(document_id, None)
        if isinstance(cleanup_result, dict):
            cleanup_result.setdefault("request_id", request_id)
            cleanup_result.setdefault("document_id", document_id)
        return cleanup_result
