from __future__ import annotations

from datetime import timedelta
from threading import Lock
from typing import Any

from backend.contracts.async_task import AsyncTaskStatus, is_terminal_async_task_status, normalize_async_task_status
from backend.domain.knowledge import (
    delete_file_knowledge_data,
    format_file_as_document,
    is_knowledge_managed_file,
)
from backend.file_processors.document_registry import get_allowed_mime_types_for_filename
from backend.infrastructure.persistence import FileRepositoryAdapter, KnowledgeBaseRepositoryAdapter
from backend.infrastructure.storage import LocalFileStorageGateway
from backend.models.file import FileUpdate, ProcessingStatus
from backend.utils.logger import get_logger
from backend.utils.time_utils import utc_now, utc_now_iso_z


logger = get_logger(__name__)
_STATUS_CACHE_TTL = timedelta(minutes=10)
_FULL_REBUILD_TASK_TTL = timedelta(hours=6)
_IDEMPOTENCY_CACHE_TTL = timedelta(hours=24)
_recent_document_statuses: dict[str, dict[str, Any]] = {}
_full_vector_rebuild_tasks: dict[str, dict[str, Any]] = {}
_full_vector_rebuild_tasks_lock = Lock()
_idempotent_operation_records: dict[str, dict[str, Any]] = {}
_idempotent_operation_lock = Lock()


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
        self.vector_store = vector_store
        self._db_manager = db_manager
        if self.vector_store is None:
            raise ValueError("DocumentServiceSupport requires injected vector_store")
        if self._db_manager is None:
            raise ValueError("DocumentServiceSupport requires injected db_manager")

    @property

    def db_manager(self):
        return self._db_manager


    def _remember_document_status(self, document: dict[str, Any]) -> None:
        snapshot = dict(document)
        snapshot["cached_at"] = utc_now()
        _recent_document_statuses[snapshot["document_id"]] = snapshot

    @staticmethod
    def _build_idempotent_record_key(*, namespace: str, user_id: str, idempotency_key: str) -> str:
        """构造幂等缓存键，确保不同用户与不同操作互不污染。"""

        return f"{namespace}:{user_id}:{idempotency_key}"

    def _purge_expired_idempotent_records(self) -> None:
        """清理过期的幂等记录，避免内存缓存无限增长。"""

        now = utc_now()
        with _idempotent_operation_lock:
            expired_keys = [
                cache_key
                for cache_key, record in _idempotent_operation_records.items()
                if now - record.get("updated_at", now) > _IDEMPOTENCY_CACHE_TTL
            ]
            for cache_key in expired_keys:
                _idempotent_operation_records.pop(cache_key, None)

    def _get_idempotent_record(self, *, namespace: str, user_id: str, idempotency_key: str | None) -> dict[str, Any] | None:
        """按命名空间读取幂等记录。"""

        if not idempotency_key:
            return None
        self._purge_expired_idempotent_records()
        cache_key = self._build_idempotent_record_key(
            namespace=namespace,
            user_id=user_id,
            idempotency_key=idempotency_key,
        )
        with _idempotent_operation_lock:
            record = _idempotent_operation_records.get(cache_key)
            return dict(record) if record else None

    def _remember_idempotent_record(
        self,
        *,
        namespace: str,
        user_id: str,
        idempotency_key: str | None,
        payload: dict[str, Any],
    ) -> None:
        """写入幂等记录，供重复请求复用。"""

        if not idempotency_key:
            return
        self._purge_expired_idempotent_records()
        cache_key = self._build_idempotent_record_key(
            namespace=namespace,
            user_id=user_id,
            idempotency_key=idempotency_key,
        )
        with _idempotent_operation_lock:
            _idempotent_operation_records[cache_key] = {
                **dict(payload),
                "updated_at": utc_now(),
            }


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
                "vectorization_status": AsyncTaskStatus.FAILED.value,
                "can_retry_vectorization": False,
            }

        row = result[0] if result else {}
        total_chunks = int((row.get("total_chunks") if isinstance(row, dict) else 0) or 0)
        vectorized_chunks = int((row.get("vectorized_chunks") if isinstance(row, dict) else 0) or 0)
        missing_chunks = max(0, total_chunks - vectorized_chunks)

        if total_chunks == 0:
            vectorization_status = AsyncTaskStatus.PENDING.value
        elif missing_chunks == 0:
            vectorization_status = AsyncTaskStatus.SUCCEEDED.value
        elif vectorized_chunks == 0:
            vectorization_status = AsyncTaskStatus.RUNNING.value
        else:
            vectorization_status = AsyncTaskStatus.RUNNING.value

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
        metadata["task_status"] = normalize_async_task_status(status)
        metadata["vectorization_status"] = normalize_async_task_status(status)
        metadata["vectorization_last_attempt_at"] = utc_now().isoformat()
        if error_message:
            metadata["vectorization_last_error"] = error_message
        else:
            metadata.pop("vectorization_last_error", None)

        normalized_status = normalize_async_task_status(status)
        processing_status = None
        persisted_error_message = error_message
        # 向量重建成功后，需要同步修正文档主状态，避免历史失败记录仍然显示为失败。
        if normalized_status == AsyncTaskStatus.SUCCEEDED.value:
            processing_status = ProcessingStatus.COMPLETED
            # 这里使用空字符串覆盖旧错误，兼容 FileUpdate 仅在非 None 时才会落库的现有实现。
            persisted_error_message = ""
        elif normalized_status == AsyncTaskStatus.FAILED.value:
            processing_status = ProcessingStatus.FAILED

        self.file_repo.update_file(
            file_record.file_id,
            FileUpdate(
                processing_status=processing_status,
                error_message=persisted_error_message,
                metadata=metadata,
            ),
        )
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

    @staticmethod
    def _normalize_document_filename(file_name: str | None) -> str:
        """统一文件名比较口径，避免同名文档因为大小写或首尾空白被视为不同文件。"""

        return str(file_name or "").strip().casefold()

    def _find_same_name_documents(
        self,
        *,
        user_id: str,
        knowledge_base_id: str | None,
        file_name: str,
        exclude_file_id: str | None = None,
    ) -> list:
        """查找同一知识库下的同名文档。

        当前产品没有文档版本管理，同知识库下保留多份同名文件只会增加用户理解成本，
        因此这里把“同知识库 + 同名文件”视为需要被后续新文件替换的候选项。
        """

        normalized_file_name = self._normalize_document_filename(file_name)
        if not normalized_file_name:
            return []

        duplicate_file_records = []
        for file_record in self._list_knowledge_managed_files(user_id=user_id, knowledge_base_id=knowledge_base_id):
            if exclude_file_id and getattr(file_record, "file_id", None) == exclude_file_id:
                continue
            if self._normalize_document_filename(getattr(file_record, "original_filename", None)) != normalized_file_name:
                continue
            duplicate_file_records.append(file_record)
        return duplicate_file_records

    def _delete_replaced_document(self, *, file_record, request_id: str | None = None) -> None:
        """删除被新上传文档替换掉的旧文档资源。"""

        document_id = getattr(file_record, "file_id", None)
        if not document_id:
            return

        try:
            delete_file_knowledge_data(
                file_id=document_id,
                vector_store=self.vector_store,
                log=logger,
            )
        except Exception as cleanup_error:
            logger.error(
                "Failed to cleanup replaced knowledge data: request_id=%s document_id=%s error=%s",
                request_id,
                document_id,
                cleanup_error,
                exc_info=True,
            )

        storage_path = getattr(file_record, "storage_path", None)
        if storage_path:
            try:
                self.storage_gateway.delete(storage_path)
            except Exception as cleanup_error:
                logger.error(
                    "Failed to delete replaced document file: request_id=%s document_id=%s path=%s error=%s",
                    request_id,
                    document_id,
                    storage_path,
                    cleanup_error,
                    exc_info=True,
                )

        try:
            existing_file = self.file_repo.get_file_by_id(document_id)
            if existing_file:
                self.file_repo.delete_file(document_id)
        except Exception as cleanup_error:
            logger.error(
                "Failed to delete replaced document record: request_id=%s document_id=%s error=%s",
                request_id,
                document_id,
                cleanup_error,
                exc_info=True,
            )

        _recent_document_statuses.pop(document_id, None)

    def _delete_replaced_documents(
        self,
        *,
        file_records: list,
        request_id: str | None = None,
        replacement_document_id: str | None = None,
    ) -> None:
        """在新文档处理成功后，清理同知识库下被替换的旧同名文档。"""

        for file_record in file_records:
            replaced_document_id = getattr(file_record, "file_id", None)
            logger.info(
                "Replacing duplicated knowledge document: request_id=%s replacement_document_id=%s replaced_document_id=%s knowledge_base_id=%s filename=%s",
                request_id,
                replacement_document_id,
                replaced_document_id,
                (getattr(file_record, "metadata", {}) or {}).get("knowledge_base_id"),
                getattr(file_record, "original_filename", None),
            )
            self._delete_replaced_document(file_record=file_record, request_id=request_id)


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

        # MIME 校验改为按“具体文件名”走统一注册表，避免 `.svg -> XML` 这类同 FileType 不同 MIME 被误判。
        expected_types = get_allowed_mime_types_for_filename(getattr(upload_file, "filename", None))
        if expected_types and content_type not in expected_types:
            raise ValueError(
                f"上传文件 MIME 类型与扩展名不匹配: filename={upload_file.filename}, content_type={content_type}"
            )


