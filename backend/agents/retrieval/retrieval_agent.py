# -*- coding: utf-8 -*-

from __future__ import annotations

"""
检索 Agent 模块。

本模块负责把查询改写、稀疏召回、向量召回、精确短语匹配、
融合排序和结果重排串联成一条完整的检索流水线。
"""


import asyncio
import json
import logging
import re
import time
import unicodedata
from dataclasses import dataclass
from types import SimpleNamespace
from typing import Any, AsyncGenerator, Dict, List, Optional

from backend.agents.base.agent_input import AgentInput
from backend.agents.base.agent_output import AgentOutput
from backend.agents.base.base_agent import BaseAgent
from backend.agents.base.stream_chunk import StreamChunk
from backend.agents.retrieval.keyword_retriever import KeywordRetriever
from backend.agents.retrieval.query_rewriter import QueryRewriter
from backend.agents.retrieval.reranker import Reranker
from backend.application.services.agent_execution_application_service import AgentExecutionApplicationService
from backend.application.services.retrieval_persistence_application_service import RetrievalPersistenceApplicationService
from backend.models.agent_execution import AgentExecutionCreate, AgentExecutionUpdate
from backend.utils.vector_db_client import get_vector_db_client


@dataclass
class RetrievalPipelineResult:
    """
    检索流水线结果对象。
    
    用于把一次检索请求中的关键中间结果聚合在一起，
    方便同步执行、流式执行以及执行记录持久化复用。
    """
    # `rewrite_info`：查询改写阶段输出的结构化信息。
    rewrite_info: Dict[str, Any]
    # `search_queries`：最终参与召回的查询列表。
    search_queries: List[str]
    # `raw_results`：融合排序后的原始候选结果。
    raw_results: List[Dict[str, Any]]
    # `reranked_results`：最终重排完成的结果列表。
    reranked_results: List[Dict[str, Any]]


class RetrievalAgent(BaseAgent):
    """
    检索 Agent。
    
    负责串联查询改写、精确短语匹配、关键词检索、向量检索、
    结果融合、重排和执行记录持久化，是检索链路的核心编排入口。
    """
    def __init__(self):
        """
        初始化检索 Agent 依赖、配置参数和可选向量库客户端。
        
        这里集中完成组件装配，避免后续执行过程中重复读取配置或重复初始化依赖。
        """
        super().__init__(agent_name="RetrievalAgent", agent_type="retrieval")
        # `query_rewriter`: rewrites user input into retrieval-friendly queries.
        self.query_rewriter = QueryRewriter()
        # `enable_rerank`: whether reranking is enabled.
        self.enable_rerank = self._coerce_bool(self._get_config_value("enable_rerank", True), True)
        # `keyword_retriever`: builds and searches keyword indexes.
        # `reranker`: reranks recalled documents.
        self.keyword_retriever = KeywordRetriever()
        # `execution_service`: persists agent execution records.
        self.reranker = Reranker(enable_rerank=self.enable_rerank)
        # `retrieval_persistence_service`: persists retrieval results and fallback rows.
        self.retrieval_persistence_service = RetrievalPersistenceApplicationService()

        # `top_k`: default number of recalled items.
        self.top_k = int(self._get_config_value("top_k", 10))
        # `rerank_top_k`: number of items entering rerank stage.
        self.rerank_top_k = int(self._get_config_value("rerank_top_k", 10))
        # `keyword_top_k`: candidate count for keyword retrieval.
        self.keyword_top_k = int(self._get_config_value("keyword_top_k", max(self.top_k * 2, 8)))
        # `keyword_min_score`: minimum keyword-match score threshold.
        self.keyword_min_score = float(self._get_config_value("keyword_min_score", 0.05))
        # `similarity_threshold`: minimum vector-similarity threshold.
        self.similarity_threshold = float(self._get_config_value("similarity_threshold", 0.0))
        # `enable_hybrid_retrieval`: whether vector and keyword retrieval run together.
        self.enable_hybrid_retrieval = self._coerce_bool(
            self._get_config_value("enable_hybrid_retrieval", True),
            True,
        )
        self.enable_query_rewrite = self._coerce_bool(
            self._get_config_value("enable_query_rewrite", True),
            True,
        )
        self.vector_weight = float(self._get_config_value("vector_weight", 0.65))
        # `keyword_weight`：融合排序中关键词检索分数的权重。
        self.keyword_weight = float(self._get_config_value("keyword_weight", 0.35))
        # `distance_metric`：向量库返回距离值所采用的度量方式。
        self.distance_metric = "l2"

        try:
            # `vector_store`：向量数据库客户端，负责执行向量召回。
            self.vector_store = get_vector_db_client()
            # `vector_enabled`：标记当前环境是否成功启用了向量检索能力。
            self.vector_enabled = True
        except Exception:
            # `vector_store`：向量数据库客户端初始化失败时置空。
            self.vector_store = None
            # `vector_enabled`：当前环境未启用向量检索能力。
            self.vector_enabled = False

    @staticmethod
    def _safe_preview(value: Any, max_length: int = 120) -> str:
        """
        把任意值转换为安全的短文本摘要，便于日志输出。
        
        该方法会限制长度并兜底异常字符串转换，
        防止日志中出现过长对象或不可序列化值。
        """
        text = str(value).replace("\n", "\\n")
        return text if len(text) <= max_length else f"{text[:max_length]}..."

    def _summarize_payload(self, payload: Any) -> str:
        """
        为复杂载荷生成紧凑描述，减少日志噪音。
        """
        if payload is None:
            return "None"
        if isinstance(payload, dict):
            keys = list(payload.keys())
            return f"dict(keys={keys[:8]}{'...' if len(keys) > 8 else ''})"
        if isinstance(payload, list):
            item_type = type(payload[0]).__name__ if payload else "empty"
            return f"list(len={len(payload)}, item_type={item_type})"
        return self._safe_preview(payload)

    @staticmethod
    def _coerce_positive_int(value: Any, default: int) -> int:
        """
        把输入值规范化为正整数，非法时回退默认值。
        """
        try:
            normalized = int(value)
        except (TypeError, ValueError):
            return int(default)
        return normalized if normalized > 0 else int(default)

    @staticmethod
    def _coerce_bool(value: Any, default: bool) -> bool:
        """
        把输入值规范化为布尔值，兼容数字和字符串表示。
        """
        if value is None:
            return bool(default)
        if isinstance(value, bool):
            return value
        if isinstance(value, (int, float)):
            return bool(value)
        normalized = str(value).strip().lower()
        if normalized in {"1", "true", "yes", "on"}:
            return True
        if normalized in {"0", "false", "no", "off"}:
            return False
        return bool(default)

    @staticmethod
    def _get_retrieval_options(agent_input: Any) -> Dict[str, Any]:
        """
        从输入对象及其 `metadata` 中汇总检索选项。
        
        显式字段优先级高于 `metadata.retrieval_options`，
        这样既兼容不同调用方式，也保持行为可预测。
        """
        options: Dict[str, Any] = {}
        for option_name in (
            "top_k",
            "enable_query_rewrite",
            "enable_rerank",
            "enable_hybrid_retrieval",
            "rerank_top_k",
            "keyword_top_k",
            "enable_exact_phrase",
            "enable_sparse_keyword",
            "enable_dense_vector",
            "enable_fusion_rank",
        ):
            option_value = getattr(agent_input, option_name, None)
            if option_value is not None:
                options[option_name] = option_value
        metadata = getattr(agent_input, "metadata", None)
        if not isinstance(metadata, dict):
            return options

        metadata_options = metadata.get("retrieval_options")
        if not isinstance(metadata_options, dict):
            return options

        for key, value in metadata_options.items():
            options.setdefault(key, value)
        return options

    def _resolve_retrieval_option(self, agent_input: Any, option_name: str, default: int) -> int:
        """
        解析单个整数型检索选项，并返回安全默认值。
        """
        return self._coerce_positive_int(self._get_retrieval_options(agent_input).get(option_name), default)

    def _resolve_retrieval_bool_option(self, agent_input: Any, option_name: str, default: bool) -> bool:
        """
        解析单个布尔型检索选项，并返回安全默认值。
        """
        return self._coerce_bool(self._get_retrieval_options(agent_input).get(option_name), default)

    @staticmethod
    def _get_conversation_history(agent_input: Any) -> List[Dict[str, Any]]:
        """
        兼容不同输入结构，提取历史对话列表。
        """
        if isinstance(agent_input, AgentInput):
            return agent_input.get_conversation_history()
        history = getattr(agent_input, "conversation_history", None)
        return history if isinstance(history, list) else []

    def _extract_exact_phrases(self, query: str) -> List[str]:
        """
        从查询中提取精确短语，供短语匹配和重排使用。
        """
        text = (query or "").strip()
        if not text:
            return []
        phrases: List[str] = []
        quote_pairs = [
            ('"', '"'),
            ("'", "'"),
            ("\u201c", "\u201d"),
            ("\u2018", "\u2019"),
        ]
        for start_quote, end_quote in quote_pairs:
            search_from = 0
            while search_from < len(text):
                start_index = text.find(start_quote, search_from)
                if start_index < 0:
                    break
                end_index = text.find(end_quote, start_index + len(start_quote))
                if end_index < 0:
                    break
                candidate = text[start_index + len(start_quote):end_index].strip()
                if len(candidate) >= 2 and candidate not in phrases:
                    phrases.append(candidate)
                search_from = end_index + len(end_quote)
        return phrases

    def _build_search_queries(
        self,
        original_query: str,
        rewrite_result: Dict[str, Any],
        agent_input: Optional[Any] = None,
    ) -> List[str]:
        """
        基于原始查询和改写结果构建最终检索查询列表。
        
        该方法会合并原始问题、精确短语和模型改写结果，
        同时做去重与顺序控制，避免重复搜索。
        """
        include_exact_phrase = True
        if agent_input is not None:
            include_exact_phrase = self._resolve_retrieval_bool_option(agent_input, "enable_exact_phrase", True)
        queries: List[str] = []
        exact_phrases = self._extract_exact_phrases(original_query) if include_exact_phrase else []
        for query in [original_query, *exact_phrases, *(rewrite_result.get("rewritten_queries", []) or [])]:
            normalized = re.sub(r"\s+", " ", str(query or "")).strip()
            if normalized and normalized not in queries:
                queries.append(normalized)
        return queries

    @staticmethod
    def _flatten_collection_values(values: Any) -> List[Any]:
        """
        把多层集合值拍平成一维列表，便于统一比较与处理。
        """
        if values is None:
            return []
        if isinstance(values, list) and values and isinstance(values[0], list):
            flattened: List[Any] = []
            for item in values:
                flattened.extend(item if isinstance(item, list) else [item])
            return flattened
        return list(values) if isinstance(values, list) else [values]

    def _normalize_text(self, text: str) -> str:
        """
        对文本做标准化处理，统一大小写和空白。
        """
        normalized = unicodedata.normalize("NFKC", str(text or "")).lower()
        normalized = re.sub(r"[\s\W_]+", " ", normalized)
        return normalized.strip()

    def _convert_distance_to_similarity(self, distance: float) -> float:
        """
        把向量距离转换为相似度，便于与其他分数融合。
        """
        try:
            distance_value = float(distance)
        except (TypeError, ValueError):
            return 0.0
        if self.distance_metric == "l2":
            return max(0.0, 1.0 - distance_value)
        return max(0.0, 1.0 - distance_value)

    def _build_vector_search_filter(self, agent_input: AgentInput) -> Dict[str, Any]:
        """
        根据输入参数构建向量检索过滤条件。
        
        该过滤条件通常包含用户隔离、知识库隔离和调用方显式传入的附加条件。
        """
        search_filter: Dict[str, Any] = {}
        user_id = getattr(agent_input, "user_id", None)
        if user_id:
            search_filter["user_id"] = user_id

        knowledge_base_id = None
        if isinstance(agent_input, AgentInput):
            knowledge_base_id = agent_input.get_knowledge_base_id()
        else:
            knowledge_base_id = getattr(agent_input, "knowledge_base_id", None)
        if knowledge_base_id:
            search_filter["knowledge_base_id"] = knowledge_base_id

        explicit_filter = getattr(agent_input, "vector_search_filter", None)
        if not isinstance(explicit_filter, dict):
            metadata = getattr(agent_input, "metadata", None)
            if isinstance(metadata, dict):
                candidate_filter = metadata.get("vector_search_filter")
                if isinstance(candidate_filter, dict):
                    explicit_filter = candidate_filter
        if isinstance(explicit_filter, dict):
            for key, value in explicit_filter.items():
                if key == "user_id":
                    continue
                if value is not None:
                    search_filter[key] = value
        return search_filter

    def _load_filtered_corpus(self, search_filter: Dict[str, Any]) -> Dict[str, Any]:
        """
        按过滤条件加载可用于检索的语料。
        
        优先从向量库读取已索引文档；若当前客户端结构不同，
        则兼容底层 `collection.get` 访问方式。
        """
        result: Dict[str, Any]
        if hasattr(self.vector_store, "get_documents"):
            result = self.vector_store.get_documents(where=search_filter, include=["documents", "metadatas"])
        else:
            collection = getattr(self.vector_store, "collection", None)
            if collection is None or not hasattr(collection, "get"):
                return {"ids": [], "documents": [], "metadatas": []}
            normalized_filter = search_filter
            normalize_where_filter = getattr(self.vector_store, "normalize_where_filter", None)
            if callable(normalize_where_filter):
                normalized_filter = normalize_where_filter(search_filter)
            result = collection.get(where=normalized_filter, include=["documents", "metadatas"])
        return {
            "ids": self._flatten_collection_values(result.get("ids", [])),
            "documents": [str(item or "") for item in self._flatten_collection_values(result.get("documents", []))],
            "metadatas": [dict(item or {}) for item in self._flatten_collection_values(result.get("metadatas", []))],
        }

    @staticmethod
    def _coerce_metadata_dict(value: Any) -> Dict[str, Any]:
        """
        把任意元数据值安全转换为字典。
        """
        if isinstance(value, dict):
            return dict(value)
        if isinstance(value, str) and value.strip():
            try:
                parsed = json.loads(value)
            except json.JSONDecodeError:
                return {}
            return dict(parsed) if isinstance(parsed, dict) else {}
        return {}

    @staticmethod
    def _matches_search_filter(row: Dict[str, Any], file_metadata: Dict[str, Any], search_filter: Dict[str, Any]) -> bool:
        """
        判断一条记录是否满足当前检索过滤条件。
        """
        for key, expected_value in search_filter.items():
            actual = row.get(key)
            if actual is None:
                actual = file_metadata.get(key)
            if actual != expected_value:
                return False
        return True

    def _load_database_fallback_corpus(self, search_filter: Dict[str, Any]) -> Dict[str, Any]:
        """
        在向量库不可用或无数据时，从数据库回退加载语料。
        """
        user_id = search_filter.get("user_id")
        if not user_id:
            return {"ids": [], "documents": [], "metadatas": []}

        rows = []
        service = getattr(self, "retrieval_persistence_service", None)
        fetch_rows = getattr(service, "fetch_fallback_rows", None)
        if callable(fetch_rows):
            rows = fetch_rows(user_id)
        else:
            db_manager = getattr(self, "db_manager", None)
            execute_query = getattr(db_manager, "execute_query", None)
            if callable(execute_query):
                rows = execute_query(
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
            else:
                return {"ids": [], "documents": [], "metadatas": []}
        ids: List[str] = []
        documents: List[str] = []
        metadatas: List[Dict[str, Any]] = []
        for row in rows or []:
            if not isinstance(row, dict):
                continue
            file_metadata = self._coerce_metadata_dict(row.get("file_metadata") or row.get("metadata"))
            chunk_metadata = self._coerce_metadata_dict(row.get("chunk_metadata"))
            if not self._matches_search_filter(row, file_metadata, search_filter):
                continue
            chunk_id = row.get("chunk_id")
            content = row.get("content") or ""
            if not chunk_id or not content:
                continue
            metadata = {**file_metadata, **chunk_metadata}
            metadata.setdefault("file_id", row.get("file_id"))
            metadata.setdefault("chunk_index", row.get("chunk_index"))
            metadata.setdefault("page_number", row.get("page_number"))
            metadata.setdefault("user_id", row.get("user_id"))
            metadata.setdefault("conversation_id", row.get("conversation_id"))
            metadata.setdefault("file_name", row.get("original_filename"))
            metadata.setdefault("original_filename", row.get("original_filename"))
            metadata.setdefault("file_type", row.get("file_type"))
            metadata.setdefault("source", row.get("original_filename"))
            ids.append(str(chunk_id))
            documents.append(str(content))
            metadatas.append(metadata)
        return {"ids": ids, "documents": documents, "metadatas": metadatas}

    def _build_keyword_index(
        self,
        corpus: Dict[str, Any],
        *,
        enable_hybrid_retrieval: bool | None = None,
    ) -> Dict[str, Any]:
        """Build the keyword-search index structure."""
        hybrid_enabled = getattr(self, "enable_hybrid_retrieval", True) if enable_hybrid_retrieval is None else enable_hybrid_retrieval
        if not hybrid_enabled:
            return {}
        ids = corpus.get("ids", []) or []
        documents = corpus.get("documents", []) or []
        metadatas = corpus.get("metadatas", []) or []
        return self.keyword_retriever.build_index(ids, documents, metadatas) if ids and documents else {}

    def _search_keyword_matches(
        self,
        query: str,
        keyword_index: Dict[str, Any],
        *,
        top_k: int,
        min_score: float,
    ) -> List[Dict[str, Any]]:
        """Run keyword search and normalize matched results."""
        if not query or not keyword_index:
            return []
        results = self.keyword_retriever.search(keyword_index, query, top_k=top_k)
        filtered: List[Dict[str, Any]] = []
        for item in results:
            score = float(item.get("score", 0.0) or 0.0)
            if score < min_score:
                continue
            metadata = dict(item.get("metadata") or {})
            metadata["keyword_score"] = score
            filtered.append({
                "id": item.get("id"),
                "content": item.get("content", ""),
                "score": score,
                "metadata": metadata,
            })
        return filtered

    def _search_exact_phrases(self, phrases: List[str], corpus: Dict[str, Any]) -> List[Dict[str, Any]]:
        """Run exact-phrase matches over the corpus and deduplicate results."""
        if not phrases:
            return []
        matched_results: Dict[str, Dict[str, Any]] = {}
        ids = corpus.get("ids", []) or []
        documents = corpus.get("documents", []) or []
        metadatas = corpus.get("metadatas", []) or []
        if not phrases:
            return []
        matched_results: Dict[str, Dict[str, Any]] = {}
        ids = corpus.get("ids", []) or []
        documents = corpus.get("documents", []) or []
        metadatas = corpus.get("metadatas", []) or []
        for phrase in phrases:
            normalized_phrase = self._normalize_text(phrase)
            if not normalized_phrase:
                continue
            for index, doc_id in enumerate(ids):
                content = documents[index] if index < len(documents) else ""
                metadata = dict(metadatas[index] if index < len(metadatas) else {})
                structured_text = " ".join(
                    str(metadata.get(field, "") or "")
                    for field in (
                        "section_title",
                        "section_path",
                        "sheet_name",
                        "structured_terms",
                        "symbol_name",
                        "node_name",
                        "leaf_value",
                        "column_headers",
                        "source",
                        "file_name",
                    )
                )
                normalized_content = self._normalize_text("\n".join(part for part in [content, structured_text] if part))
                if normalized_phrase and normalized_phrase in normalized_content:
                    result_key = str(doc_id)
                    existing = matched_results.get(result_key)
                    if existing is None:
                        metadata["matched_phrases"] = [phrase]
                        metadata["exact_phrase_match"] = True
                        metadata["exact_phrase_score"] = 0.98
                        matched_results[result_key] = {
                            "id": doc_id,
                            "content": content,
                            "score": 0.98,
                            "metadata": metadata,
                        }
                        continue

                    existing_metadata = existing.setdefault("metadata", {})
                    matched_phrases = list(existing_metadata.get("matched_phrases") or [])
                    if phrase not in matched_phrases:
                        matched_phrases.append(phrase)
                    existing_metadata["matched_phrases"] = matched_phrases
                    existing_metadata["exact_phrase_match"] = True
                    existing_metadata["exact_phrase_score"] = max(
                        float(existing_metadata.get("exact_phrase_score", 0.0) or 0.0),
                        0.98,
                    )
                    existing["score"] = max(float(existing.get("score", 0.0) or 0.0), 0.98)
        return list(matched_results.values())

    def _merge_retrieval_result(
        self,
        aggregated_results: Dict[str, Dict[str, Any]],
        candidate: Dict[str, Any],
        *,
        matched_query: Optional[str],
        match_source: str,
    ) -> None:
        """
        把多路召回结果合并到统一聚合结构中。
        
        同一文档可能来自向量、关键词和短语多种召回来源，
        这里负责合并分数、来源标记和命中查询信息。
        """
        doc_id = str(candidate.get("id") or "")
        if not doc_id:
            return
        candidate_content = candidate.get("content") or ""
        candidate_score = float(candidate.get("score", 0.0) or 0.0)
        candidate_metadata = dict(candidate.get("metadata") or {})

        matched_queries = list(candidate_metadata.get("matched_queries") or [])
        if matched_query and matched_query not in matched_queries:
            matched_queries.append(matched_query)
        if matched_queries:
            candidate_metadata["matched_queries"] = matched_queries
            candidate_metadata["query_hit_count"] = len(matched_queries)

        match_sources = list(candidate_metadata.get("match_sources") or [])
        if match_source and match_source not in match_sources:
            match_sources.append(match_source)
        if match_sources:
            candidate_metadata["match_sources"] = match_sources

        score_field = {
            "vector": "vector_score",
            "keyword": "keyword_score",
            "text": "keyword_score",
            "exact_phrase": "exact_phrase_score",
        }.get(match_source)
        if score_field:
            candidate_metadata[score_field] = max(float(candidate_metadata.get(score_field, 0.0) or 0.0), candidate_score)
        if match_source == "exact_phrase":
            candidate_metadata["exact_phrase_match"] = True

        existing = aggregated_results.get(doc_id)
        if existing is None:
            aggregated_results[doc_id] = {
                "id": doc_id,
                "content": candidate_content,
                "score": candidate_score,
                "metadata": candidate_metadata,
            }
            return

        existing_metadata = dict(existing.get("metadata") or {})
        for field in ("matched_queries", "match_sources", "matched_phrases"):
            values = list(existing_metadata.get(field) or [])
            for value in candidate_metadata.get(field, []) or []:
                if value not in values:
                    values.append(value)
            if values:
                existing_metadata[field] = values

        existing_metadata["query_hit_count"] = len(existing_metadata.get("matched_queries") or [])
        for numeric_field in ("vector_score", "keyword_score", "exact_phrase_score"):
            existing_metadata[numeric_field] = max(
                float(existing_metadata.get(numeric_field, 0.0) or 0.0),
                float(candidate_metadata.get(numeric_field, 0.0) or 0.0),
            )
        if candidate_metadata.get("exact_phrase_match"):
            existing_metadata["exact_phrase_match"] = True
        if candidate_score >= float(existing.get("score", 0.0) or 0.0):
            existing["score"] = candidate_score
            if candidate_content:
                existing["content"] = candidate_content
        existing["metadata"] = existing_metadata

    def _rank_aggregated_results(
        self,
        aggregated_results: Dict[str, Dict[str, Any]],
        *,
        enable_fusion_rank: bool = True,
    ) -> List[Dict[str, Any]]:
        """
        对聚合后的多路结果执行融合排序。
        
        融合排序会综合向量分、关键词分、精确短语分和命中次数，
        用于生成进入重排阶段前的稳定候选集合。
        """
        ranked_results: List[Dict[str, Any]] = []
        vector_weight = float(getattr(self, "vector_weight", 0.65) or 0.65)
        keyword_weight = float(getattr(self, "keyword_weight", 0.35) or 0.35)
        total_weight = vector_weight + keyword_weight
        vector_weight = vector_weight / total_weight if total_weight > 0 else 0.65
        keyword_weight = keyword_weight / total_weight if total_weight > 0 else 0.35

        for result in aggregated_results.values():
            metadata = dict(result.get("metadata") or {})
            query_hit_count = len(metadata.get("matched_queries") or [])
            metadata["query_hit_count"] = query_hit_count
            vector_score = float(metadata.get("vector_score", 0.0) or 0.0)
            keyword_score = float(metadata.get("keyword_score", 0.0) or 0.0)
            exact_phrase_score = float(metadata.get("exact_phrase_score", 0.0) or 0.0)
            fused_score = (
                vector_weight * vector_score + keyword_weight * keyword_score
                if enable_fusion_rank and vector_score > 0 and keyword_score > 0
                else max(vector_score, keyword_score)
            )
            base_score = max(fused_score, exact_phrase_score, float(result.get("score", 0.0) or 0.0))
            bonus = 0.0
            if enable_fusion_rank and vector_score > 0 and keyword_score > 0:
                bonus += 0.02
            if metadata.get("exact_phrase_match"):
                bonus += 0.03
            if query_hit_count > 1:
                bonus += min(0.08, 0.02 * (query_hit_count - 1))
            final_score = min(1.0, base_score + bonus)
            metadata["score_components"] = {
                "vector_score": vector_score,
                "keyword_score": keyword_score,
                "exact_phrase_score": exact_phrase_score,
                "fused_score": fused_score,
                "bonus": bonus,
                "final_score": final_score,
            }
            ranked_results.append({**result, "score": final_score, "metadata": metadata})

        ranked_results.sort(
            key=lambda item: (
                item.get("score", 0.0),
                item.get("metadata", {}).get("query_hit_count", 0),
                len(item.get("metadata", {}).get("match_sources", []) or []),
                1 if item.get("metadata", {}).get("exact_phrase_match") else 0,
            ),
            reverse=True,
        )
        return ranked_results

    async def _retrieve_documents(self, queries: List[str], agent_input: AgentInput) -> List[Dict[str, Any]]:
        """
        执行完整召回流程，组合向量、关键词和短语检索。
        """
        if not queries:
            return []
        effective_top_k = self._resolve_retrieval_option(agent_input, "top_k", int(getattr(self, "top_k", 10)))
        effective_rerank_top_k = self._resolve_retrieval_option(agent_input, "rerank_top_k", int(getattr(self, "rerank_top_k", effective_top_k)))
        effective_keyword_top_k = self._resolve_retrieval_option(agent_input, "keyword_top_k", int(getattr(self, "keyword_top_k", max(effective_top_k * 2, 8))))
        enable_exact_phrase = self._resolve_retrieval_bool_option(agent_input, "enable_exact_phrase", True)
        enable_keyword_search = self._resolve_retrieval_bool_option(agent_input, "enable_sparse_keyword", True)
        enable_dense_vector = self._resolve_retrieval_bool_option(agent_input, "enable_dense_vector", getattr(self, "vector_enabled", False))
        enable_fusion_rank = self._resolve_retrieval_bool_option(agent_input, "enable_fusion_rank", True)
        enable_hybrid_retrieval = self._resolve_retrieval_bool_option(
            agent_input,
            "enable_hybrid_retrieval",
            getattr(self, "enable_hybrid_retrieval", True),
        )
        aggregated_results: Dict[str, Dict[str, Any]] = {}
        search_filter = self._build_vector_search_filter(agent_input)
        corpus = self._load_filtered_corpus(search_filter)
        using_database_fallback_corpus = False
        if not (corpus.get("ids") or corpus.get("documents")):
            corpus = self._load_database_fallback_corpus(search_filter)
            using_database_fallback_corpus = bool(corpus.get("ids"))

        exact_phrases = self._extract_exact_phrases(getattr(agent_input, "content", "")) if enable_exact_phrase else []
        for result in self._search_exact_phrases(exact_phrases, corpus):
            matched_queries = result.get("metadata", {}).get("matched_phrases", [])
            self._merge_retrieval_result(
                aggregated_results,
                result,
                matched_query=matched_queries[0] if matched_queries else None,
                match_source="exact_phrase",
            )

        keyword_index = self._build_keyword_index(
            corpus,
            enable_hybrid_retrieval=enable_hybrid_retrieval,
        ) if enable_keyword_search else {}
        if keyword_index:
            keyword_tasks = [
                asyncio.to_thread(
                    self._search_keyword_matches,
                    query,
                    keyword_index,
                    top_k=effective_keyword_top_k,
                    min_score=self.keyword_min_score,
                )
                for query in queries
            ]
            for query, keyword_results in zip(queries, await asyncio.gather(*keyword_tasks)):
                for result in keyword_results:
                    self._merge_retrieval_result(
                        aggregated_results,
                        result,
                        matched_query=query,
                        match_source="text" if using_database_fallback_corpus else "keyword",
                    )

        if enable_dense_vector and getattr(self, "vector_enabled", False) and self.vector_store is not None:
            retrieval_limit = max(int(effective_top_k), int(effective_rerank_top_k), 10)
            tasks = [
                asyncio.to_thread(self.vector_store.search, query=query, n_results=retrieval_limit, where=search_filter)
                for query in queries
            ]
            for query, search_results in zip(queries, await asyncio.gather(*tasks)):
                if not search_results or "ids" not in search_results:
                    continue
                ids = self._flatten_collection_values(search_results.get("ids", []))
                documents = self._flatten_collection_values(search_results.get("documents", []))
                distances = self._flatten_collection_values(search_results.get("distances", []))
                metadatas = self._flatten_collection_values(search_results.get("metadatas", []))
                for index, doc_id in enumerate(ids):
                    distance = distances[index] if index < len(distances) else 1.0
                    similarity_score = self._convert_distance_to_similarity(distance)
                    if similarity_score < self.similarity_threshold:
                        continue
                    metadata = dict(metadatas[index] if index < len(metadatas) else {})
                    metadata["vector_score"] = max(float(metadata.get("vector_score", 0.0) or 0.0), similarity_score)
                    self._merge_retrieval_result(
                        aggregated_results,
                        {
                            "id": doc_id,
                            "content": documents[index] if index < len(documents) else "",
                            "score": similarity_score,
                            "metadata": metadata,
                        },
                        matched_query=query,
                        match_source="vector",
                    )

        ranked = self._rank_aggregated_results(aggregated_results, enable_fusion_rank=enable_fusion_rank)
        final_limit = max(int(effective_top_k), int(effective_rerank_top_k), 10)
        return ranked[: final_limit * max(1, len(queries))]

    async def _save_retrieval_results(self, execution_id: str, results: List[Dict[str, Any]]) -> None:
        """
        把检索结果持久化，便于追踪和审计。
        """
        service = getattr(self, "retrieval_persistence_service", None)
        save_method = getattr(service, "save_retrieval_results", None)
        if callable(save_method):
            maybe_result = save_method(execution_id, results)
            if asyncio.iscoroutine(maybe_result):
                await maybe_result

    def _get_execution_persistence(self):
        """
        返回执行记录持久化入口。
        """
        service = getattr(self, "execution_service", None)
        if service is not None:
            return service
        return getattr(self, "execution_repo", None)

    def _create_execution_record(self, execution_create: AgentExecutionCreate):
        """
        创建一条检索执行记录。
        """
        persistence = self._get_execution_persistence()
        if persistence is None:
            raise AttributeError("RetrievalAgent execution persistence is not configured")
        return persistence.create_execution(execution_create)

    def _update_execution_record(self, execution_id: str, execution_update: AgentExecutionUpdate) -> None:
        """
        Prepare retrieval queries and optionally rewrite them first.
        """
        persistence = self._get_execution_persistence()
        if persistence is None:
            raise AttributeError("RetrievalAgent execution persistence is not configured")
        persistence.update_execution(execution_id, execution_update)
    async def _prepare_retrieval_queries(self, agent_input: AgentInput) -> tuple[Dict[str, Any], List[str]]:
        """Prepare retrieval queries and optionally rewrite them first."""
        enable_query_rewrite = self._resolve_retrieval_bool_option(agent_input, "enable_query_rewrite", True)
        if enable_query_rewrite:
            rewrite_result = await self.query_rewriter.rewrite_query(
                getattr(agent_input, "content", ""),
                self._get_conversation_history(agent_input),
            )
        else:
            rewrite_result = {
                "original_query": getattr(agent_input, "content", ""),
                "rewritten_queries": [getattr(agent_input, "content", "")],
                "keywords": [],
                "reasoning": "Query rewrite disabled by retrieval options",
                "rewrite_applied": False,
            }
        search_queries = self._build_search_queries(
            getattr(agent_input, "content", ""),
            rewrite_result,
            agent_input=agent_input,
        )
        return rewrite_result, search_queries

    async def _run_retrieval_pipeline(self, agent_input: AgentInput) -> RetrievalPipelineResult:
        """Execute the full retrieval pipeline: rewrite, recall, rerank, and persist."""
        rewrite_result, search_queries = await self._prepare_retrieval_queries(agent_input)
        raw_results = await self._retrieve_documents(search_queries, agent_input)
        reranked_results = self._rerank_results(raw_results, agent_input)
        return RetrievalPipelineResult(
            rewrite_info=rewrite_result,
            search_queries=search_queries,
            raw_results=raw_results,
            reranked_results=reranked_results,
        )

    def _rerank_results(self, results: List[Dict[str, Any]], agent_input: AgentInput) -> List[Dict[str, Any]]:
        """Rerank recalled results when enabled and trim to the final size."""
        if not results:
            return []
        enable_rerank = self._resolve_retrieval_bool_option(agent_input, "enable_rerank", self.enable_rerank)
        if not enable_rerank:
            top_k = self._resolve_retrieval_option(agent_input, "top_k", int(getattr(self, "top_k", 10)))
            return list(results[:top_k])
        rerank_top_k = self._resolve_retrieval_option(
            agent_input,
            "rerank_top_k",
            int(getattr(self, "rerank_top_k", self.top_k)),
        )
        return self.reranker.rerank(results, getattr(agent_input, "content", ""), rerank_top_k)

    async def execute(self, agent_input: AgentInput) -> AgentOutput:
        """Execute retrieval in non-streaming mode."""
        start_time = time.time()
        execution = self._create_execution_record(
            AgentExecutionCreate(
                conversation_id=getattr(agent_input, "conversation_id", None),
                message_id=getattr(agent_input, "message_id", None),
                agent_name=self.agent_name,
                agent_type=self.agent_type,
                input_data={"content": getattr(agent_input, "content", "")},
            )
        )
        try:
            pipeline = await self._run_retrieval_pipeline(agent_input)
            execution_time_ms = int((time.time() - start_time) * 1000)
            payload = {
                "retrieval_results": pipeline.reranked_results,
                "rewrite_info": pipeline.rewrite_info,
                "total_results": len(pipeline.reranked_results),
            }
            self._update_execution_record(
                execution.execution_id,
                AgentExecutionUpdate(
                    output_data=payload,
                    status="success",
                    execution_time_ms=execution_time_ms,
                ),
            )
            await self._save_retrieval_results(execution.execution_id, pipeline.reranked_results)
            if not pipeline.reranked_results:
                message = self._get_prompt("no_results_prompt") or "No relevant results found"
                return self._create_output(
                    content=message,
                    status="success",
                    execution_time_ms=execution_time_ms,
                    execution_id=execution.execution_id,
                    retrieval_results=[],
                    rewrite_info=pipeline.rewrite_info,
                )
            return self._create_output(
                content=f"Found {len(pipeline.reranked_results)} relevant results",
                status="success",
                execution_time_ms=execution_time_ms,
                execution_id=execution.execution_id,
                retrieval_results=pipeline.reranked_results,
                rewrite_info=pipeline.rewrite_info,
            )
        except Exception as error:
            execution_time_ms = int((time.time() - start_time) * 1000)
            self._update_execution_record(
                execution.execution_id,
                AgentExecutionUpdate(
                    output_data={},
                    status="failed",
                    error_message=str(error),
                    execution_time_ms=execution_time_ms,
                ),
            )
            return self._create_output(
                content="",
                status="failed",
                error_message=str(error),
                execution_time_ms=execution_time_ms,
                execution_id=execution.execution_id,
            )

    async def execute_stream(self, agent_input: AgentInput) -> AsyncGenerator[StreamChunk, None]:
        """Execute retrieval in streaming mode."""
        start_time = time.time()
        execution = self._create_execution_record(
            AgentExecutionCreate(
                conversation_id=getattr(agent_input, "conversation_id", None),
                message_id=getattr(agent_input, "message_id", None),
                agent_name=self.agent_name,
                agent_type=self.agent_type,
                input_data={"content": getattr(agent_input, "content", "")},
            )
        )
        try:
            yield StreamChunk.create_thinking("Preparing retrieval queries...")
            rewrite_result, search_queries = await self._prepare_retrieval_queries(agent_input)
            query_lines = [
                getattr(agent_input, "content", ""),
                *[query for query in search_queries if query != getattr(agent_input, "content", "")],
            ]
            query_details = "\n".join(f"{index}. {query}" for index, query in enumerate(query_lines, start=1))
            yield StreamChunk.create_thinking(
                f"Generated {len(query_lines)} retrieval queries:\n{query_details}"
            )
            yield StreamChunk.create_thinking("Searching related documents...")
            raw_results = await self._retrieve_documents(search_queries, agent_input)
            reranked_results = self._rerank_results(raw_results, agent_input)
            pipeline = RetrievalPipelineResult(
                rewrite_info=rewrite_result,
                search_queries=search_queries,
                raw_results=raw_results,
                reranked_results=reranked_results,
            )
            execution_time_ms = int((time.time() - start_time) * 1000)
            payload = {
                "execution_id": execution.execution_id,
                "retrieval_results": pipeline.reranked_results,
                "rewrite_info": rewrite_result,
                "total_results": len(pipeline.reranked_results),
            }
            self._update_execution_record(
                execution.execution_id,
                AgentExecutionUpdate(
                    output_data=payload,
                    status="success",
                    execution_time_ms=execution_time_ms,
                ),
            )
            await self._save_retrieval_results(execution.execution_id, pipeline.reranked_results)
            yield StreamChunk.create_result(payload)
        except Exception as error:
            execution_time_ms = int((time.time() - start_time) * 1000)
            self._update_execution_record(
                execution.execution_id,
                AgentExecutionUpdate(
                    output_data={"error": str(error)},
                    status="failed",
                    execution_time_ms=execution_time_ms,
                ),
            )
            yield StreamChunk.create_error(str(error))
