"""Retrieval result reranking utilities."""

from __future__ import annotations

from dataclasses import dataclass
import re
import unicodedata
from typing import Any, Dict, List, Optional

from backend.utils.logger import get_logger


@dataclass
class RetrievalItem:
    id: str
    content: str
    score: float
    metadata: Optional[Dict[str, Any]] = None


class Reranker:
    def __init__(
        self,
        enable_rerank: bool = True,
        similarity_weight: float = 0.6,
        recency_weight: float = 0.15,
        authority_weight: float = 0.1,
        dedup_threshold: float = 0.9,
        query_relevance_weight: float = 0.15,
    ):
        self.logger = get_logger("reranker")
        self.enable_rerank = enable_rerank
        self.similarity_weight = similarity_weight
        self.recency_weight = recency_weight
        self.authority_weight = authority_weight
        self.dedup_threshold = dedup_threshold
        self.query_relevance_weight = query_relevance_weight

    def rerank(
        self,
        results: List[Dict[str, Any]],
        query: Optional[str] = None,
        top_k: Optional[int] = None,
    ) -> List[Dict[str, Any]]:
        if not self.enable_rerank or not results:
            return results[:top_k] if top_k else results

        try:
            ordered_results = sorted(results, key=lambda item: item.get("score", 0.0), reverse=True)
            deduped_results = self._deduplicate(ordered_results)
            self.logger.info(f"Deduplicated: {len(results)} -> {len(deduped_results)} results")

            scored_results = self._calculate_scores(deduped_results, query)
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

    def _deduplicate(self, results: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
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
    ) -> List[Dict[str, Any]]:
        scored_results: List[Dict[str, Any]] = []

        for result in results:
            similarity_score = float(result.get("score", 0.5) or 0.5)
            recency_score = self._get_recency_score(result.get("metadata", {}))
            authority_score = self._get_authority_score(result.get("metadata", {}))
            query_relevance_score = self._get_query_relevance_score(query, result)

            rerank_score = (
                self.similarity_weight * similarity_score
                + self.recency_weight * recency_score
                + self.authority_weight * authority_score
                + self.query_relevance_weight * query_relevance_score
            )

            result["rerank_score"] = rerank_score
            result["score_breakdown"] = {
                "similarity": similarity_score,
                "recency": recency_score,
                "authority": authority_score,
                "query_relevance": query_relevance_score,
            }
            scored_results.append(result)

        return scored_results

    def _get_query_relevance_score(self, query: Optional[str], result: Dict[str, Any]) -> float:
        if not query:
            return 0.5

        metadata = result.get("metadata", {}) or {}
        content = result.get("content", "") or ""
        source_text = " ".join(
            str(metadata.get(field, "") or "")
            for field in ("source", "file_name", "filename", "title", "original_filename")
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

        query_hit_count = metadata.get("query_hit_count", 0) or 0
        multi_query_bonus = min(1.0, query_hit_count / 2) if query_hit_count else 0.0

        score = (
            token_overlap * 0.6
            + (1.0 if exact_phrase_match else 0.0) * 0.25
            + source_match * 0.05
            + multi_query_bonus * 0.1
        )
        return min(1.0, score)

    def _tokenize_text(self, text: str) -> set[str]:
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
        normalized = unicodedata.normalize("NFKC", str(text or "")).lower()
        normalized = re.sub(r"\s+", " ", normalized)
        return normalized.strip()

    def _normalize_compact_text(self, text: str) -> str:
        return re.sub(r"\s+", "", self._normalize_text(text))

    def _get_recency_score(self, metadata: Dict[str, Any]) -> float:
        return metadata.get("recency_score", 0.5)

    def _get_authority_score(self, metadata: Dict[str, Any]) -> float:
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
        return (
            "Reranker("
            f"enabled={self.enable_rerank}, "
            f"weights=[sim:{self.similarity_weight}, rec:{self.recency_weight}, "
            f"auth:{self.authority_weight}, query:{self.query_relevance_weight}]"
            ")"
        )
