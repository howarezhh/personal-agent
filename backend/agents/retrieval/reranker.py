# -*- coding: utf-8 -*-


from __future__ import annotations
"""
检索重排模块，负责对召回结果做二次排序与融合评分。
"""


from dataclasses import dataclass
from datetime import datetime, timezone
import re
import unicodedata
from typing import Any, Callable, Dict, List, Optional

from backend.utils.logger import get_logger


@dataclass
class RetrievalItem:
    """
    重排阶段使用的标准检索结果对象。
    
    字段说明：
    - `id`：结果唯一标识。
    - `content`：结果正文内容。
    - `score`：召回阶段给出的基础分。
    - `metadata`：结果附带的补充信息。
    """
    # `id`：检索结果唯一标识。
    id: str
    # `content`：检索结果正文内容。
    content: str
    # `score`：召回阶段给出的基础分数。
    score: float
    # `metadata`：附带的来源信息和打分辅助字段。
    metadata: Optional[Dict[str, Any]] = None


class Reranker:
    """
    检索结果重排器。
    
    该组件负责把多路召回结果进一步整理为更适合回答生成的顺序，
    主要包含去重、启发式评分、可选语义重排和最终排序。
    """
    def __init__(
        self,
        enable_rerank: bool = True,
        similarity_weight: float = 0.6,
        recency_weight: float = 0.15,
        authority_weight: float = 0.1,
        dedup_threshold: float = 0.9,
        query_relevance_weight: float = 0.15,
        semantic_reranker: Optional[Callable[[str, List[str]], List[float]]] = None,
        semantic_weight: float = 0.35,
        diversity_weight: float = 0.05,
        min_query_relevance_score: float = 0.28,
        min_semantic_rerank_score: float = 0.55,
        semantic_agreement_bonus: float = 0.08,
        semantic_disagreement_penalty: float = 0.12,
    ):
        """
        初始化重排器配置、权重和可选语义重排器。
        
        各权重共同决定最终 `rerank_score` 的构成比例，
        其中 `semantic_reranker` 是可选的外部语义重排函数。
        """
        self.logger = get_logger("reranker")
        self.enable_rerank = enable_rerank
        self.similarity_weight = similarity_weight
        self.recency_weight = recency_weight
        self.authority_weight = authority_weight
        self.dedup_threshold = dedup_threshold
        self.query_relevance_weight = query_relevance_weight
        self.semantic_reranker = semantic_reranker
        self.semantic_weight = max(0.0, min(float(semantic_weight), 1.0))
        # `diversity_weight`：来源多样性辅助权重，用于轻微鼓励跨来源结果保留。
        self.diversity_weight = max(0.0, min(float(diversity_weight), 0.2))
        # `min_query_relevance_score`：词法/结构化相关性的最低强信号阈值。
        self.min_query_relevance_score = max(0.0, min(float(min_query_relevance_score), 1.0))
        # `min_semantic_rerank_score`：cross-encoder 语义分的最低强信号阈值。
        self.min_semantic_rerank_score = max(0.0, min(float(min_semantic_rerank_score), 1.0))
        # `semantic_agreement_bonus`：语义与词法一致时的额外奖励。
        self.semantic_agreement_bonus = max(0.0, min(float(semantic_agreement_bonus), 0.2))
        # `semantic_disagreement_penalty`：语义与词法同时偏弱时的惩罚。
        self.semantic_disagreement_penalty = max(0.0, min(float(semantic_disagreement_penalty), 0.3))
        # `max_results_per_document`：最终结果中同一文档最多保留的 chunk 数。
        # 这里直接内聚为重排规则，避免单一长文档凭借 chunk 数量挤占整个 top_k。
        self.max_results_per_document = 2

    def rerank(
        self,
        results: List[Dict[str, Any]],
        query: Optional[str] = None,
        top_k: Optional[int] = None,
    ) -> List[Dict[str, Any]]:
        """
        对候选结果执行去重、评分和排序。
        
        处理顺序为：
        1. 按原始分数做初步排序。
        2. 去除内容高度重复的结果。
        3. 计算启发式与可选语义分数。
        4. 生成最终重排后的结果列表。
        """
        if not self.enable_rerank or not results:
            return results[:top_k] if top_k else results

        try:
            ordered_results = sorted(results, key=lambda item: item.get("score", 0.0), reverse=True)
            deduped_results = self._deduplicate(ordered_results)
            self.logger.info(f"Deduplicated: {len(results)} -> {len(deduped_results)} results")

            semantic_scores = self._get_semantic_scores(query, deduped_results)
            scored_results = self._calculate_scores(deduped_results, query, semantic_scores)
            sorted_results = sorted(
                scored_results,
                key=lambda item: item.get("rerank_score", item.get("score", 0.0)),
                reverse=True,
            )
            diversified_results = self._diversify_results(sorted_results, limit=top_k)

            final_results = diversified_results[:top_k] if top_k else diversified_results
            self.logger.info(f"Reranked {len(results)} results, returning top {len(final_results)}")
            return final_results

        except Exception as exc:
            self.logger.error(f"Reranking failed: {exc}")
            return results[:top_k] if top_k else results

    def _get_semantic_scores(
        self,
        query: Optional[str],
        results: List[Dict[str, Any]],
    ) -> Optional[List[float]]:
        """
        调用外部语义重排器获取语义分数。
        
        如果外部重排器不存在、执行失败或返回格式不合法，
        会自动回退到内部启发式重排逻辑。
        """
        if not query or not results or self.semantic_reranker is None:
            return None

        try:
            passages = [str(result.get("content", "") or "") for result in results]
            semantic_scores = self.semantic_reranker(query, passages)
        except Exception as exc:
            self.logger.warning(f"Semantic reranker failed, fallback to heuristic reranker: {exc}")
            return None

        if not isinstance(semantic_scores, list) or len(semantic_scores) != len(results):
            self.logger.warning("Semantic reranker returned invalid scores, fallback to heuristic reranker")
            return None

        return [max(0.0, min(float(score), 1.0)) for score in semantic_scores]

    def _deduplicate(self, results: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """
        按内容相似度对结果去重。
        
        这里采用标准化文本相似度做近似去重，
        避免同一段内容在多路召回后重复出现。
        """
        if not results:
            return []

        deduped: List[Dict[str, Any]] = []
        seen_results: List[Dict[str, Any]] = []

        for result in results:
            content = result.get("content", "")
            if not content:
                self.logger.warning(f"检索结果 {result.get('id', 'unknown')} 的内容为空，保留结果")
                deduped.append(result)
                continue

            normalized_content = self._normalize_text(content)
            is_duplicate = False
            for seen_result in seen_results:
                seen_content = self._normalize_text(seen_result.get("content", ""))
                similarity = self._calculate_text_similarity(normalized_content, seen_content)
                if self._is_duplicate_result(result, seen_result, similarity):
                    is_duplicate = True
                    self.logger.debug(f"检测到重复内容，相似度: {similarity:.2f}")
                    break

            if not is_duplicate:
                deduped.append(result)
                seen_results.append(result)

        return deduped

    def _calculate_text_similarity(self, text1: str, text2: str) -> float:
        """
        计算两段文本的相似度。
        
        该方法用于去重阶段的重复内容识别，
        返回值越接近 1，表示两段文本越相似。
        """
        tokens1 = self._tokenize_text(text1)
        tokens2 = self._tokenize_text(text2)
        if not tokens1 or not tokens2:
            return 0.0

        intersection = len(tokens1 & tokens2)
        union = len(tokens1 | tokens2)
        jaccard_similarity = intersection / union if union else 0.0

        len1, len2 = len(text1), len(text2)
        length_similarity = min(len1, len2) / max(len1, len2) if max(len1, len2) else 0.0
        return jaccard_similarity * 0.75 + length_similarity * 0.25

    def _calculate_scores(
        self,
        results: List[Dict[str, Any]],
        query: Optional[str] = None,
        semantic_scores: Optional[List[float]] = None,
    ) -> List[Dict[str, Any]]:
        """
        计算并写回每条结果的综合重排分数。
        
        综合分通常会融合原始召回分、查询相关性、时效性、权威性
        以及可选的语义分数，最终写入 `rerank_score`。
        """
        scored_results: List[Dict[str, Any]] = []

        for index, result in enumerate(results):
            similarity_score = float(result.get("score", 0.5) or 0.5)
            recency_score = self._get_recency_score(result.get("metadata", {}))
            authority_score = self._get_authority_score(result.get("metadata", {}))
            query_relevance_score = self._get_query_relevance_score(query, result)
            metadata = dict(result.get("metadata", {}) or {})
            metadata.setdefault("pre_rerank_score", float(result.get("score", 0.0) or 0.0))
            vector_score = float(metadata.get("vector_score", 0.0) or 0.0)
            keyword_score = float(metadata.get("keyword_score", 0.0) or 0.0)
            exact_phrase_score = float(metadata.get("exact_phrase_score", 0.0) or 0.0)
            query_hit_count = int(metadata.get("query_hit_count", 0) or 0)
            multi_query_bonus = min(1.0, query_hit_count / 3.0) if query_hit_count > 0 else 0.0
            retrieval_signal_score = min(
                1.0,
                vector_score * 0.45 + keyword_score * 0.2 + exact_phrase_score * 0.35,
            )
            feature_score = (
                self.similarity_weight * max(similarity_score, retrieval_signal_score)
                + self.recency_weight * recency_score
                + self.authority_weight * authority_score
                + self.query_relevance_weight * min(1.0, query_relevance_score * 0.8 + multi_query_bonus * 0.2)
            )
            diversity_score = self._get_diversity_score(metadata)
            semantic_score = semantic_scores[index] if semantic_scores is not None else None
            agreement_bonus = 0.0
            disagreement_penalty = 0.0

            if semantic_score is not None:
                lexical_or_structured_strong = query_relevance_score >= self.min_query_relevance_score
                semantic_strong = semantic_score >= self.min_semantic_rerank_score
                has_exact_support = exact_phrase_score >= 0.9 or bool(metadata.get("exact_phrase_match"))
                if semantic_strong and (lexical_or_structured_strong or has_exact_support):
                    agreement_bonus = self.semantic_agreement_bonus
                elif (
                    semantic_score < self.min_semantic_rerank_score * 0.6
                    and query_relevance_score < self.min_query_relevance_score * 0.7
                    and not has_exact_support
                ):
                    disagreement_penalty = self.semantic_disagreement_penalty

            rerank_score = feature_score + self.diversity_weight * diversity_score
            if semantic_score is not None:
                rerank_score = (
                    (1.0 - self.semantic_weight) * (feature_score + self.diversity_weight * diversity_score)
                    + self.semantic_weight * semantic_score
                )
            rerank_score = max(0.0, min(1.0, rerank_score + agreement_bonus - disagreement_penalty))

            result["rerank_score"] = rerank_score
            result["score"] = rerank_score
            result["metadata"] = metadata
            result["score_breakdown"] = {
                "similarity": similarity_score,
                "recency": recency_score,
                "authority": authority_score,
                "query_relevance": query_relevance_score,
                "retrieval_signal": retrieval_signal_score,
                "multi_query_bonus": multi_query_bonus,
                "diversity": diversity_score,
                "feature_score": feature_score,
                "semantic": semantic_score,
                "semantic_agreement_bonus": agreement_bonus,
                "semantic_disagreement_penalty": disagreement_penalty,
                "final_rerank_score": rerank_score,
            }
            scored_results.append(result)

        return scored_results

    def _get_query_relevance_score(self, query: Optional[str], result: Dict[str, Any]) -> float:
        """
        评估结果与查询之间的相关性。
        
        评分原则调整为“正文优先、结构化字段辅助、文件名弱提示”：
        - 主分只看正文与结构化内容，避免长文档文件名长期霸榜；
        - 文件名/标题只作为弱辅助信号，不再主导排序；
        - 精确短语若已在 exact phrase 召回通道命中，则不再重复放大。
        """
        if not query:
            return 0.5

        metadata = result.get("metadata", {}) or {}
        content = str(result.get("content", "") or "")
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
                "slide_title",
                "source_region",
            )
        )
        reference_text = " ".join(
            str(metadata.get(field, "") or "")
            for field in (
                "title",
                "section_title",
                "section_path",
            )
        )
        if not any([content, structured_text, reference_text]):
            return 0.0

        query_tokens = self._tokenize_text(query)
        content_tokens = self._tokenize_text(content)
        structured_tokens = self._tokenize_text(structured_text)
        reference_tokens = self._tokenize_text(reference_text)

        content_overlap = len(query_tokens & content_tokens) / len(query_tokens) if query_tokens else 0.0
        structured_overlap = len(query_tokens & structured_tokens) / len(query_tokens) if query_tokens else 0.0
        reference_overlap = len(query_tokens & reference_tokens) / len(query_tokens) if query_tokens else 0.0

        compact_query = self._normalize_compact_text(query)
        compact_content = self._normalize_compact_text(content)
        compact_structured = self._normalize_compact_text(structured_text)
        compact_reference = self._normalize_compact_text(reference_text)
        exact_phrases = self._extract_exact_phrases(query)
        exact_phrase_match = any(
            self._normalize_compact_text(phrase) in compact_content
            or self._normalize_compact_text(phrase) in compact_structured
            for phrase in exact_phrases
        )

        retrieval_ranks = dict(metadata.get("retrieval_ranks") or {})
        exact_phrase_lane_hit = any(str(lane_key).startswith("exact_phrase:") for lane_key in retrieval_ranks.keys())
        if exact_phrase_lane_hit:
            exact_phrase_match = False

        reference_match = 0.0
        if compact_query and compact_query in compact_reference:
            reference_match = 1.0
        elif any(self._normalize_compact_text(phrase) in compact_reference for phrase in exact_phrases):
            reference_match = 0.6

        score = (
            content_overlap * 0.72
            + structured_overlap * 0.14
            + reference_overlap * 0.04
            + (1.0 if exact_phrase_match else 0.0) * 0.08
            + reference_match * 0.02
        )
        return min(1.0, score)

    def _tokenize_text(self, text: str) -> set[str]:
        """
        对文本执行标准化分词。
        
        英文与数字以连续串切分，中文连续串按双字 gram 方式切分，
        用于计算查询和结果内容之间的交集重叠度。
        """
        normalized = self._normalize_text(text)
        latin_tokens = set(re.findall(r"[a-z0-9]+", normalized))
        cjk_segments = re.findall(r"[\u4e00-\u9fff]+", normalized)
        cjk_tokens = set()
        for segment in cjk_segments:
            if len(segment) == 1:
                cjk_tokens.add(segment)
                continue
            cjk_tokens.update(segment[index : index + 2] for index in range(len(segment) - 1))
        return latin_tokens | cjk_tokens

    def _extract_exact_phrases(self, query: str) -> List[str]:
        """
        提取查询中的精确短语。
        
        主要识别引号、中文引号和书名号中的内容，
        用于提升对用户明确指定短语的匹配能力。
        """
        if not query:
            return []

        phrases: List[str] = []
        patterns = [r'["“](.{2,}?)[”"]', r'[《「](.{2,}?)[》」]']
        for pattern in patterns:
            for match in re.findall(pattern, query):
                candidate = match.strip()
                if candidate and candidate not in phrases:
                    phrases.append(candidate)
        return phrases

    def _normalize_text(self, text: str) -> str:
        """
        对文本做基础标准化。
        
        统一全角半角、大小写和多余空白，
        便于后续相似度计算与 token 对齐。
        """
        normalized = unicodedata.normalize("NFKC", str(text or "")).lower()
        normalized = re.sub(r"\s+", " ", normalized)
        return normalized.strip()

    def _normalize_compact_text(self, text: str) -> str:
        """
        对文本做去空白标准化。
        
        适合用于判断“完整短语是否连续出现”这类场景。
        """
        return re.sub(r"\s+", "", self._normalize_text(text))

    def _get_recency_score(self, metadata: Dict[str, Any]) -> float:
        """
        读取或估算结果的时效性分数。
        """
        raw_score = metadata.get("recency_score")
        if raw_score is not None:
            try:
                return max(0.0, min(float(raw_score), 1.0))
            except (TypeError, ValueError):
                pass

        timestamp_fields = (
            metadata.get("updated_at"),
            metadata.get("modified"),
            metadata.get("created_at"),
            metadata.get("created"),
        )
        for value in timestamp_fields:
            normalized_value = str(value or "").strip()
            if not normalized_value:
                continue
            try:
                parsed_time = datetime.fromisoformat(normalized_value.replace("Z", "+00:00"))
            except ValueError:
                continue
            if parsed_time.tzinfo is None:
                parsed_time = parsed_time.replace(tzinfo=timezone.utc)
            age_days = max(
                0.0,
                (datetime.now(timezone.utc) - parsed_time.astimezone(timezone.utc)).total_seconds() / 86400.0,
            )
            if age_days <= 7:
                return 1.0
            if age_days <= 30:
                return 0.9
            if age_days <= 180:
                return 0.75
            if age_days <= 365:
                return 0.6
            return 0.45
        return 0.5

    def _get_authority_score(self, metadata: Dict[str, Any]) -> float:
        """
        根据来源类型估算结果的权威性分数。
        """
        source_type = str(metadata.get("source_type") or self._infer_source_type(metadata) or "")
        if metadata.get("source_region") in {"header", "footer"}:
            return 0.2
        authority_map = {
            "official_doc": 1.0,
            "policy": 0.9,
            "report": 0.8,
            "document": 0.75,
            "spreadsheet": 0.78,
            "presentation": 0.68,
            "structured_data": 0.82,
            "code": 0.85,
            "article": 0.6,
            "comment": 0.4,
            "unknown": 0.5,
        }
        return authority_map.get(source_type, 0.5)

    def _get_diversity_score(self, metadata: Dict[str, Any]) -> float:
        """根据来源多样性信号计算一个轻量辅助分。"""
        match_sources = list(metadata.get("match_sources") or [])
        source_bonus = min(1.0, len(match_sources) / 3) if match_sources else 0.0
        return min(1.0, source_bonus)

    def _diversify_results(self, results: List[Dict[str, Any]], *, limit: Optional[int]) -> List[Dict[str, Any]]:
        """对最终排序结果做文档级多样性整理。

        这里不再让同一长文档连续占满整个结果集，而是按三轮策略收敛：
        1. 先尽量保留每个文档的第一条；
        2. 再补充同一文档的第二条高质量 chunk；
        3. 若仍未达到目标数量，再按原排序补齐。
        """
        if not results:
            return []

        target_size = min(limit, len(results)) if limit else len(results)
        selected: List[Dict[str, Any]] = []
        selected_ids: set[str] = set()
        document_counts: Dict[str, int] = {}

        def _append_with_limit(max_per_document: Optional[int]) -> None:
            for item in results:
                item_id = str(item.get("id") or "")
                if item_id and item_id in selected_ids:
                    continue
                document_key = self._resolve_document_key(item)
                current_count = document_counts.get(document_key, 0)
                if max_per_document is not None and current_count >= max_per_document:
                    continue
                selected.append(item)
                if item_id:
                    selected_ids.add(item_id)
                document_counts[document_key] = current_count + 1
                if len(selected) >= target_size:
                    return

        _append_with_limit(1)
        if len(selected) < target_size:
            _append_with_limit(self.max_results_per_document)
        if len(selected) < target_size:
            _append_with_limit(None)
        return selected

    @staticmethod
    def _resolve_document_key(result: Dict[str, Any]) -> str:
        """为多样性控制提取稳定的文档标识。"""
        metadata = dict(result.get("metadata") or {})
        for field in ("document_id", "file_id", "source", "file_name", "original_filename"):
            value = metadata.get(field)
            if value:
                return str(value)
        return str(result.get("id") or "unknown-document")

    @staticmethod
    def _infer_source_type(metadata: Dict[str, Any]) -> str:
        """根据文件类型推断来源类型，避免权威性长期落到默认值。"""
        file_type = str(metadata.get("file_type") or "").lower()
        mapping = {
            "pdf": "document",
            "docx": "document",
            "md": "document",
            "markdown": "document",
            "txt": "document",
            "pptx": "presentation",
            "xlsx": "spreadsheet",
            "xls": "spreadsheet",
            "csv": "spreadsheet",
            "tsv": "spreadsheet",
            "json": "structured_data",
            "xml": "structured_data",
            "yaml": "structured_data",
            "yml": "structured_data",
            "code": "code",
            "html": "article",
        }
        return mapping.get(file_type, "unknown")

    def _is_duplicate_result(
        self,
        current_result: Dict[str, Any],
        seen_result: Dict[str, Any],
        similarity: float,
    ) -> bool:
        """判断两条结果是否应视为重复。

        规则：
        - 同一文档 / 同一 chunk 直接视为重复；
        - 同一文件或同一来源下，相似度达到阈值即去重；
        - 不同来源的高相似内容默认保留，以避免误杀来源多样性。
        """
        current_metadata = dict(current_result.get("metadata") or {})
        seen_metadata = dict(seen_result.get("metadata") or {})

        current_doc_id = str(current_result.get("id") or current_metadata.get("document_id") or "")
        seen_doc_id = str(seen_result.get("id") or seen_metadata.get("document_id") or "")
        if current_doc_id and seen_doc_id and current_doc_id == seen_doc_id:
            return True

        current_file_id = current_metadata.get("file_id")
        seen_file_id = seen_metadata.get("file_id")
        current_chunk_index = current_metadata.get("chunk_index")
        seen_chunk_index = seen_metadata.get("chunk_index")
        same_file = current_file_id is not None and current_file_id == seen_file_id
        same_source = self._build_source_signature(current_metadata) == self._build_source_signature(seen_metadata)

        if same_file and current_chunk_index is not None and seen_chunk_index is not None:
            if int(current_chunk_index) == int(seen_chunk_index):
                return True
            if abs(int(current_chunk_index) - int(seen_chunk_index)) <= 1 and similarity >= self.dedup_threshold:
                return True

        if same_file or same_source:
            return similarity >= self.dedup_threshold

        # 中文说明：不同来源即便内容高度相似，也默认保留，避免误伤来源多样性。
        return False

    @staticmethod
    def _build_source_signature(metadata: Dict[str, Any]) -> str:
        """构建来源签名，用于在去重阶段判断是否同源。"""
        for field in ("source", "file_name", "filename", "original_filename", "title"):
            value = metadata.get(field)
            if value:
                return str(value)
        return ""

    def __repr__(self) -> str:
        """
        返回重排器的调试表示，便于日志和问题排查。
        """
        return (
            "Reranker("
            f"enabled={self.enable_rerank}, "
            f"weights=[sim:{self.similarity_weight}, rec:{self.recency_weight}, "
            f"auth:{self.authority_weight}, query:{self.query_relevance_weight}]"
            ")"
        )
