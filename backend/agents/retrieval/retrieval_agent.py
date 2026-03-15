
from typing import AsyncGenerator, List, Dict, Any, Optional
import json
import uuid
import time
import re
import unicodedata

from backend.agents.base.base_agent import BaseAgent
from backend.agents.base.agent_input import AgentInput
from backend.agents.base.agent_output import AgentOutput
from backend.agents.base.stream_chunk import StreamChunk
from backend.agents.retrieval.query_rewriter import QueryRewriter
from backend.agents.retrieval.reranker import Reranker
from backend.agents.retrieval.keyword_retriever import KeywordRetriever
from backend.utils.vector_db_client import get_vector_db_client
from backend.database.database_manager import get_database_manager
from backend.database.repositories.agent_execution_repository import get_agent_execution_repository
from backend.database.repositories.retrieval_result_repository import get_retrieval_result_repository
from backend.models.retrieval_result import RetrievalResultCreate
from backend.models.agent_execution import AgentExecutionCreate, AgentExecutionUpdate


class RetrievalAgent(BaseAgent):
    def __init__(self):
        super().__init__(agent_name="RetrievalAgent", agent_type="retrieval")
        self.query_rewriter = QueryRewriter()

        try:
            self.vector_store = get_vector_db_client()
            self.vector_enabled = True
            doc_count = self.vector_store.get_collection_count()
            self.logger.info(f"向量数据库集合文档数量: {doc_count}")
            if doc_count == 0:
                self.logger.warning("当前向量库为空，请先导入知识文档")
        except Exception as e:
            self.logger.error(f"初始化向量数据库失败: {str(e)}")
            self.vector_store = None
            self.vector_enabled = False

        self.db_manager = get_database_manager()
        self.execution_repo = get_agent_execution_repository()
        self.retrieval_result_repo = get_retrieval_result_repository()
        self.top_k = self._get_config_value("top_k", 10)
        self.similarity_threshold = self._get_config_value("similarity_threshold", 0.7)
        self.enable_rerank = self._get_config_value("enable_rerank", True)
        self.rerank_top_k = self._get_config_value("rerank_top_k", 10)
        self.enable_summary = self._get_config_value("enable_summary", False)
        self.enable_hybrid_retrieval = self._get_config_value("enable_hybrid_retrieval", True)
        self.keyword_top_k = int(self._get_config_value("keyword_top_k", max(self.top_k * 2, 8)))
        self.keyword_min_score = float(self._get_config_value("keyword_min_score", 0.05))
        self.vector_weight = float(self._get_config_value("vector_weight", 0.65))
        self.keyword_weight = float(self._get_config_value("keyword_weight", 0.35))
        total_weight = self.vector_weight + self.keyword_weight
        if total_weight <= 0:
            self.vector_weight = 0.65
            self.keyword_weight = 0.35
        else:
            self.vector_weight /= total_weight
            self.keyword_weight /= total_weight
        self.keyword_retriever = KeywordRetriever()
        self.reranker = Reranker(enable_rerank=self.enable_rerank)
        self.distance_metric = "l2"
        self.logger.info("检索代理初始化完成")

    @staticmethod
    def _safe_preview(value: Any, max_length: int = 120) -> str:
        text = str(value).replace("\n", "\\n")
        if len(text) <= max_length:
            return text
        return f"{text[:max_length]}..."

    def _summarize_payload(self, payload: Any) -> str:
        if payload is None:
            return "None"

        if isinstance(payload, dict):
            keys = list(payload.keys())
            return f"dict(keys={keys[:8]}{'...' if len(keys) > 8 else ''})"

        if isinstance(payload, list):
            item_type = type(payload[0]).__name__ if payload else "empty"
            return f"list(len={len(payload)}, item_type={item_type})"

        if isinstance(payload, str):
            return f"str(len={len(payload)}, preview='{self._safe_preview(payload)}')"

        return f"{type(payload).__name__}({self._safe_preview(payload)})"

    async def execute(self, agent_input: AgentInput) -> AgentOutput:
        start_time = time.time()

        # 创建执行记录
        execution_create = AgentExecutionCreate(
            conversation_id=agent_input.conversation_id,
            message_id=agent_input.message_id,
            agent_name=self.agent_name,
            agent_type=self.agent_type,
            input_data={"content": agent_input.content}
        )
        execution = self.execution_repo.create_execution(execution_create)

        try:
            # 查询重写
            rewrite_result = await self.query_rewriter.rewrite_query(
                query=agent_input.content,
                conversation_history=agent_input.metadata.get("conversation_history") if agent_input.metadata else None
            )

            search_queries = self._build_search_queries(agent_input.content, rewrite_result)

            # 检索文档
            retrieval_results = await self._retrieve_documents(search_queries, agent_input)

            self.logger.info(f"检索到 {len(retrieval_results)} 条原始结果")

            # 检查是否有结果
            if not retrieval_results:
                # 无结果处理
                no_results_message = self._get_prompt("no_results_prompt")
                if not no_results_message:
                    no_results_message = "抱歉，我在知识库中没有找到与您问题相关的信息。"

                execution_time_ms = int((time.time() - start_time) * 1000)

                # 更新执行记录
                execution_update = AgentExecutionUpdate(
                    output_data={
                        "retrieval_results": [],
                        "rewrite_info": rewrite_result,
                        "message": no_results_message
                    },
                    status="success",
                    execution_time_ms=execution_time_ms
                )
                self.execution_repo.update_execution(execution.execution_id, execution_update)

                return self._create_output(
                    content=no_results_message,
                    status="success",
                    execution_time_ms=execution_time_ms,
                    execution_id=execution.execution_id,
                    retrieval_results=[],
                    rewrite_info=rewrite_result
                )

            # 重排序
            reranked_results = self.reranker.rerank(retrieval_results, agent_input.content, self.rerank_top_k)

            self.logger.info(f"重排序后剩余 {len(reranked_results)} 条结果")

            # 保存检索结果
            await self._save_retrieval_results(execution.execution_id, reranked_results)

            # 生成检索摘要（可选）
            summary = await self._generate_retrieval_summary(reranked_results, agent_input.content)

            execution_time_ms = int((time.time() - start_time) * 1000)

            # 构建输出数据
            output_data = {
                "retrieval_results": reranked_results,
                "rewrite_info": rewrite_result,
                "total_results": len(reranked_results)
            }
            if summary:
                output_data["summary"] = summary

            # 更新执行记录
            execution_update = AgentExecutionUpdate(
                output_data=output_data,
                status="success",
                execution_time_ms=execution_time_ms
            )
            self.execution_repo.update_execution(execution.execution_id, execution_update)

            # 构建返回内容
            content = f"Found {len(reranked_results)} relevant results"
            if summary and summary.get("summary"):
                content = summary.get("summary")

            return self._create_output(
                content=content,
                status="success",
                execution_time_ms=execution_time_ms,
                execution_id=execution.execution_id,
                retrieval_results=reranked_results,
                rewrite_info=rewrite_result,
                summary=summary
            )

        except Exception as e:
            self.logger.error(f"检索执行失败: {e}", exc_info=True)
            execution_time_ms = int((time.time() - start_time) * 1000)

            # 更新执行记录为失败状态
            execution_update = AgentExecutionUpdate(
                output_data={},
                status="failed",
                error_message=str(e),
                execution_time_ms=execution_time_ms
            )
            self.execution_repo.update_execution(execution.execution_id, execution_update)

            return self._create_output(
                content="",
                status="failed",
                error_message=str(e),
                execution_time_ms=execution_time_ms,
                execution_id=execution.execution_id
            )

    async def execute_stream(self, agent_input: AgentInput) -> AsyncGenerator[StreamChunk, None]:
        start_time = time.time()

        execution_create = AgentExecutionCreate(
            conversation_id=agent_input.conversation_id,
            message_id=agent_input.message_id,
            agent_name=self.agent_name,
            agent_type=self.agent_type,
            input_data={"content": agent_input.content}
        )
        execution = self.execution_repo.create_execution(execution_create)

        try:
            conversation_history = []
            if agent_input.metadata:
                conversation_history = agent_input.metadata.get("conversation_history", []) or []

            self.logger.info(
                "[RETRIEVAL] stream_start: "
                f"conversation_id={agent_input.conversation_id}, "
                f"message_id={agent_input.message_id}, "
                f"question_len={len(agent_input.content or '')}, "
                f"history_count={len(conversation_history)}"
            )

            yield StreamChunk.create_thinking("正在优化查询...")
            rewrite_result = await self.query_rewriter.rewrite_query(
                agent_input.content,
                conversation_history
            )

            rewritten_queries = self._build_search_queries(agent_input.content, rewrite_result)
            self.logger.info(
                "[RETRIEVAL] query_rewrite_done: "
                f"payload={self._summarize_payload(rewrite_result)}, "
                f"query_count={len(rewritten_queries)}, "
                f"first_query='{self._safe_preview(rewritten_queries[0]) if rewritten_queries else ''}'"
            )

            query_details = "\n".join(f"{index}. {query}" for index, query in enumerate(rewritten_queries, start=1))
            yield StreamChunk.create_thinking(f"查询已优化，生成 {len(rewritten_queries)} 个检索查询：\n{query_details}")
            yield StreamChunk.create_thinking("正在检索知识库...")
            retrieval_results = await self._retrieve_documents(rewritten_queries, agent_input)

            if not retrieval_results:
                execution_time_ms = int((time.time() - start_time) * 1000)
                output_data = {
                    "retrieval_results": [],
                    "rewrite_info": rewrite_result,
                    "total_results": 0
                }
                execution_update = AgentExecutionUpdate(
                    output_data=output_data,
                    status="success",
                    execution_time_ms=execution_time_ms
                )
                self.execution_repo.update_execution(execution.execution_id, execution_update)

                self.logger.info("[RETRIEVAL] 未检索到结果，已保存执行记录")
                yield StreamChunk.create_result(output_data, execution_id=execution.execution_id)
                return

            self.logger.info(
                "[RETRIEVAL] vector_search_done: "
                f"retrieval_results={self._summarize_payload(retrieval_results)}"
            )

            yield StreamChunk.create_thinking(f"找到{len(retrieval_results)}条相关结果")
            if self.enable_rerank:
                yield StreamChunk.create_thinking("正在重排序结果...")
            reranked_results = self.reranker.rerank(retrieval_results, agent_input.content, self.rerank_top_k)

            self.logger.info(
                "[RETRIEVAL] rerank_done: "
                f"reranked_count={len(reranked_results)}, "
                f"sample={self._summarize_payload(reranked_results[0] if reranked_results else {})}"
            )

            execution_id = execution.execution_id
            await self._save_retrieval_results(execution_id, reranked_results)

            execution_time_ms = int((time.time() - start_time) * 1000)
            execution_update = AgentExecutionUpdate(
                output_data={
                    "retrieval_results": reranked_results,
                    "rewrite_info": rewrite_result,
                    "total_results": len(reranked_results)
                },
                status="success",
                execution_time_ms=execution_time_ms
            )
            self.execution_repo.update_execution(execution.execution_id, execution_update)
            self.logger.info(f"[RETRIEVAL] 执行记录已更新: execution_id={execution.execution_id}")

            result_payload = {
                "execution_id": execution_id,
                "retrieval_results": reranked_results,
                "rewrite_info": rewrite_result,
                "total_results": len(reranked_results)
            }
            self.logger.info(
                "[RETRIEVAL] stream_result_payload="
                f"{self._summarize_payload(result_payload)}"
            )
            yield StreamChunk.create_result(result_payload)
        except Exception as e:
            self.logger.error(f"检索流式执行失败: {e}")
            execution_time_ms = int((time.time() - start_time) * 1000)
            execution_update = AgentExecutionUpdate(
                output_data={"error": str(e)},
                status="failed",
                execution_time_ms=execution_time_ms
            )
            self.execution_repo.update_execution(execution.execution_id, execution_update)
            yield StreamChunk.create_error(str(e))

    def _build_search_queries(self, original_query: str, rewrite_result: Dict[str, Any]) -> List[str]:
        queries: List[str] = []

        for query in [original_query, *self._extract_exact_phrases(original_query), *(rewrite_result.get("rewritten_queries", []) or [])]:
            normalized = unicodedata.normalize("NFKC", str(query or ""))
            normalized = re.sub(r"\s+", " ", normalized).strip()
            if normalized and normalized not in queries:
                queries.append(normalized)

        return queries

    def _extract_exact_phrases(self, query: str) -> List[str]:
        phrases: List[str] = []
        text = (query or "").strip()
        if not text:
            return phrases

        patterns = [r'“([^”]{2,})”', r'"([^"]{2,})"', r'《([^》]{2,})》']
        for pattern in patterns:
            for match in re.findall(pattern, text):
                candidate = match.strip()
                if candidate and candidate not in phrases:
                    phrases.append(candidate)

        if not phrases:
            normalized = re.sub(r'^(知识库里(?:面)?|知识库中|文档里(?:面)?|文档中|请问)\s*', '', text)
            normalized = re.sub(r'(是谁写的|作者是谁|是谁的作者|是谁写的呢|写的是谁)\s*[？?]*$', '', normalized).strip()
            normalized = normalized.strip('“”"《》')
            if len(normalized) >= 6 and normalized != text:
                phrases.append(normalized)

        return phrases

    @staticmethod
    def _flatten_collection_values(values: Any) -> List[Any]:
        if values is None:
            return []
        if isinstance(values, list) and values and isinstance(values[0], list):
            return values[0]
        if isinstance(values, tuple):
            return list(values)
        if isinstance(values, list):
            return values
        return [values]

    def _load_filtered_corpus(self, search_filter: Dict[str, Any]) -> Dict[str, Any]:
        collection = getattr(self.vector_store, "collection", None)
        if collection is None:
            return {"ids": [], "documents": [], "metadatas": []}

        normalize_filter = getattr(self.vector_store, "normalize_where_filter", None)
        normalized_filter = normalize_filter(search_filter) if callable(normalize_filter) else search_filter

        try:
            corpus = collection.get(where=normalized_filter, include=["documents", "metadatas"])
        except Exception as exc:
            self.logger.warning(f"Failed to load corpus for keyword retrieval: {exc}")
            return {"ids": [], "documents": [], "metadatas": []}

        ids = self._flatten_collection_values(corpus.get("ids", []))
        documents = self._flatten_collection_values(corpus.get("documents", []))
        metadatas = self._flatten_collection_values(corpus.get("metadatas", []))
        return {
            "ids": [str(doc_id) for doc_id in ids],
            "documents": [str(document or "") for document in documents],
            "metadatas": [dict(metadata or {}) for metadata in metadatas],
        }

    @staticmethod
    def _coerce_metadata_dict(value: Any) -> Dict[str, Any]:
        if isinstance(value, dict):
            return dict(value)

        if isinstance(value, str) and value.strip():
            try:
                parsed = json.loads(value)
            except json.JSONDecodeError:
                return {}
            if isinstance(parsed, dict):
                return parsed

        return {}

    @staticmethod
    def _matches_search_filter(row: Dict[str, Any], file_metadata: Dict[str, Any], search_filter: Dict[str, Any]) -> bool:
        for key, expected_value in search_filter.items():
            if expected_value is None:
                continue

            actual_value = row.get(key)
            if actual_value is None:
                actual_value = file_metadata.get(key)

            if actual_value != expected_value:
                return False

        return True

    def _load_database_fallback_corpus(self, search_filter: Dict[str, Any]) -> Dict[str, Any]:
        user_id = search_filter.get("user_id")
        db_manager = getattr(self, "db_manager", None)
        if not user_id or db_manager is None:
            return {"ids": [], "documents": [], "metadatas": []}

        try:
            rows = db_manager.execute_query(
                """
                SELECT fc.chunk_id, fc.chunk_index, fc.content, fc.page_number,
                       fc.file_id, f.user_id, f.conversation_id, f.original_filename,
                       f.file_type, f.metadata AS file_metadata
                FROM file_chunks fc
                INNER JOIN files f ON f.file_id = fc.file_id
                WHERE f.user_id = %s
                ORDER BY f.created_at DESC, fc.chunk_index ASC
                """,
                (user_id,),
            )
        except Exception as exc:
            self.logger.warning(f"Failed to load database fallback corpus: {exc}")
            return {"ids": [], "documents": [], "metadatas": []}

        ids: List[str] = []
        documents: List[str] = []
        metadatas: List[Dict[str, Any]] = []

        for row in rows or []:
            if not isinstance(row, dict):
                continue

            file_metadata = self._coerce_metadata_dict(row.get("file_metadata") or row.get("metadata"))
            if not self._matches_search_filter(row, file_metadata, search_filter):
                continue

            chunk_id = row.get("chunk_id")
            content = row.get("content") or ""
            if not chunk_id or not content:
                continue

            metadata = dict(file_metadata)
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

    def _build_keyword_index(self, corpus: Dict[str, Any]) -> Dict[str, Any]:
        if not getattr(self, "enable_hybrid_retrieval", True):
            return {}

        ids = corpus.get("ids", []) or []
        documents = corpus.get("documents", []) or []
        if not ids or not documents:
            return {}

        keyword_retriever = getattr(self, "keyword_retriever", None)
        if keyword_retriever is None:
            keyword_retriever = KeywordRetriever()
            self.keyword_retriever = keyword_retriever

        return keyword_retriever.build_index(
            ids=ids,
            documents=documents,
            metadatas=corpus.get("metadatas", []) or [],
        )

    def _search_keyword_matches(self, query: str, keyword_index: Dict[str, Any]) -> List[Dict[str, Any]]:
        if not query or not keyword_index:
            return []

        keyword_retriever = getattr(self, "keyword_retriever", None)
        if keyword_retriever is None:
            keyword_retriever = KeywordRetriever()
            self.keyword_retriever = keyword_retriever

        top_k = int(getattr(self, "keyword_top_k", max(getattr(self, "top_k", 5) * 2, 8)))
        min_score = float(getattr(self, "keyword_min_score", 0.05) or 0.0)
        results = keyword_retriever.search(keyword_index, query, top_k=top_k)

        filtered_results: List[Dict[str, Any]] = []
        for result in results:
            score = float(result.get("score", 0.0) or 0.0)
            if score < min_score:
                continue
            metadata = dict(result.get("metadata") or {})
            metadata["keyword_score"] = max(float(metadata.get("keyword_score", 0.0) or 0.0), score)
            filtered_results.append(
                {
                    "id": result.get("id"),
                    "content": result.get("content", ""),
                    "score": score,
                    "metadata": metadata,
                }
            )

        return filtered_results

    def _search_exact_phrases(
        self,
        phrases: List[str],
        corpus: Dict[str, Any],
    ) -> List[Dict[str, Any]]:
        if not phrases or not corpus:
            return []

        matched_results: List[Dict[str, Any]] = []
        ids = corpus.get("ids", []) or []
        documents = corpus.get("documents", []) or []
        metadatas = corpus.get("metadatas", []) or []
        normalized_corpus = [self._normalize_exact_match_text(document) for document in documents]

        for phrase in phrases:
            normalized_phrase = self._normalize_exact_match_text(phrase)
            if not normalized_phrase:
                continue

            for index, doc_id in enumerate(ids):
                content = documents[index] if index < len(documents) else ""
                normalized_content = normalized_corpus[index] if index < len(normalized_corpus) else ""
                if normalized_phrase not in normalized_content:
                    continue

                metadata = dict(metadatas[index] if index < len(metadatas) else {})
                metadata["matched_queries"] = [phrase]
                metadata["matched_phrases"] = [phrase]
                metadata["query_hit_count"] = 1
                metadata["exact_phrase_match"] = True
                match_position = normalized_content.find(normalized_phrase)
                score = min(1.0, 0.95 + max(0.0, (5000 - min(match_position, 5000)) / 100000))
                metadata["exact_phrase_score"] = score
                matched_results.append(
                    {
                        "id": doc_id,
                        "content": content,
                        "score": score,
                        "metadata": metadata,
                    }
                )

        return matched_results

    @staticmethod
    def _normalize_exact_match_text(text: str) -> str:
        normalized = unicodedata.normalize("NFKC", str(text or ""))
        return re.sub(r"\s+", "", normalized).lower()

    def _merge_retrieval_result(
        self,
        aggregated_results: Dict[str, Dict[str, Any]],
        candidate: Dict[str, Any],
        *,
        matched_query: Optional[str],
        match_source: str,
    ) -> None:
        doc_id = candidate.get("id")
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

        for list_field in ("matched_queries", "match_sources", "matched_terms", "matched_phrases"):
            merged_values = list(existing_metadata.get(list_field) or [])
            for value in candidate_metadata.get(list_field, []) or []:
                if value not in merged_values:
                    merged_values.append(value)
            if merged_values:
                existing_metadata[list_field] = merged_values

        existing_metadata["query_hit_count"] = len(existing_metadata.get("matched_queries") or [])
        if candidate_metadata.get("exact_phrase_match"):
            existing_metadata["exact_phrase_match"] = True

        for numeric_field in ("vector_score", "keyword_score", "keyword_score_raw", "exact_phrase_score"):
            existing_metadata[numeric_field] = max(
                float(existing_metadata.get(numeric_field, 0.0) or 0.0),
                float(candidate_metadata.get(numeric_field, 0.0) or 0.0),
            )

        for key, value in candidate_metadata.items():
            if key not in existing_metadata or existing_metadata.get(key) in (None, "", [], {}):
                existing_metadata[key] = value

        if candidate_score >= float(existing.get("score", 0.0) or 0.0):
            existing["score"] = candidate_score
            if candidate_content:
                existing["content"] = candidate_content
        elif candidate_content and not existing.get("content"):
            existing["content"] = candidate_content

        existing["metadata"] = existing_metadata

    def _rank_aggregated_results(
        self,
        aggregated_results: Dict[str, Dict[str, Any]],
    ) -> List[Dict[str, Any]]:
        ranked_results: List[Dict[str, Any]] = []
        vector_weight = float(getattr(self, "vector_weight", 0.65) or 0.65)
        keyword_weight = float(getattr(self, "keyword_weight", 0.35) or 0.35)
        total_weight = vector_weight + keyword_weight
        if total_weight <= 0:
            vector_weight = 0.65
            keyword_weight = 0.35
        else:
            vector_weight /= total_weight
            keyword_weight /= total_weight

        for result in aggregated_results.values():
            metadata = dict(result.get("metadata") or {})
            query_hit_count = len(metadata.get("matched_queries") or [])
            metadata["query_hit_count"] = query_hit_count

            vector_score = float(metadata.get("vector_score", 0.0) or 0.0)
            keyword_score = float(metadata.get("keyword_score", 0.0) or 0.0)
            exact_phrase_score = float(metadata.get("exact_phrase_score", 0.0) or 0.0)
            fused_score = (
                vector_weight * vector_score + keyword_weight * keyword_score
                if vector_score > 0 and keyword_score > 0
                else max(vector_score, keyword_score)
            )
            base_score = max(fused_score, exact_phrase_score, float(result.get("score", 0.0) or 0.0))

            bonus = 0.0
            if vector_score > 0 and keyword_score > 0:
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

            result["score"] = final_score
            result["metadata"] = metadata
            ranked_results.append(result)

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

    def _build_vector_search_filter(self, agent_input: AgentInput) -> Dict[str, Any]:
        search_filter: Dict[str, Any] = {"user_id": agent_input.user_id}

        if agent_input.metadata:
            metadata_filter = agent_input.metadata.get("vector_search_filter")
            if isinstance(metadata_filter, dict):
                for key, value in metadata_filter.items():
                    if value is None or key == "user_id":
                        continue
                    search_filter[key] = value

        return search_filter

    async def _retrieve_documents(self, queries: List[str], agent_input: AgentInput) -> List[Dict[str, Any]]:
        if self.vector_store is None:
            self.logger.warning("向量数据库未初始化，将跳过向量检索")

        self.logger.info(
            "[RETRIEVAL] knowledge_base_query_start: "
            f"query_count={len(queries)}, top_k={self.top_k}, "
            f"similarity_threshold={self.similarity_threshold}, hybrid_enabled={getattr(self, 'enable_hybrid_retrieval', True)}"
        )

        aggregated_results: Dict[str, Dict[str, Any]] = {}
        search_filter = self._build_vector_search_filter(agent_input)
        corpus = self._load_filtered_corpus(search_filter)
        using_database_fallback_corpus = False
        if not (corpus.get("ids") or corpus.get("documents")):
            corpus = self._load_database_fallback_corpus(search_filter)
            if corpus.get("ids"):
                using_database_fallback_corpus = True
                self.logger.info(
                    "[RETRIEVAL] database_text_fallback_loaded: "
                    f"count={len(corpus.get('ids', []))}, "
                    f"sample={self._summarize_payload((corpus.get('metadatas') or [{}])[0])}"
                )
        exact_phrases = self._extract_exact_phrases(agent_input.content)

        exact_phrase_results = self._search_exact_phrases(exact_phrases, corpus)
        if exact_phrase_results:
            self.logger.info(
                "[RETRIEVAL] exact_phrase_search_done: "
                f"count={len(exact_phrase_results)}, sample={self._summarize_payload(exact_phrase_results[0])}"
            )
            for result in exact_phrase_results:
                matched_queries = result.get("metadata", {}).get("matched_queries", [])
                self._merge_retrieval_result(
                    aggregated_results,
                    result,
                    matched_query=matched_queries[0] if matched_queries else None,
                    match_source="exact_phrase",
                )

        keyword_index = self._build_keyword_index(corpus)
        if keyword_index:
            for query_index, query in enumerate(queries, start=1):
                keyword_results = self._search_keyword_matches(query, keyword_index)
                if keyword_results:
                    self.logger.info(
                        "[RETRIEVAL] keyword_search_done: "
                        f"query_index={query_index}/{len(queries)}, count={len(keyword_results)}, "
                        f"sample={self._summarize_payload(keyword_results[0])}"
                    )
                for result in keyword_results:
                    self._merge_retrieval_result(
                        aggregated_results,
                        result,
                        matched_query=query,
                        match_source="text" if using_database_fallback_corpus else "keyword",
                    )

        if getattr(self, "vector_enabled", False):
            rerank_limit = int(getattr(self, "rerank_top_k", self.top_k))
            retrieval_limit = max(int(self.top_k), rerank_limit, 10)
            per_query_top_k = max(retrieval_limit, min(retrieval_limit * 2, retrieval_limit + len(queries) + 2))
            for query_index, query in enumerate(queries, start=1):
                try:
                    self.logger.info(
                        "[RETRIEVAL] vector_search_request: "
                        f"query_index={query_index}/{len(queries)}, "
                        f"query_preview='{self._safe_preview(query, 80)}'"
                    )

                    search_results = self.vector_store.search(
                        query=query,
                        n_results=per_query_top_k,
                        where=search_filter,
                    )

                    if isinstance(search_results, dict):
                        raw_ids = search_results.get("ids", [])
                        flat_ids = self._flatten_collection_values(raw_ids)
                        self.logger.info(
                            "[RETRIEVAL] vector_search_response: "
                            f"query_index={query_index}, keys={list(search_results.keys())}, "
                            f"first_ids_count={len(flat_ids)}"
                        )
                    else:
                        self.logger.warning(
                            "[RETRIEVAL] vector_search_response_unexpected: "
                            f"query_index={query_index}, type={type(search_results).__name__}"
                        )

                    if not search_results or "ids" not in search_results:
                        continue

                    ids = self._flatten_collection_values(search_results.get("ids", []))
                    documents = self._flatten_collection_values(search_results.get("documents", []))
                    distances = self._flatten_collection_values(search_results.get("distances", []))
                    metadatas = self._flatten_collection_values(search_results.get("metadatas", []))

                    for i, doc_id in enumerate(ids):
                        distance = distances[i] if i < len(distances) else 1.0
                        similarity_score = self._convert_distance_to_similarity(distance)

                        self.logger.info(
                            f"文档 {doc_id}: 距离={distance:.6f}, 相似度={similarity_score:.6f}, 阈值={self.similarity_threshold}"
                        )

                        if similarity_score < self.similarity_threshold:
                            self.logger.info(
                                f"相似度未达阈值: {doc_id} (score={similarity_score:.4f} < threshold={self.similarity_threshold})"
                            )
                            continue

                        metadata = dict(metadatas[i] if i < len(metadatas) else {})
                        metadata["vector_score"] = max(float(metadata.get("vector_score", 0.0) or 0.0), similarity_score)
                        result = {
                            "id": doc_id,
                            "content": documents[i] if i < len(documents) else "",
                            "score": similarity_score,
                            "metadata": metadata,
                        }

                        if not result["content"]:
                            self.logger.warning(f"文档 {doc_id} 内容为空")

                        self._merge_retrieval_result(
                            aggregated_results,
                            result,
                            matched_query=query,
                            match_source="vector",
                        )

                except Exception as e:
                    self.logger.error(f"查询 '{query}' 向量检索失败: {str(e)}")
                    continue
        else:
            self.logger.info("[RETRIEVAL] vector_search_skipped: vector search is disabled")

        all_results = self._rank_aggregated_results(aggregated_results)
        rerank_limit = int(getattr(self, "rerank_top_k", self.top_k))
        final_limit = max(int(self.top_k), rerank_limit, 10)
        final_results = all_results[: final_limit * max(1, len(queries))]

        self.logger.info(f"_retrieve_documents 完成: 原始{len(all_results)}条 -> 返回{len(final_results)}条")
        self.logger.info(
            "[RETRIEVAL] knowledge_base_query_done: "
            f"deduplicated_total={len(all_results)}, returned={len(final_results)}, "
            f"sample={self._summarize_payload(final_results[0] if final_results else {})}"
        )

        return final_results

    async def _save_retrieval_results(self, execution_id: str, results: List[Dict[str, Any]]):
        try:
            self.logger.info(f"开始保存 {len(results)} 条检索结果")
            for rank, result in enumerate(results, start=1):
                retrieval_result = RetrievalResultCreate(
                    execution_id=execution_id, content=result.get("content", ""),
                    source_type=result.get("metadata", {}).get("source_type", "document"),
                    source_id=result.get("id"), source_name=result.get("metadata", {}).get("source", "Unknown"),
                    relevance_score=result.get("score"), rank=rank, metadata=result.get("metadata")
                )
                self.retrieval_result_repo.create_result(retrieval_result)
            self.logger.info(f"成功保存 {len(results)} 条检索结果到数据库")
        except Exception as e:
            self.logger.error(f"保存检索结果失败: {e}", exc_info=True)

    def _convert_distance_to_similarity(self, distance: float) -> float:
        if self.distance_metric == "cosine":
            # Cosine距离: 范围[0, 2]，0表示完全相同，2表示完全相反
            # 转换为相似度: similarity = 1 - (distance / 2)
            # 简化: similarity = 1 - distance (因为通常distance已经在[0,1]范围内)
            similarity = max(0.0, min(1.0, 1.0 - distance))
        elif self.distance_metric == "l2":
            # L2距离（欧氏距离）: 范围[0, +∞)，0表示完全相同
            # 转换为相似度: similarity = 1 / (1 + distance)
            similarity = 1.0 / (1.0 + distance)
        elif self.distance_metric == "ip":
            # Inner Product（内积）: 值越大越相似
            # 如果向量已归一化，内积等于余弦相似度，范围[-1, 1]
            # 转换为[0, 1]: similarity = (distance + 1) / 2
            similarity = max(0.0, min(1.0, (distance + 1.0) / 2.0))
        else:
            # 默认使用cosine转换
            similarity = max(0.0, min(1.0, 1.0 - distance))

        return similarity

    async def _generate_retrieval_summary(
        self,
        results: List[Dict[str, Any]],
        user_question: str
    ) -> Optional[Dict[str, Any]]:
        if not self.enable_summary or not results:
            return None

        try:
            # 格式化检索结果
            formatted_results = []
            for i, result in enumerate(results, start=1):
                formatted_result = self._get_prompt("retrieval_result_format")
                if formatted_result:
                    formatted_result = formatted_result.format(
                        index=i,
                        source_type=result.get("metadata", {}).get("source_type", "document"),
                        relevance_score=f"{result.get('score', 0):.2f}",
                        content=result.get("content", "")[:500]  # 限制长度
                    )
                else:
                    formatted_result = f"[{i}] {result.get('content', '')[:500]}"
                formatted_results.append(formatted_result)

            retrieval_results_text = "\n".join(formatted_results)

            # 获取摘要提示词
            summary_prompt = self._get_prompt("retrieval_summary_prompt")
            if not summary_prompt:
                self.logger.warning("retrieval_summary_prompt not found")
                return None

            # 格式化提示词
            prompt = summary_prompt.format(
                question=user_question,
                retrieval_results=retrieval_results_text
            )

            # 调用LLM生成摘要
            from backend.utils.llm_client import get_llm_client
            llm_client = get_llm_client()

            response = await llm_client.chat_completion(
                messages=[{"role": "user", "content": prompt}],
                temperature=0.3,
                max_tokens=800
            )

            # 解析JSON响应
            import json
            try:
                summary_result = json.loads(response)
                self.logger.info("成功生成检索摘要")
                return summary_result
            except json.JSONDecodeError:
                self.logger.warning("摘要JSON解析失败，返回原始响应")
                return {
                    "summary": response,
                    "key_points": [],
                    "sources": []
                }

        except Exception as e:
            self.logger.error(f"生成检索摘要失败: {e}", exc_info=True)
            return None
