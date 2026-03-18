# -*- coding: utf-8 -*-


from __future__ import annotations
"""
检索重排模块，负责对召回结果做二次排序与融合评分。
"""


from dataclasses import dataclass
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
        semantic_reranker: Optional[Callable[[str, List[Dict[str, Any]]], List[float]]] = None,
        semantic_weight: float = 0.35,
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

            final_results = sorted_results[:top_k] if top_k else sorted_results
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
            semantic_scores = self.semantic_reranker(query, results)
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
        seen_contents: List[str] = []

        for result in results:
            content = result.get("content", "")
            if not content:
                self.logger.warning(f"检索结果 {result.get('id', 'unknown')} 的内容为空，保留结果")
                deduped.append(result)
                continue

            normalized_content = self._normalize_text(content)
            is_duplicate = False
            for seen_content in seen_contents:
                similarity = self._calculate_text_similarity(normalized_content, seen_content)
                if similarity >= self.dedup_threshold:
                    is_duplicate = True
                    self.logger.debug(f"检测到重复内容，相似度: {similarity:.2f}")
                    break

            if not is_duplicate:
                deduped.append(result)
                seen_contents.append(normalized_content)

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
            feature_score = (
                self.similarity_weight * similarity_score
                + self.recency_weight * recency_score
                + self.authority_weight * authority_score
                + self.query_relevance_weight * query_relevance_score
            )
            semantic_score = semantic_scores[index] if semantic_scores is not None else None

            rerank_score = feature_score
            if semantic_score is not None:
                rerank_score = (1.0 - self.semantic_weight) * feature_score + self.semantic_weight * semantic_score

            result["rerank_score"] = rerank_score
            result["score_breakdown"] = {
                "similarity": similarity_score,
                "recency": recency_score,
                "authority": authority_score,
                "query_relevance": query_relevance_score,
                "feature_score": feature_score,
                "semantic": semantic_score,
            }
            scored_results.append(result)

        return scored_results

    def _get_query_relevance_score(self, query: Optional[str], result: Dict[str, Any]) -> float:
        """
        评估结果与查询之间的相关性。
        
        该方法会综合 token 重叠、精确短语命中、来源字段命中、
        结构化字段命中以及多查询命中次数进行打分。
        """
        if not query:
            return 0.5

        metadata = result.get("metadata", {}) or {}
        content = result.get("content", "") or ""
        source_text = " ".join(
            str(metadata.get(field, "") or "")
            for field in (
                "source",
                "file_name",
                "filename",
                "title",
                "original_filename",
                "section_title",
                "section_path",
                "sheet_name",
                "structured_terms",
                "symbol_name",
                "node_name",
                "leaf_value",
                "column_headers",
            )
        )
        search_text = "\n".join(part for part in [content, source_text] if part)
        if not search_text:
            return 0.0

        query_tokens = self._tokenize_text(query)
        content_tokens = self._tokenize_text(search_text)
        token_overlap = len(query_tokens & content_tokens) / len(query_tokens) if query_tokens else 0.0

        compact_query = self._normalize_compact_text(query)
        compact_search_text = self._normalize_compact_text(search_text)
        exact_phrases = self._extract_exact_phrases(query)
        exact_phrase_match = any(
            self._normalize_compact_text(phrase) in compact_search_text for phrase in exact_phrases
        )

        source_match = 0.0
        compact_source = self._normalize_compact_text(source_text)
        if compact_query and compact_query in compact_source:
            source_match = 1.0
        elif any(self._normalize_compact_text(phrase) in compact_source for phrase in exact_phrases):
            source_match = 0.8

        structured_match = 0.0
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
            )
        )
        compact_structured = self._normalize_compact_text(structured_text)
        if compact_query and compact_query in compact_structured:
            structured_match = 1.0
        elif any(self._normalize_compact_text(phrase) in compact_structured for phrase in exact_phrases):
            structured_match = 0.85

        query_hit_count = metadata.get("query_hit_count", 0) or 0
        multi_query_bonus = min(1.0, query_hit_count / 2) if query_hit_count else 0.0

        score = (
            token_overlap * 0.52
            + (1.0 if exact_phrase_match else 0.0) * 0.25
            + source_match * 0.05
            + structured_match * 0.08
            + multi_query_bonus * 0.1
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
        return metadata.get("recency_score", 0.5)

    def _get_authority_score(self, metadata: Dict[str, Any]) -> float:
        """
        根据来源类型估算结果的权威性分数。
        """
        source_type = metadata.get("source_type", "")
        authority_map = {
            "official_doc": 1.0,
            "policy": 0.9,
            "report": 0.8,
            "article": 0.6,
            "comment": 0.4,
            "unknown": 0.5,
        }
        return authority_map.get(source_type, 0.5)

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
