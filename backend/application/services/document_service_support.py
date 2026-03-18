from __future__ import annotations

from datetime import timedelta
from threading import Lock
from typing import Any

from backend.domain.knowledge import (
    delete_file_knowledge_data,
    format_file_as_document,
    is_knowledge_managed_file,
)
from backend.infrastructure.persistence import FileRepositoryAdapter, KnowledgeBaseRepositoryAdapter
from backend.infrastructure.storage import LocalFileStorageGateway
from backend.models.file import FileType, FileUpdate
from backend.utils.logger import get_logger
from backend.utils.time_utils import utc_now, utc_now_iso_z
from backend.utils.vector_db_client import get_vector_db_client


logger = get_logger(__name__)
_STATUS_CACHE_TTL = timedelta(minutes=10)
_FULL_REBUILD_TASK_TTL = timedelta(hours=6)
_recent_document_statuses: dict[str, dict[str, Any]] = {}
_full_vector_rebuild_tasks: dict[str, dict[str, Any]] = {}
_full_vector_rebuild_tasks_lock = Lock()


def _utcnow_iso() -> str:
    return utc_now_iso_z(timespec="seconds")


def _clone_full_rebuild_task(task: dict[str, Any]) -> dict[str, Any]:
    snapshot = {key: value for key, value in task.items() if not key.startswith("_")}
    snapshot["details"] = [dict(item) for item in task.get("details", [])]
    return snapshot


class DocumentServiceSupport:
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


    def _remember_document_status(self, document: dict[str, Any]) -> None:
        snapshot = dict(document)
        snapshot["cached_at"] = utc_now()
        _recent_document_statuses[snapshot["document_id"]] = snapshot


    def _purge_expired_document_statuses(self) -> None:
        now = utc_now()
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
        metadata["vectorization_last_attempt_at"] = utc_now().isoformat()
        if error_message:
            metadata["vectorization_last_error"] = error_message
        else:
            metadata.pop("vectorization_last_error", None)

        self.file_repo.update_file(file_record.file_id, FileUpdate(metadata=metadata))
        refreshed_file = self.file_repo.get_file_by_id(file_record.file_id) or file_record
        self._remember_document_status(self._build_document_snapshot(refreshed_file))
        return refreshed_file


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
        now = utc_now()
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
                raise FileNotFoundError("Full rebuild task not found")

            for key, value in updates.items():
                if key == "details" and value is not None:
                    task[key] = [dict(item) for item in value]
                else:
                    task[key] = value

            task["updated_at"] = _utcnow_iso()
            task["_updated_at_dt"] = utc_now()
            return _clone_full_rebuild_task(task)


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
                f"涓婁紶鏂囦欢 MIME 绫诲瀷涓庢墿灞曞悕涓嶅尮閰? filename={upload_file.filename}, content_type={content_type}"
            )


