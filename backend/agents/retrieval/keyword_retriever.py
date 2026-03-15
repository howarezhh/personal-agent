
from __future__ import annotations

from collections import Counter, defaultdict
from dataclasses import dataclass
import math
import re
import unicodedata
from typing import Any, Dict, Iterable, List, Sequence


@dataclass(frozen=True)
class KeywordDocument:
    doc_id: str
    content: str
    metadata: Dict[str, Any]
    source_text: str
    token_freq: Counter[str]
    length: int
    compact_text: str
    compact_source_text: str


class KeywordRetriever:
    _EN_STOPWORDS = {
        "a", "an", "and", "are", "as", "at", "be", "by", "for", "from", "in", "is",
        "of", "on", "or", "that", "the", "this", "to", "was", "were", "with",
    }

    def __init__(self, k1: float = 1.5, b: float = 0.75):
        self.k1 = k1
        self.b = b

    def build_index(self, ids: Sequence[str], documents: Sequence[str], metadatas: Sequence[Dict[str, Any]]) -> Dict[str, Any]:
        indexed_documents: List[KeywordDocument] = []
        postings: Dict[str, List[tuple[int, int]]] = defaultdict(list)
        document_frequency: Counter[str] = Counter()

        for index, doc_id in enumerate(ids):
            content = str(documents[index] if index < len(documents) else "")
            metadata = dict(metadatas[index] if index < len(metadatas) else {})
            source_text = self._build_source_text(metadata)
            token_freq = Counter(self._tokenize_text("\n".join(part for part in [content, source_text] if part)))
            if not token_freq:
                continue

            compact_text = self._normalize_compact_text(content)
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

        for doc_index, document in enumerate(indexed_documents):
            for token, frequency in document.token_freq.items():
                postings[token].append((doc_index, frequency))
            document_frequency.update(document.token_freq.keys())

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
        documents: List[KeywordDocument] = index.get("documents", [])
        postings: Dict[str, List[tuple[int, int]]] = index.get("postings", {})
        document_frequency: Counter[str] = index.get("document_frequency", Counter())
        document_count = index.get("document_count", 0)
        average_length = index.get("average_length", 0.0) or 1.0

        if not documents or not query:
            return []

        query_tokens = self._tokenize_text(query)
        if not query_tokens:
            return []

        candidate_scores: Dict[int, float] = defaultdict(float)
        matched_terms: Dict[int, set[str]] = defaultdict(set)

        for token in query_tokens:
            posting_list = postings.get(token, [])
            if not posting_list:
                continue

            df = document_frequency.get(token, 0)
            if df <= 0:
                continue

            idf = math.log(1.0 + ((document_count - df + 0.5) / (df + 0.5)))
            for doc_index, term_frequency in posting_list:
                document = documents[doc_index]
                denominator = term_frequency + self.k1 * (1 - self.b + self.b * (document.length / average_length))
                score = idf * ((term_frequency * (self.k1 + 1)) / denominator)
                candidate_scores[doc_index] += score
                matched_terms[doc_index].add(token)

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

    def _build_source_text(self, metadata: Dict[str, Any]) -> str:
        parts = [
            str(metadata.get(field, "") or "")
            for field in ("source", "file_name", "filename", "title", "original_filename")
        ]
        return " ".join(part for part in parts if part)

    def _extract_exact_phrases(self, query: str) -> List[str]:
        phrases: List[str] = []
        for pattern in (r'["“](.{2,}?)[”"]', r'[《「](.{2,}?)[》」]'):
            for match in re.findall(pattern, query or ""):
                candidate = match.strip()
                if candidate and candidate not in phrases:
                    phrases.append(candidate)
        return phrases

    def _tokenize_text(self, text: str) -> List[str]:
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
        normalized = unicodedata.normalize("NFKC", str(text or "")).lower()
        return re.sub(r"\s+", "", normalized)
