from __future__ import annotations

from typing import Any

from backend.application.services.document_service_support import (
    DocumentServiceSupport,
    _clone_full_rebuild_task,
    _full_vector_rebuild_tasks,
    _full_vector_rebuild_tasks_lock,
    _utcnow_iso,
    logger,
)
from backend.models.file import FileUpdate
from backend.utils.embedding_client import get_embedding_client
from backend.utils.time_utils import utc_now


class DocumentVectorRebuildApplicationService(DocumentServiceSupport):
    def retry_document_vectorization(
        self,
        *,
        document_id: str,
        user_id: str,
        request_id: str | None = None,
    ) -> dict[str, Any]:
        file_record = self.file_repo.get_file_by_id(document_id)
        if not file_record or not is_knowledge_managed_file(file_record):
            raise FileNotFoundError("Document not found")
        if file_record.user_id != user_id:
            raise PermissionError("Document access denied")

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
            error_message = "鏈壘鍒伴渶瑕佽ˉ鍏ㄥ悜閲忕殑鏂囨。鍒嗗潡"
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
            error_message = getattr(embedding_client, "last_error", None) or "鏈敓鎴愭湁鏁堢殑 embedding 鍚戦噺"
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
            error_message = getattr(self.vector_store, "last_error", None) or "鍚戦噺瀛樺偍鍐欏叆澶辫触"
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
        error_message = None if missing_after == 0 else f"{missing_after} chunks still have no vectors"
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
            "_updated_at_dt": utc_now(),
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
                raise FileNotFoundError("Full rebuild task not found")
                raise PermissionError("Rebuild task access denied")
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
            error_message = getattr(self.vector_store, "last_error", None) or "閲嶇疆鍚戦噺闆嗗悎澶辫触"
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


