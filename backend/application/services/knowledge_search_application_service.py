from __future__ import annotations

import uuid
from types import SimpleNamespace
from typing import Any

from backend.application.services.knowledge_base_service_support import KnowledgeBaseServiceSupport, logger
from backend.core.config_manager import get_config_manager
from backend.file_processors.document_registry import normalize_search_file_type


class KnowledgeSearchApplicationService(KnowledgeBaseServiceSupport):
    """知识库检索应用服务。"""

    # 中文说明：以下默认值只作为配置缺失时的兜底；权威来源位于 `config/base/agent.yaml`。
    DEFAULT_MAX_RETRIEVAL_CANDIDATES = 30
    DEFAULT_MAX_RERANK_RESULTS = 10

    async def search_knowledge(
        self,
        *,
        user_id: str,
        query: str,
        top_k: int,
        knowledge_base_id: str | None,
        file_type: str | None = None,
        retrieval_options: dict[str, Any] | None = None,
        request_id: str | None = None,
    ):
        """执行知识库检索，并将 Retrieval Agent 结果整理为统一结构。"""
        # 中文说明：对外允许传入任意正整数，但知识搜索链路内部统一钳制到固定上限，
        # 避免召回过多噪声结果，也避免最终返回条数漂移。
        requested_top_k = self._normalize_requested_top_k(top_k)
        normalized_file_type = normalize_search_file_type(file_type)
        vector_search_filter: dict[str, Any] = {}
        if knowledge_base_id:
            knowledge_base = self.get_user_knowledge_base(user_id=user_id, knowledge_base_id=knowledge_base_id)
            if not knowledge_base:
                raise ValueError("知识库不存在或无权访问")
            vector_search_filter["knowledge_base_id"] = knowledge_base_id
        if normalized_file_type:
            # 中文说明：文件类型过滤属于检索契约的一部分，统一下沉到向量过滤条件中。
            vector_search_filter["file_type"] = normalized_file_type

        logger.info(
            "Searching knowledge: request_id=%s user_id=%s knowledge_base_id=%s file_type=%s top_k=%s",
            request_id,
            user_id,
            knowledge_base_id,
            normalized_file_type,
            requested_top_k,
        )

        retrieval_output = await self._get_retrieval_executor().execute(
            self._build_search_agent_input(
                user_id=user_id,
                query=query,
                top_k=requested_top_k,
                knowledge_base_id=knowledge_base_id,
                file_type=normalized_file_type,
                vector_search_filter=vector_search_filter,
                retrieval_options=retrieval_options,
                request_id=request_id,
            )
        )
        if retrieval_output.is_failed():
            raise RuntimeError(retrieval_output.error_message or "知识库检索失败")

        return self._format_search_results(
            retrieval_output.get_metadata("retrieval_results", []) or [],
            top_k=min(requested_top_k, self._get_search_policy()["max_rerank_results"]),
        )

    @classmethod
    def _normalize_requested_top_k(cls, top_k: int) -> int:
        """把外部请求的 top_k 规范化为安全正整数。"""
        try:
            normalized_top_k = int(top_k)
        except (TypeError, ValueError):
            normalized_top_k = cls._get_search_policy()["max_rerank_results"]
        if normalized_top_k <= 0:
            return cls._get_search_policy()["max_rerank_results"]
        return normalized_top_k

    @classmethod
    def _get_search_policy(cls) -> dict[str, Any]:
        """从配置中心读取知识检索固定策略。"""
        retrieval_agent_config = get_config_manager().get_agent_config("retrieval")

        def _coerce_positive_int(value: Any, default: int) -> int:
            try:
                normalized_value = int(value)
            except (TypeError, ValueError):
                return default
            return normalized_value if normalized_value > 0 else default

        def _coerce_bool(value: Any, default: bool) -> bool:
            if value is None:
                return default
            if isinstance(value, bool):
                return value
            return str(value).strip().lower() in {"1", "true", "yes", "on"}

        return {
            "max_retrieval_candidates": _coerce_positive_int(
                retrieval_agent_config.get("max_retrieval_candidates"),
                cls.DEFAULT_MAX_RETRIEVAL_CANDIDATES,
            ),
            "max_rerank_results": _coerce_positive_int(
                retrieval_agent_config.get("max_rerank_results"),
                cls.DEFAULT_MAX_RERANK_RESULTS,
            ),
            "force_hybrid_retrieval": _coerce_bool(retrieval_agent_config.get("force_hybrid_retrieval"), True),
            "force_exact_phrase": _coerce_bool(retrieval_agent_config.get("force_exact_phrase"), True),
            "force_sparse_keyword": _coerce_bool(retrieval_agent_config.get("force_sparse_keyword"), True),
            "force_dense_vector": _coerce_bool(retrieval_agent_config.get("force_dense_vector"), True),
            "force_rerank": _coerce_bool(retrieval_agent_config.get("force_rerank"), True),
        }

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
        knowledge_base_id: str | None,
        file_type: str | None,
        vector_search_filter: dict[str, Any],
        retrieval_options: dict[str, Any] | None,
        request_id: str | None,
    ):
        """构造知识库搜索所需的标准 Agent 输入。"""
        search_request_id = request_id or str(uuid.uuid4())
        search_policy = KnowledgeSearchApplicationService._get_search_policy()
        requested_top_k = KnowledgeSearchApplicationService._normalize_requested_top_k(top_k)
        merged_retrieval_options = {
            # 中文说明：知识库检索固定策略统一来自配置中心，避免实现层多处手写并行维护。
            "top_k": search_policy["max_retrieval_candidates"],
            "rerank_top_k": min(requested_top_k, search_policy["max_rerank_results"]),
            "keyword_top_k": search_policy["max_retrieval_candidates"],
            "enable_hybrid_retrieval": search_policy["force_hybrid_retrieval"],
            "enable_exact_phrase": search_policy["force_exact_phrase"],
            "enable_sparse_keyword": search_policy["force_sparse_keyword"],
            "enable_dense_vector": search_policy["force_dense_vector"],
            "enable_rerank": search_policy["force_rerank"],
        }
        if isinstance(retrieval_options, dict):
            # 中文说明：调用方允许补充非核心检索参数，但不能覆盖知识搜索主链路的固定策略。
            for option_name, option_value in retrieval_options.items():
                if option_name in merged_retrieval_options:
                    continue
                merged_retrieval_options[option_name] = option_value

        normalized_file_type = str(file_type).strip().lower() if file_type else None
        normalized_vector_search_filter = dict(vector_search_filter)
        if knowledge_base_id:
            normalized_vector_search_filter.setdefault("knowledge_base_id", knowledge_base_id)
        if normalized_file_type:
            normalized_vector_search_filter.setdefault("file_type", normalized_file_type)

        return SimpleNamespace(
            user_id=user_id,
            knowledge_base_id=knowledge_base_id,
            file_type=normalized_file_type,
            vector_search_filter=normalized_vector_search_filter,
            conversation_id=f"knowledge-search-{search_request_id}",
            message_id=f"knowledge-search-{search_request_id}",
            content=query,
            conversation_history=[],
            metadata={
                "vector_search_filter": normalized_vector_search_filter,
                "retrieval_options": merged_retrieval_options,
                "request_id": request_id,
                "search_source": "knowledge_api",
            },
        )

    @staticmethod
    def _format_search_results(retrieval_results: list[dict[str, Any]], *, top_k: int) -> list[dict[str, Any]]:
        """把 Retrieval Agent 的输出映射成知识库搜索响应结构。"""
        search_results = []
        invalid_result_count = 0
        for result in retrieval_results:
            metadata = result.get("metadata") if isinstance(result, dict) else None
            if not isinstance(metadata, dict) or not metadata.get("document_id"):
                invalid_result_count += 1
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

        if retrieval_results and not search_results and invalid_result_count > 0:
            raise RuntimeError("知识库检索结果缺少 document_id，无法构建标准响应")
        return search_results
