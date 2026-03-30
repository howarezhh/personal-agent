from __future__ import annotations

from typing import Any, Dict, List

from backend.models.retrieval_result import RetrievalResultCreate
from backend.utils.logger import get_logger


class RetrievalPersistenceApplicationService:
    """Application service for retrieval persistence."""


    def __init__(self, *, database_manager, retrieval_result_repository):
        self.db_manager = database_manager
        self.retrieval_result_repo = retrieval_result_repository
        self.logger = get_logger(self.__class__.__name__)

    def fetch_fallback_rows(self, user_id: str) -> List[Dict[str, Any]]:
        return self.db_manager.execute_query(
            """
            SELECT fc.chunk_id, fc.chunk_index, fc.content, fc.page_number,
                   fc.file_id, fc.metadata AS chunk_metadata,
                   f.user_id, f.conversation_id, f.original_filename,
                   f.file_type, f.metadata AS file_metadata
            FROM file_chunks fc
            INNER JOIN files f ON f.file_id = fc.file_id
            WHERE f.user_id = %s
            ORDER BY f.created_at DESC, fc.chunk_index ASC
            """,
            (user_id,),
        )

    def save_retrieval_results(self, execution_id: str, results: List[Dict[str, Any]]) -> None:
        self.logger.info("Saving %s retrieval results", len(results))
        for rank, result in enumerate(results, start=1):
            retrieval_result = RetrievalResultCreate(
                execution_id=execution_id,
                content=result.get("content", ""),
                source_type=result.get("metadata", {}).get("source_type", "document"),
                source_id=result.get("id"),
                source_name=result.get("metadata", {}).get("source", "Unknown"),
                relevance_score=result.get("score"),
                rank=rank,
                metadata=result.get("metadata"),
            )
            self.retrieval_result_repo.create_retrieval_result(retrieval_result)
        self.logger.info("Saved %s retrieval results", len(results))
