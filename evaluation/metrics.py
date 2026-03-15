"""Metrics for offline retrieval evaluation."""

from __future__ import annotations

from typing import Iterable, Sequence


def _normalize_ids(values: Iterable[str] | None) -> list[str]:
    if not values:
        return []
    return [str(value) for value in values if value]


def _relevant_set(relevant_document_ids: Iterable[str] | None) -> set[str]:
    return set(_normalize_ids(relevant_document_ids))


def first_relevant_rank(
    ranked_document_ids: Sequence[str],
    relevant_document_ids: Iterable[str] | None,
    *,
    cutoff: int | None = None,
) -> int | None:
    relevant_ids = _relevant_set(relevant_document_ids)
    if not relevant_ids:
        return None

    for index, document_id in enumerate(_normalize_ids(ranked_document_ids), start=1):
        if cutoff is not None and index > cutoff:
            break
        if document_id in relevant_ids:
            return index
    return None


def hit_at_k(
    ranked_document_ids: Sequence[str],
    relevant_document_ids: Iterable[str] | None,
    k: int,
) -> float:
    if k <= 0:
        return 0.0
    rank = first_relevant_rank(ranked_document_ids, relevant_document_ids, cutoff=k)
    return 1.0 if rank is not None else 0.0


def precision_at_k(
    ranked_document_ids: Sequence[str],
    relevant_document_ids: Iterable[str] | None,
    k: int,
) -> float:
    if k <= 0:
        return 0.0

    relevant_ids = _relevant_set(relevant_document_ids)
    if not relevant_ids:
        return 0.0

    ranked_prefix = _normalize_ids(ranked_document_ids)[:k]
    hits = sum(1 for document_id in ranked_prefix if document_id in relevant_ids)
    return hits / float(k)


def recall_at_k(
    ranked_document_ids: Sequence[str],
    relevant_document_ids: Iterable[str] | None,
    k: int,
) -> float:
    if k <= 0:
        return 0.0

    relevant_ids = _relevant_set(relevant_document_ids)
    if not relevant_ids:
        return 0.0

    ranked_prefix = _normalize_ids(ranked_document_ids)[:k]
    hits = sum(1 for document_id in ranked_prefix if document_id in relevant_ids)
    return hits / float(len(relevant_ids))


def reciprocal_rank_at_k(
    ranked_document_ids: Sequence[str],
    relevant_document_ids: Iterable[str] | None,
    k: int,
) -> float:
    if k <= 0:
        return 0.0

    rank = first_relevant_rank(ranked_document_ids, relevant_document_ids, cutoff=k)
    return 1.0 / float(rank) if rank is not None else 0.0


def evaluate_ranked_documents(
    ranked_document_ids: Sequence[str],
    relevant_document_ids: Iterable[str] | None,
) -> dict[str, float | int | None]:
    return {
        "hit@1": hit_at_k(ranked_document_ids, relevant_document_ids, 1),
        "hit@3": hit_at_k(ranked_document_ids, relevant_document_ids, 3),
        "precision@3": precision_at_k(ranked_document_ids, relevant_document_ids, 3),
        "recall@5": recall_at_k(ranked_document_ids, relevant_document_ids, 5),
        "recall@10": recall_at_k(ranked_document_ids, relevant_document_ids, 10),
        "mrr@10": reciprocal_rank_at_k(ranked_document_ids, relevant_document_ids, 10),
        "first_relevant_rank": first_relevant_rank(ranked_document_ids, relevant_document_ids, cutoff=10),
    }


def aggregate_metrics(rows: Sequence[dict[str, float | int | None]]) -> dict[str, float]:
    if not rows:
        return {
            "hit@1": 0.0,
            "hit@3": 0.0,
            "precision@3": 0.0,
            "recall@5": 0.0,
            "recall@10": 0.0,
            "mrr@10": 0.0,
            "query_count": 0.0,
        }

    keys = ["hit@1", "hit@3", "precision@3", "recall@5", "recall@10", "mrr@10"]
    aggregated: dict[str, float] = {}
    row_count = float(len(rows))
    for key in keys:
        aggregated[key] = sum(float(row.get(key, 0.0) or 0.0) for row in rows) / row_count
    aggregated["query_count"] = row_count
    return aggregated
