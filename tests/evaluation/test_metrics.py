from evaluation.metrics import hit_rate_at_k, mrr_at_k, precision_at_k, recall_at_k, summarize_metrics


def test_metric_functions_cover_single_and_multiple_relevant_ids():
    ranked_ids = ["doc-1", "doc-2", "doc-3"]
    relevant_ids = ["doc-2", "doc-4"]

    assert recall_at_k(relevant_ids, ranked_ids, 2) == 0.5
    assert hit_rate_at_k(ranked_ids, relevant_ids, 2) == 1.0
    assert precision_at_k(relevant_ids, ranked_ids, 2) == 0.5
    assert mrr_at_k(ranked_ids, relevant_ids, 3) == 0.5


def test_summarize_metrics_aggregates_query_rankings():
    rankings = [
        {
            "ranked_document_ids": ["doc-1", "doc-2"],
            "relevant_document_ids": ["doc-1"],
        },
        {
            "ranked_document_ids": ["doc-3", "doc-2"],
            "relevant_document_ids": ["doc-2", "doc-4"],
        },
    ]

    metrics = summarize_metrics(rankings).to_dict()

    assert metrics["query_count"] == 2
    assert metrics["Recall@5"] == 0.75
    assert metrics["MRR@10"] == 0.75
    assert metrics["HitRate@1"] == 0.5
