"""Hybrid LangChain retriever for the project's retrieval pipeline."""

from __future__ import annotations

import asyncio
from typing import Any, Callable, Dict, List, Optional

from langchain_core.documents import Document
from langchain_core.retrievers import BaseRetriever
from pydantic import ConfigDict, Field


class HybridLangChainRetriever(BaseRetriever):
    """Expose hybrid recall through LangChain's retriever abstraction."""

    model_config = ConfigDict(arbitrary_types_allowed=True)

    corpus: Dict[str, Any] = Field(default_factory=dict)
    keyword_index: Dict[str, Any] = Field(default_factory=dict)
    vector_retriever: Any = None
    using_database_fallback_corpus: bool = False
    keyword_top_k: int = 8
    keyword_min_score: float = 0.0
    similarity_threshold: float = 0.0
    enable_exact_phrase: bool = True
    enable_keyword_search: bool = True
    enable_dense_vector: bool = True
    exact_phrase_extractor: Callable[[str], List[str]]
    exact_phrase_search: Callable[[List[str], Dict[str, Any]], List[Dict[str, Any]]]
    keyword_search: Callable[..., List[Dict[str, Any]]]
    distance_to_similarity: Callable[[float], float]

    def _document_from_result(
        self,
        *,
        query: str,
        result: Dict[str, Any],
        match_source: str,
        source_rank: int,
    ) -> Document:
        metadata = dict(result.get("metadata") or {})
        metadata.setdefault("document_id", result.get("id"))
        metadata["matched_query"] = query
        metadata["match_source"] = match_source
        metadata["source_rank"] = int(source_rank)
        metadata["retrieval_score"] = float(result.get("score", 0.0) or 0.0)
        return Document(page_content=str(result.get("content", "") or ""), metadata=metadata)

    def _get_relevant_documents(self, query: str) -> List[Document]:
        raise NotImplementedError("Use async retrieval for hybrid retriever")

    async def _aget_relevant_documents(self, query: str) -> List[Document]:
        documents: List[Document] = []

        if self.enable_exact_phrase:
            exact_phrases = self.exact_phrase_extractor(query)
            exact_phrase_corpus = self.keyword_index if self.keyword_index else self.corpus
            for source_rank, result in enumerate(self.exact_phrase_search(exact_phrases, exact_phrase_corpus), start=1):
                documents.append(
                    self._document_from_result(
                        query=query,
                        result=result,
                        match_source="exact_phrase",
                        source_rank=source_rank,
                    )
                )

        if self.enable_keyword_search and self.keyword_index:
            keyword_results = await asyncio.to_thread(
                self.keyword_search,
                query,
                self.keyword_index,
                top_k=self.keyword_top_k,
                min_score=self.keyword_min_score,
            )
            keyword_source = "text" if self.using_database_fallback_corpus else "keyword"
            for source_rank, result in enumerate(keyword_results, start=1):
                documents.append(
                    self._document_from_result(
                        query=query,
                        result=result,
                        match_source=keyword_source,
                        source_rank=source_rank,
                    )
                )

        if self.enable_dense_vector and self.vector_retriever is not None:
            vector_documents = await self.vector_retriever.ainvoke(query)
            for source_rank, document in enumerate(vector_documents, start=1):
                metadata = dict(getattr(document, "metadata", {}) or {})
                distance = float(metadata.get("distance", 1.0) or 1.0)
                similarity_score = self.distance_to_similarity(distance)
                if similarity_score < self.similarity_threshold:
                    continue
                metadata["retrieval_score"] = similarity_score
                metadata["match_source"] = "vector"
                metadata["matched_query"] = query
                metadata["source_rank"] = int(source_rank)
                documents.append(
                    Document(
                        page_content=str(getattr(document, "page_content", "") or ""),
                        metadata=metadata,
                    )
                )

        return documents


__all__ = ["HybridLangChainRetriever"]
