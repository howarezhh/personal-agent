from __future__ import annotations

from evaluation.metrics import aggregate_metrics, evaluate_ranked_documents, ndcg_at_k


def test_ndcg_at_k_returns_expected_value():
    ranked = ["d1", "d2", "d3", "d4"]
    relevant = ["d2", "d4"]
    value = ndcg_at_k(ranked, relevant, 4)
    assert 0.0 < value <= 1.0


def test_evaluate_ranked_documents_contains_ndcg():
    metrics = evaluate_ranked_documents(["d1", "d2", "d3"], ["d2"])
    assert "ndcg@10" in metrics
    assert metrics["mrr@10"] == 0.5


def test_aggregate_metrics_includes_ndcg():
    aggregated = aggregate_metrics(
        [
            {"hit@1": 1.0, "hit@3": 1.0, "precision@3": 0.33, "recall@5": 1.0, "recall@10": 1.0, "mrr@10": 1.0, "ndcg@10": 1.0},
            {"hit@1": 0.0, "hit@3": 1.0, "precision@3": 0.33, "recall@5": 1.0, "recall@10": 1.0, "mrr@10": 0.5, "ndcg@10": 0.63},
        ]
    )
    assert "ndcg@10" in aggregated
    assert aggregated["query_count"] == 2.0
