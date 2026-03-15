from __future__ import annotations

import json
import time
from dataclasses import dataclass
from typing import Any, Mapping, Sequence

from backend.agents.retrieval.keyword_retriever import KeywordRetriever
from backend.database.database_manager import get_database_manager
from backend.utils.vector_db_client import get_vector_db_client


RETRIEVAL_MODES = ("vector", "bm25", "hybrid_rrf")


@dataclass(frozen=True)
class ChunkRecord:
    chunk_id: str
    document_id: str
    file_id: str
    file_name: str
    chunk_index: int
    content: str
    metadata: dict[str, Any]


@dataclass(frozen=True)
class RetrievalCorpus:
    knowledge_base_id: str
    document_ids: tuple[str, ...]
    document_infos: dict[str, dict[str, Any]]
    chunks: tuple[ChunkRecord, ...]


def load_dataset_corpus(dataset: Mapping[str, Any], db_manager=None) -> RetrievalCorpus:
    knowledge_base = dict(dataset.get("knowledge_base") or {})
    knowledge_base_id = str(knowledge_base.get("knowledge_base_id") or "").strip()
    source_documents = list(dataset.get("source_documents") or [])
    document_infos = {
        str(document["document_id"]): {
            "document_id": str(document["document_id"]),
            "file_name": str(document.get("file_name") or ""),
            "chunk_count": int(document.get("chunk_count") or 0),
            "topic": str(document.get("topic") or ""),
        }
        for document in source_documents
        if document.get("document_id")
    }
    document_ids = tuple(document_infos.keys())
    if not document_ids:
        raise ValueError("Dataset source_documents is empty; cannot build offline retrieval corpus.")

    active_db_manager = db_manager or get_database_manager()
    placeholders = ", ".join(["%s"] * len(document_ids))
    sql = f"""
        SELECT fc.chunk_id, fc.chunk_index, fc.content,
               f.file_id, f.original_filename, f.metadata AS file_metadata
        FROM file_chunks fc
        INNER JOIN files f ON f.file_id = fc.file_id
        WHERE f.file_id IN ({placeholders})
          AND f.processing_status = 'completed'
        ORDER BY f.file_id ASC, fc.chunk_index ASC
    """
    rows = active_db_manager.execute_query(sql, document_ids)

    chunks: list[ChunkRecord] = []
    for row in rows or []:
        file_metadata = _coerce_dict(row.get("file_metadata"))
        file_id = str(row.get("file_id") or "")
        document_id = str(file_metadata.get("document_id") or file_id)
        if document_id not in document_infos:
            continue

        file_name = str(row.get("original_filename") or document_infos[document_id].get("file_name") or "")
        metadata = {
            "chunk_id": str(row.get("chunk_id") or ""),
            "chunk_index": int(row.get("chunk_index") or 0),
            "file_id": file_id,
            "document_id": document_id,
            "file_name": file_name,
            "source": file_name,
            "knowledge_base_id": knowledge_base_id,
        }
        metadata.update(file_metadata)
        chunks.append(
            ChunkRecord(
                chunk_id=str(row.get("chunk_id") or ""),
                document_id=document_id,
                file_id=file_id,
                file_name=file_name,
                chunk_index=int(row.get("chunk_index") or 0),
                content=str(row.get("content") or ""),
                metadata=metadata,
            )
        )

    loaded_document_ids = {chunk.document_id for chunk in chunks}
    missing_document_ids = sorted(set(document_ids) - loaded_document_ids)
    if missing_document_ids:
        raise ValueError(f"Missing completed chunks for source documents: {', '.join(missing_document_ids)}")

    return RetrievalCorpus(
        knowledge_base_id=knowledge_base_id,
        document_ids=document_ids,
        document_infos=document_infos,
        chunks=tuple(chunks),
    )


def reciprocal_rank_fusion(
    rankings: Mapping[str, Sequence[Mapping[str, Any]]],
    *,
    rrf_k: int = 60,
    top_k: int | None = None,
) -> list[dict[str, Any]]:
    fused_scores: dict[str, dict[str, Any]] = {}

    for source_name, ranking in rankings.items():
        for rank, item in enumerate(ranking, start=1):
            document_id = str(item.get("document_id") or "")
            if not document_id:
                continue

            entry = fused_scores.setdefault(
                document_id,
                {
                    "document_id": document_id,
                    "file_name": item.get("file_name") or "",
                    "score": 0.0,
                    "source_ranks": {},
                    "source_scores": {},
                    "supporting_chunk_ids": [],
                },
            )
            entry["score"] += 1.0 / (rrf_k + rank)
            entry["source_ranks"][source_name] = rank
            entry["source_scores"][source_name] = float(item.get("score", 0.0) or 0.0)
            for chunk_id in item.get("supporting_chunk_ids") or []:
                if chunk_id not in entry["supporting_chunk_ids"]:
                    entry["supporting_chunk_ids"].append(chunk_id)

    results = list(fused_scores.values())
    results.sort(
        key=lambda item: (
            -float(item.get("score", 0.0) or 0.0),
            -len(item.get("source_ranks") or {}),
            min(item.get("source_ranks", {}).values()) if item.get("source_ranks") else 10**9,
        )
    )
    return results[:top_k] if top_k is not None else results


class OfflineRetrievalExperiment:
    def __init__(
        self,
        corpus: RetrievalCorpus,
        *,
        vector_store=None,
        keyword_retriever: KeywordRetriever | None = None,
        similarity_metric: str = "l2",
        rrf_k: int = 60,
    ):
        self.corpus = corpus
        self.vector_store = vector_store or get_vector_db_client()
        self.keyword_retriever = keyword_retriever or KeywordRetriever()
        self.similarity_metric = similarity_metric
        self.rrf_k = rrf_k
        self.allowed_document_ids = set(corpus.document_ids)
        self.chunk_lookup = {chunk.chunk_id: chunk for chunk in corpus.chunks}
        self.keyword_index = self.keyword_retriever.build_index(
            ids=[chunk.chunk_id for chunk in corpus.chunks],
            documents=[chunk.content for chunk in corpus.chunks],
            metadatas=[dict(chunk.metadata) for chunk in corpus.chunks],
        )

    def retrieve(self, query: str, mode: str, *, top_k: int = 10) -> list[dict[str, Any]]:
        normalized_mode = self._normalize_mode(mode)
        if normalized_mode == "vector":
            return self._retrieve_vector_documents(query, top_k=top_k)
        if normalized_mode == "bm25":
            return self._retrieve_bm25_documents(query, top_k=top_k)
        if normalized_mode == "hybrid_rrf":
            return self._retrieve_hybrid_documents(query, top_k=top_k)
        raise ValueError(f"Unsupported retrieval mode: {mode}")

    def retrieve_all(self, query: str, *, top_k: int = 10) -> tuple[dict[str, list[dict[str, Any]]], dict[str, float]]:
        vector_started_at = time.perf_counter()
        vector_results = self._retrieve_vector_documents(query, top_k=None)
        vector_elapsed = time.perf_counter() - vector_started_at

        bm25_started_at = time.perf_counter()
        bm25_results = self._retrieve_bm25_documents(query, top_k=None)
        bm25_elapsed = time.perf_counter() - bm25_started_at

        hybrid_started_at = time.perf_counter()
        hybrid_results = reciprocal_rank_fusion(
            {"vector": vector_results, "bm25": bm25_results},
            rrf_k=self.rrf_k,
            top_k=top_k,
        )
        hybrid_elapsed = time.perf_counter() - hybrid_started_at

        return (
            {
                "vector": vector_results[:top_k],
                "bm25": bm25_results[:top_k],
                "hybrid_rrf": hybrid_results,
            },
            {
                "vector": vector_elapsed,
                "bm25": bm25_elapsed,
                "hybrid_rrf": vector_elapsed + bm25_elapsed + hybrid_elapsed,
            },
        )

    def _retrieve_vector_documents(self, query: str, *, top_k: int | None) -> list[dict[str, Any]]:
        search_results = self.vector_store.search(
            query=query,
            n_results=max(1, len(self.corpus.chunks)),
            where={"knowledge_base_id": self.corpus.knowledge_base_id} if self.corpus.knowledge_base_id else None,
        )
        ids = _flatten_collection_values(search_results.get("ids"))
        documents = _flatten_collection_values(search_results.get("documents"))
        distances = _flatten_collection_values(search_results.get("distances"))
        metadatas = _flatten_collection_values(search_results.get("metadatas"))

        chunk_hits: list[dict[str, Any]] = []
        for index, raw_chunk_id in enumerate(ids):
            metadata = dict(metadatas[index] if index < len(metadatas) and metadatas[index] else {})
            chunk_id = str(metadata.get("chunk_id") or raw_chunk_id or "")
            chunk = self.chunk_lookup.get(chunk_id)
            document_id = str(metadata.get("document_id") or metadata.get("file_id") or (chunk.document_id if chunk else ""))
            if document_id not in self.allowed_document_ids:
                continue

            distance = float(distances[index] if index < len(distances) and distances[index] is not None else 1.0)
            similarity_score = _convert_distance_to_similarity(distance, metric=self.similarity_metric)
            file_name = str(
                metadata.get("file_name")
                or metadata.get("original_filename")
                or metadata.get("source")
                or (chunk.file_name if chunk else self.corpus.document_infos.get(document_id, {}).get("file_name", ""))
            )
            supporting_chunk_id = chunk_id or (chunk.chunk_id if chunk else "")
            chunk_hits.append(
                {
                    "chunk_id": supporting_chunk_id,
                    "document_id": document_id,
                    "file_name": file_name,
                    "content": documents[index] if index < len(documents) and documents[index] is not None else (chunk.content if chunk else ""),
                    "score": similarity_score,
                    "metadata": metadata,
                }
            )

        ranked_documents = _aggregate_document_hits(chunk_hits)
        return ranked_documents[:top_k] if top_k is not None else ranked_documents

    def _retrieve_bm25_documents(self, query: str, *, top_k: int | None) -> list[dict[str, Any]]:
        chunk_results = self.keyword_retriever.search(self.keyword_index, query, top_k=max(1, len(self.corpus.chunks)))
        chunk_hits: list[dict[str, Any]] = []
        for result in chunk_results:
            metadata = dict(result.get("metadata") or {})
            chunk_id = str(result.get("id") or metadata.get("chunk_id") or "")
            chunk = self.chunk_lookup.get(chunk_id)
            document_id = str(metadata.get("document_id") or metadata.get("file_id") or (chunk.document_id if chunk else ""))
            if document_id not in self.allowed_document_ids:
                continue

            file_name = str(
                metadata.get("file_name")
                or metadata.get("original_filename")
                or metadata.get("source")
                or (chunk.file_name if chunk else self.corpus.document_infos.get(document_id, {}).get("file_name", ""))
            )
            chunk_hits.append(
                {
                    "chunk_id": chunk_id or (chunk.chunk_id if chunk else ""),
                    "document_id": document_id,
                    "file_name": file_name,
                    "content": result.get("content") or (chunk.content if chunk else ""),
                    "score": float(result.get("score", 0.0) or 0.0),
                    "metadata": metadata,
                }
            )

        ranked_documents = _aggregate_document_hits(chunk_hits)
        return ranked_documents[:top_k] if top_k is not None else ranked_documents

    def _retrieve_hybrid_documents(self, query: str, *, top_k: int | None) -> list[dict[str, Any]]:
        vector_results = self._retrieve_vector_documents(query, top_k=None)
        bm25_results = self._retrieve_bm25_documents(query, top_k=None)
        return reciprocal_rank_fusion(
            {"vector": vector_results, "bm25": bm25_results},
            rrf_k=self.rrf_k,
            top_k=top_k,
        )

    @staticmethod
    def _normalize_mode(mode: str) -> str:
        normalized_mode = str(mode or "").strip().lower()
        if normalized_mode == "hybrid":
            return "hybrid_rrf"
        return normalized_mode


def _coerce_dict(value: Any) -> dict[str, Any]:
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


def _flatten_collection_values(values: Any) -> list[Any]:
    if values is None:
        return []
    if isinstance(values, list) and values and isinstance(values[0], list):
        return values[0]
    if isinstance(values, tuple):
        return list(values)
    if isinstance(values, list):
        return values
    return [values]


def _convert_distance_to_similarity(distance: float, *, metric: str = "l2") -> float:
    if metric == "cosine":
        return max(0.0, min(1.0, 1.0 - distance))
    if metric == "ip":
        return max(0.0, min(1.0, (distance + 1.0) / 2.0))
    return 1.0 / (1.0 + distance)


def _aggregate_document_hits(chunk_hits: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    aggregated: dict[str, dict[str, Any]] = {}

    for rank, hit in enumerate(chunk_hits, start=1):
        document_id = str(hit.get("document_id") or "")
        if not document_id:
            continue

        chunk_id = str(hit.get("chunk_id") or "")
        score = float(hit.get("score", 0.0) or 0.0)
        entry = aggregated.setdefault(
            document_id,
            {
                "document_id": document_id,
                "file_name": str(hit.get("file_name") or ""),
                "score": score,
                "best_chunk_rank": rank,
                "supporting_chunk_ids": [],
                "chunk_hit_count": 0,
            },
        )

        entry["chunk_hit_count"] += 1
        if chunk_id and chunk_id not in entry["supporting_chunk_ids"]:
            entry["supporting_chunk_ids"].append(chunk_id)
        if score > float(entry.get("score", 0.0) or 0.0):
            entry["score"] = score
        if rank < int(entry.get("best_chunk_rank", rank)):
            entry["best_chunk_rank"] = rank
        if not entry.get("file_name") and hit.get("file_name"):
            entry["file_name"] = str(hit.get("file_name") or "")

    ranked = list(aggregated.values())
    ranked.sort(
        key=lambda item: (
            -float(item.get("score", 0.0) or 0.0),
            -int(item.get("chunk_hit_count", 0) or 0),
            int(item.get("best_chunk_rank", 10**9) or 10**9),
        )
    )
    return ranked
