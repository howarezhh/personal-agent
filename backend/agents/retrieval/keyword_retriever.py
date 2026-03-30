# -*- coding: utf-8 -*-

from __future__ import annotations

"""
关键词检索模块。

本模块提供一个轻量级的 BM25 风格关键词检索器，
主要用于在向量检索之外补充稀疏召回能力。
核心职责包括：

1. 对文档正文与来源元数据做统一分词。
2. 构建倒排索引与文档频次统计信息。
3. 基于 BM25 公式计算查询与文档的匹配分数。
4. 对精确短语命中和来源字段命中追加轻量加权。
"""

from collections import Counter, defaultdict
from dataclasses import dataclass
import math
import re
import unicodedata
from typing import Any, Dict, Iterable, List, Sequence


@dataclass(frozen=True)
class KeywordDocument:
    """关键词检索阶段使用的标准文档对象。

    这里保存的字段都是为了让搜索阶段避免重复预处理：
    - `doc_id`：文档唯一标识。
    - `content`：文档原始正文。
    - `metadata`：文档元数据副本。
    - `source_text`：从来源、标题、文件名等字段拼接出的辅助检索文本。
    - `token_freq`：分词后的词频统计。
    - `length`：词项总长度，用于 BM25 长度归一化。
    - `compact_text`：去空白后的正文，便于做精确短语匹配。
    - `compact_source_text`：去空白后的来源文本，便于补充来源级命中。
    """

    # `doc_id`：文档唯一 ID，用于最终结果回传。
    doc_id: str
    # `content`：文档正文内容。
    content: str
    # `metadata`：文档携带的元数据。
    metadata: Dict[str, Any]
    # `source_text`：由来源相关字段拼接得到的辅助检索文本。
    source_text: str
    # `token_freq`：当前文档的词频统计结果。
    token_freq: Counter[str]
    # `length`：词项总数，用于 BM25 的长度惩罚计算。
    length: int
    # `compact_text`：去除空白后的正文，用于精确短语判断。
    compact_text: str
    # `compact_source_text`：去除空白后的来源文本，用于来源命中增强。
    compact_source_text: str


class KeywordRetriever:
    """关键词检索器，负责构建索引并执行关键词召回。"""

    # `_EN_STOPWORDS`：英文停用词集合，用于过滤价值较低的英文词项。
    _EN_STOPWORDS = {
        "a", "an", "and", "are", "as", "at", "be", "by", "for", "from", "in", "is",
        "of", "on", "or", "that", "the", "this", "to", "was", "were", "with",
    }

    def __init__(self, k1: float = 1.5, b: float = 0.75):
        """初始化 BM25 相关参数。

        参数说明：
        - `k1`：控制词频饱和速度，数值越大，重复词影响越强。
        - `b`：控制文档长度归一化力度，数值越大，长文惩罚越明显。
        """
        # `self.k1`：BM25 的词频饱和参数。
        self.k1 = k1
        # `self.b`：BM25 的长度归一化参数。
        self.b = b

    def build_index(
        self,
        ids: Sequence[str],
        documents: Sequence[str],
        metadatas: Sequence[Dict[str, Any]],
    ) -> Dict[str, Any]:
        """根据文档 ID、正文和元数据构建可复用索引。

        返回值是一个纯字典结构，目的是让上层调用方可以缓存索引，
        而不是在每次搜索时重复执行分词和倒排构建。
        """
        # `indexed_documents`：保存完成预处理后的文档对象列表。
        indexed_documents: List[KeywordDocument] = []
        # `postings`：倒排索引，结构为 token -> [(doc_index, frequency)]。
        postings: Dict[str, List[tuple[int, int]]] = defaultdict(list)
        # `document_frequency`：记录每个 token 出现于多少篇文档。
        document_frequency: Counter[str] = Counter()

        for index, doc_id in enumerate(ids):
            # `content`：按索引读取的正文，缺失时安全回退为空字符串。
            content = str(documents[index] if index < len(documents) else "")
            # `metadata`：按索引读取的元数据，并复制为普通字典防止外部副作用。
            metadata = dict(metadatas[index] if index < len(metadatas) else {})
            # `source_text`：把标题、来源、文件名等字段拼成辅助文本。
            source_text = self._build_source_text(metadata)
            # `token_freq`：对正文与来源文本合并分词后做词频统计。
            token_freq = Counter(self._tokenize_text("\n".join(part for part in [content, source_text] if part)))
            # 没有任何有效词项的文档不进入索引，避免污染召回结果。
            if not token_freq:
                continue

            # `compact_text`：正文的紧凑版文本，用于精确短语包含判断。
            compact_text = self._normalize_compact_text(content)
            # `compact_source_text`：来源文本的紧凑版文本，用于来源字段增强。
            compact_source_text = self._normalize_compact_text(source_text)
            indexed_document = KeywordDocument(
                doc_id=doc_id,
                content=content,
                metadata=metadata,
                source_text=source_text,
                token_freq=token_freq,
                length=sum(token_freq.values()),
                compact_text=compact_text,
                compact_source_text=compact_source_text,
            )
            indexed_documents.append(indexed_document)

        # 第二阶段统一构建倒排索引，避免在首轮遍历中处理半成品文档。
        for doc_index, document in enumerate(indexed_documents):
            for token, frequency in document.token_freq.items():
                postings[token].append((doc_index, frequency))
            document_frequency.update(document.token_freq.keys())

        # `average_length`：所有索引文档的平均长度，用于 BM25 归一化。
        average_length = (
            sum(document.length for document in indexed_documents) / len(indexed_documents)
            if indexed_documents
            else 0.0
        )

        return {
            "documents": indexed_documents,
            "postings": dict(postings),
            "document_frequency": document_frequency,
            "document_count": len(indexed_documents),
            "average_length": average_length,
        }

    def search(self, index: Dict[str, Any], query: str, *, top_k: int = 10) -> List[Dict[str, Any]]:
        """在已构建索引中执行关键词搜索。

        处理流程分为三段：
        1. 用 BM25 为命中文档打基础分。
        2. 用精确短语和来源字段命中做轻量加权。
        3. 做归一化并整理成统一结果格式返回。
        """
        # `documents`：索引中的文档对象列表。
        documents: List[KeywordDocument] = index.get("documents", [])
        # `postings`：索引中的倒排表。
        postings: Dict[str, List[tuple[int, int]]] = index.get("postings", {})
        # `document_frequency`：词项文档频次统计。
        document_frequency: Counter[str] = index.get("document_frequency", Counter())
        # `document_count`：索引中的总文档数。
        document_count = index.get("document_count", 0)
        # `average_length`：平均文档长度，为避免除零，空值时回退到 1.0。
        average_length = index.get("average_length", 0.0) or 1.0

        if not documents or not query:
            return []

        # `query_tokens`：查询分词结果，是后续倒排查找的基础。
        query_tokens = self._tokenize_text(query)
        if not query_tokens:
            return []

        # `candidate_scores`：候选文档基础分，键是文档索引，值是累计得分。
        candidate_scores: Dict[int, float] = defaultdict(float)
        # `matched_terms`：记录每个文档命中的查询词，便于结果解释。
        matched_terms: Dict[int, set[str]] = defaultdict(set)

        # 第一阶段：基于倒排索引计算 BM25 分数。
        for token in query_tokens:
            posting_list = postings.get(token, [])
            if not posting_list:
                continue

            df = document_frequency.get(token, 0)
            if df <= 0:
                continue

            # `idf`：当前词项的逆文档频率，越稀有的词权重越高。
            idf = math.log(1.0 + ((document_count - df + 0.5) / (df + 0.5)))
            for doc_index, term_frequency in posting_list:
                document = documents[doc_index]
                denominator = term_frequency + self.k1 * (1 - self.b + self.b * (document.length / average_length))
                score = idf * ((term_frequency * (self.k1 + 1)) / denominator)
                candidate_scores[doc_index] += score
                matched_terms[doc_index].add(token)

        # 第二阶段：对完整短语命中和来源字段命中追加增益分。
        exact_phrases = self._extract_exact_phrases(query)
        compact_query = self._normalize_compact_text(query)
        for doc_index, score in list(candidate_scores.items()):
            document = documents[doc_index]
            phrase_boost = 0.0
            if compact_query and compact_query in document.compact_source_text:
                phrase_boost += 0.2
            if exact_phrases:
                for phrase in exact_phrases:
                    compact_phrase = self._normalize_compact_text(phrase)
                    if compact_phrase and compact_phrase in document.compact_text:
                        phrase_boost += 0.25
                        break
                    if compact_phrase and compact_phrase in document.compact_source_text:
                        phrase_boost += 0.15
                        break
            candidate_scores[doc_index] = score + phrase_boost

        if not candidate_scores:
            return []

        # `max_score`：用于把最终分数压缩到 0~1 区间。
        max_score = max(candidate_scores.values()) or 1.0
        ranked_indices = sorted(candidate_scores, key=lambda item: candidate_scores[item], reverse=True)[:top_k]

        results: List[Dict[str, Any]] = []
        for doc_index in ranked_indices:
            document = documents[doc_index]
            raw_score = candidate_scores[doc_index]
            normalized_score = raw_score / max_score if max_score else 0.0
            metadata = dict(document.metadata)
            metadata["keyword_score"] = normalized_score
            metadata["keyword_score_raw"] = raw_score
            metadata["matched_terms"] = sorted(matched_terms.get(doc_index, set()))
            results.append(
                {
                    "id": document.doc_id,
                    "content": document.content,
                    "score": normalized_score,
                    "metadata": metadata,
                }
            )

        return results

    def search_exact_phrases(
        self,
        index: Dict[str, Any],
        phrases: Sequence[str],
        *,
        top_k: int | None = None,
    ) -> List[Dict[str, Any]]:
        """在已构建的关键词索引上执行精确短语匹配。

        优化点：
        - 先用 phrase 的 token postings 预选候选文档；
        - 再对候选文档做 compact_text / compact_source_text 的包含判断；
        - 避免每次短语查询都全量扫描整个语料。
        """
        if not index or not phrases:
            return []

        documents: List[KeywordDocument] = index.get("documents", [])
        postings: Dict[str, List[tuple[int, int]]] = index.get("postings", {})
        if not documents:
            return []

        matched_results: Dict[str, Dict[str, Any]] = {}
        for phrase in phrases:
            compact_phrase = self._normalize_compact_text(phrase)
            if not compact_phrase:
                continue

            phrase_tokens = [token for token in self._tokenize_text(phrase) if token]
            candidate_indices: set[int] = set()
            for token in phrase_tokens:
                candidate_indices.update(doc_index for doc_index, _ in postings.get(token, []))

            if not candidate_indices:
                candidate_indices = set(range(len(documents)))

            for doc_index in sorted(candidate_indices):
                document = documents[doc_index]
                matched_in_content = compact_phrase in document.compact_text
                matched_in_source = compact_phrase in document.compact_source_text
                if not matched_in_content and not matched_in_source:
                    continue

                # 中文说明：正文中的短语命中仍然视为强信号；
                # 但仅文件名/来源字段命中时，只保留弱辅助分，避免“大总结”类文件名长期霸榜。
                score = 0.98 if matched_in_content else 0.35
                existing = matched_results.get(document.doc_id)
                if existing is None:
                    metadata = dict(document.metadata)
                    metadata["matched_phrases"] = [phrase]
                    metadata["exact_phrase_match"] = matched_in_content
                    metadata["exact_phrase_in_source"] = bool(matched_in_source and not matched_in_content)
                    metadata["exact_phrase_score"] = score
                    matched_results[document.doc_id] = {
                        "id": document.doc_id,
                        "content": document.content,
                        "score": score,
                        "metadata": metadata,
                    }
                    continue

                existing_metadata = dict(existing.get("metadata") or {})
                matched_phrases = list(existing_metadata.get("matched_phrases") or [])
                if phrase not in matched_phrases:
                    matched_phrases.append(phrase)
                existing_metadata["matched_phrases"] = matched_phrases
                existing_metadata["exact_phrase_match"] = bool(
                    existing_metadata.get("exact_phrase_match") or matched_in_content
                )
                existing_metadata["exact_phrase_in_source"] = bool(
                    existing_metadata.get("exact_phrase_in_source") or (matched_in_source and not matched_in_content)
                )
                existing_metadata["exact_phrase_score"] = max(
                    float(existing_metadata.get("exact_phrase_score", 0.0) or 0.0),
                    score,
                )
                existing["score"] = max(float(existing.get("score", 0.0) or 0.0), score)
                existing["metadata"] = existing_metadata

        ranked = sorted(
            matched_results.values(),
            key=lambda item: (
                float(item.get("score", 0.0) or 0.0),
                len(item.get("metadata", {}).get("matched_phrases", []) or []),
            ),
            reverse=True,
        )
        return ranked[:top_k] if top_k else ranked

    def _build_source_text(self, metadata: Dict[str, Any]) -> str:
        """从元数据中拼接辅助检索文本。

        这里改成“结构化上下文优先”，不再把文件名、原始文件名和通用 source
        直接并入主关键词语料，避免单个总结类文档仅凭文件名就长期压制正文更相关的结果。
        """
        parts = [
            str(metadata.get(field, "") or "")
            for field in (
                "title",
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
        ]
        return " ".join(part for part in parts if part)

    def _extract_exact_phrases(self, query: str) -> List[str]:
        """从查询中提取被引号或书名号包裹的精确短语。"""
        phrases: List[str] = []
        for pattern in (r'["“](.{2,}?)[”"]', r'[《「](.{2,}?)[》」]'):
            for match in re.findall(pattern, query or ""):
                candidate = match.strip()
                if candidate and candidate not in phrases:
                    phrases.append(candidate)
        return phrases

    def _tokenize_text(self, text: str) -> List[str]:
        """对文本执行标准化与分词。

        处理规则：
        - 英文和数字连续串视为一个 token。
        - 中文连续串会拆成双字 gram，并在长度较短时保留整词。
        - 过滤常见英文停用词，减少噪声匹配。
        """
        normalized = unicodedata.normalize("NFKC", str(text or "")).lower()
        segments = re.findall(r"[a-z0-9]+|[\u4e00-\u9fff]+", normalized)
        tokens: List[str] = []

        for segment in segments:
            if re.fullmatch(r"[a-z0-9]+", segment):
                if len(segment) > 1 and segment not in self._EN_STOPWORDS:
                    tokens.append(segment)
                continue

            if len(segment) <= 2:
                tokens.append(segment)
            else:
                tokens.extend(segment[index:index + 2] for index in range(len(segment) - 1))
                if len(segment) <= 12:
                    tokens.append(segment)

        return tokens

    def _normalize_compact_text(self, text: str) -> str:
        """对文本做去空白标准化，便于精确匹配。"""
        normalized = unicodedata.normalize("NFKC", str(text or "")).lower()
        return re.sub(r"\s+", "", normalized)
