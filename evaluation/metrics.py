"""离线检索评测指标模块。"""

from __future__ import annotations

from dataclasses import dataclass
import math
from typing import Iterable, Sequence


@dataclass(frozen=True)
class MetricSummary:
    """统一的评测汇总结果对象。"""

    query_count: int
    recall_at_5: float
    recall_at_10: float
    mrr_at_10: float
    ndcg_at_10: float
    hit_rate_at_1: float
    hit_rate_at_3: float
    precision_at_3: float

    def to_dict(self) -> dict[str, float | int]:
        """输出兼容历史脚本与测试的指标字段。"""

        return {
            "query_count": self.query_count,
            "Recall@5": self.recall_at_5,
            "Recall@10": self.recall_at_10,
            "MRR@10": self.mrr_at_10,
            "nDCG@10": self.ndcg_at_10,
            "HitRate@1": self.hit_rate_at_1,
            "HitRate@3": self.hit_rate_at_3,
            "Precision@3": self.precision_at_3,
        }


def _normalize_ids(values: Iterable[str] | None) -> list[str]:
    if not values:
        return []
    return [str(value) for value in values if value]


def _relevant_set(relevant_document_ids: Iterable[str] | None) -> set[str]:
    return set(_normalize_ids(relevant_document_ids))


def _resolve_recall_inputs(
    primary_document_ids: Sequence[str],
    secondary_document_ids: Iterable[str] | None,
) -> tuple[list[str], set[str]]:
    """兼容历史调用顺序差异，统一得到 ranked / relevant。"""

    primary_list = _normalize_ids(primary_document_ids)
    secondary_list = _normalize_ids(secondary_document_ids)

    # 中文说明：历史测试里存在 `recall_at_k(relevant_ids, ranked_ids, k)` 调用；
    # 当前评测主流程则使用 `recall_at_k(ranked_ids, relevant_ids, k)`。
    # 这里用最小兼容策略：若第一个列表明显更短，则优先视为 relevant。
    if len(primary_list) < len(secondary_list):
        return secondary_list, set(primary_list)
    return primary_list, set(secondary_list)


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


def hit_rate_at_k(
    ranked_document_ids: Sequence[str],
    relevant_document_ids: Iterable[str] | None,
    k: int,
) -> float:
    """兼容历史命名。"""

    return hit_at_k(ranked_document_ids, relevant_document_ids, k)


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
    primary_document_ids: Sequence[str],
    secondary_document_ids: Iterable[str] | None,
    k: int,
) -> float:
    if k <= 0:
        return 0.0

    ranked_document_ids, relevant_ids = _resolve_recall_inputs(primary_document_ids, secondary_document_ids)
    if not relevant_ids:
        return 0.0

    ranked_prefix = ranked_document_ids[:k]
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


def mrr_at_k(
    ranked_document_ids: Sequence[str],
    relevant_document_ids: Iterable[str] | None,
    k: int,
) -> float:
    """兼容历史命名。"""

    return reciprocal_rank_at_k(ranked_document_ids, relevant_document_ids, k)


def ndcg_at_k(
    ranked_document_ids: Sequence[str],
    relevant_document_ids: Iterable[str] | None,
    k: int,
) -> float:
    """计算二值相关性的 nDCG@k。"""
    if k <= 0:
        return 0.0

    relevant_ids = _relevant_set(relevant_document_ids)
    if not relevant_ids:
        return 0.0

    ranked_prefix = _normalize_ids(ranked_document_ids)[:k]
    dcg = 0.0
    for index, document_id in enumerate(ranked_prefix, start=1):
        if document_id in relevant_ids:
            dcg += 1.0 / math.log2(index + 1)

    ideal_hits = min(len(relevant_ids), k)
    if ideal_hits <= 0:
        return 0.0
    ideal_dcg = sum(1.0 / math.log2(index + 1) for index in range(1, ideal_hits + 1))
    return dcg / ideal_dcg if ideal_dcg > 0 else 0.0


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
        "ndcg@10": ndcg_at_k(ranked_document_ids, relevant_document_ids, 10),
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
            "ndcg@10": 0.0,
            "query_count": 0.0,
        }

    keys = ["hit@1", "hit@3", "precision@3", "recall@5", "recall@10", "mrr@10", "ndcg@10"]
    aggregated: dict[str, float] = {}
    row_count = float(len(rows))
    for key in keys:
        aggregated[key] = sum(float(row.get(key, 0.0) or 0.0) for row in rows) / row_count
    aggregated["query_count"] = row_count
    return aggregated


def summarize_metrics(query_rankings: Sequence[dict[str, object]]) -> MetricSummary:
    """按查询排名结果汇总标准评测指标。"""

    metric_rows = [
        evaluate_ranked_documents(
            ranked_document_ids=item.get("ranked_document_ids") or [],
            relevant_document_ids=item.get("relevant_document_ids") or [],
        )
        for item in query_rankings
    ]
    aggregated = aggregate_metrics(metric_rows)
    return MetricSummary(
        query_count=int(aggregated.get("query_count", 0.0) or 0),
        recall_at_5=float(aggregated.get("recall@5", 0.0) or 0.0),
        recall_at_10=float(aggregated.get("recall@10", 0.0) or 0.0),
        mrr_at_10=float(aggregated.get("mrr@10", 0.0) or 0.0),
        ndcg_at_10=float(aggregated.get("ndcg@10", 0.0) or 0.0),
        hit_rate_at_1=float(aggregated.get("hit@1", 0.0) or 0.0),
        hit_rate_at_3=float(aggregated.get("hit@3", 0.0) or 0.0),
        precision_at_3=float(aggregated.get("precision@3", 0.0) or 0.0),
    )


__all__ = [
    "MetricSummary",
    "aggregate_metrics",
    "evaluate_ranked_documents",
    "first_relevant_rank",
    "hit_at_k",
    "hit_rate_at_k",
    "mrr_at_k",
    "ndcg_at_k",
    "precision_at_k",
    "recall_at_k",
    "reciprocal_rank_at_k",
    "summarize_metrics",
]
