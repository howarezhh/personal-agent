from __future__ import annotations

import uuid
from types import SimpleNamespace
from typing import Any

from backend.application.services.knowledge_base_service_support import KnowledgeBaseServiceSupport, logger


class KnowledgeSearchApplicationService(KnowledgeBaseServiceSupport):
    """知识库检索应用服务。"""

    async def search_knowledge(
        self,
        *,
        user_id: str,
        query: str,
        top_k: int,
        knowledge_base_id: str | None,
        retrieval_options: dict[str, Any] | None = None,
        request_id: str | None = None,
    ):
        """执行知识库检索，并将 Retrieval Agent 结果整理为统一结构。"""
        vector_search_filter = {}
        if knowledge_base_id:
            knowledge_base = self.get_user_knowledge_base(user_id=user_id, knowledge_base_id=knowledge_base_id)
            if not knowledge_base:
                raise ValueError("知识库不存在或无权访问")
            vector_search_filter["knowledge_base_id"] = knowledge_base_id

        logger.info(
            "Searching knowledge: request_id=%s user_id=%s knowledge_base_id=%s top_k=%s",
            request_id,
            user_id,
            knowledge_base_id,
            top_k,
        )

        retrieval_output = await self._get_retrieval_executor().execute(
            self._build_search_agent_input(
                user_id=user_id,
                query=query,
                top_k=top_k,
                vector_search_filter=vector_search_filter,
                retrieval_options=retrieval_options,
                request_id=request_id,
            )
        )
        if retrieval_output.is_failed():
            raise RuntimeError(retrieval_output.error_message or "知识库检索失败")

        return self._format_search_results(
            retrieval_output.get_metadata("retrieval_results", []) or [],
            top_k=top_k,
        )

    def _get_retrieval_executor(self):
        """按需创建 Retrieval Agent，避免无必要初始化。"""
        if self.retrieval_executor is None:
            from backend.agents.retrieval.retrieval_agent import RetrievalAgent

            self.retrieval_executor = RetrievalAgent()
        return self.retrieval_executor

    @staticmethod
    def _build_search_agent_input(
        *,
        user_id: str,
        query: str,
        top_k: int,
        vector_search_filter: dict[str, Any],
        retrieval_options: dict[str, Any] | None,
        request_id: str | None,
    ):
        """构造知识库搜索所需的标准 Agent 输入。"""
        search_request_id = request_id or str(uuid.uuid4())
        merged_retrieval_options = {
            "top_k": top_k,
            "rerank_top_k": top_k,
            "keyword_top_k": max(top_k * 2, 8),
        }
        if isinstance(retrieval_options, dict):
            merged_retrieval_options.update(retrieval_options)

        return SimpleNamespace(
            user_id=user_id,
            conversation_id=f"knowledge-search-{search_request_id}",
            message_id=f"knowledge-search-{search_request_id}",
            content=query,
            conversation_history=[],
            metadata={
                "vector_search_filter": dict(vector_search_filter),
                "retrieval_options": merged_retrieval_options,
                "request_id": request_id,
                "search_source": "knowledge_api",
            },
        )

    @staticmethod
    def _format_search_results(retrieval_results: list[dict[str, Any]], *, top_k: int) -> list[dict[str, Any]]:
        """把 Retrieval Agent 的输出映射成知识库搜索响应结构。"""
        search_results = []
        for result in retrieval_results:
            metadata = result.get("metadata") if isinstance(result, dict) else None
            if not isinstance(metadata, dict) or not metadata.get("document_id"):
                continue

            search_results.append(
                {
                    "id": str(result.get("id") or ""),
                    "content": str(result.get("content") or ""),
                    "score": float(result.get("score") or 0.0),
                    "source": metadata.get("file_name") or metadata.get("original_filename") or metadata.get("source") or "Unknown",
                    "metadata": metadata,
                }
            )
            if len(search_results) >= top_k:
                break
        return search_results
