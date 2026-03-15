from __future__ import annotations

import argparse
import csv
import json
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


PROJECT_ROOT = Path(__file__).resolve().parents[1]
project_root_str = str(PROJECT_ROOT)
if project_root_str not in sys.path:
    sys.path.insert(0, project_root_str)


from evaluation.experiments.exp_hybrid_search import (  # noqa: E402
    RETRIEVAL_MODES,
    OfflineRetrievalExperiment,
    load_dataset_corpus,
)
from evaluation.metrics import evaluate_query, summarize_query_metrics  # noqa: E402


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Offline comparison for vector, BM25, and hybrid RRF retrieval.")
    parser.add_argument(
        "--dataset",
        default="evaluation/datasets/biyesheji_retrieval_eval_50.json",
        help="Path to the retrieval evaluation dataset JSON file.",
    )
    parser.add_argument(
        "--output-dir",
        default="evaluation/results",
        help="Directory used to write the evaluation result files.",
    )
    parser.add_argument(
        "--top-k",
        type=int,
        default=10,
        help="Maximum number of ranked documents retained per strategy.",
    )
    return parser.parse_args()


def load_dataset(dataset_path: Path) -> dict[str, Any]:
    with dataset_path.open("r", encoding="utf-8") as handle:
        return json.load(handle)


def infer_query_tags(query: str) -> list[str]:
    normalized_query = str(query or "")
    tag_patterns = {
        "exact_numeric_requirement": ("多少", "几个", "几篇", "多长", "多久", "比例", "字", "时间", "%", "率"),
        "format_or_standard": ("格式", "标准", "编号", "字体", "国家标准", "参考文献"),
        "enumeration_or_scope": ("哪些", "哪几", "哪三", "组成", "包括", "分别", "分类", "范围"),
        "policy_rule": ("办法", "规定", "原则", "职责", "评选", "抽检", "申诉", "处理", "奖励"),
    }
    return [tag for tag, keywords in tag_patterns.items() if any(keyword in normalized_query for keyword in keywords)]


def choose_recommended_strategy(strategy_summaries: dict[str, dict[str, Any]]) -> str:
    def ranking_key(item: tuple[str, dict[str, Any]]) -> tuple[float, float, float, float]:
        _, payload = item
        metrics = payload["metrics"]
        return (
            float(metrics["MRR@10"]),
            float(metrics["Recall@10"]),
            float(metrics["Recall@5"]),
            float(metrics["Precision@3"]),
        )

    return max(strategy_summaries.items(), key=ranking_key)[0]


def is_better(lhs: dict[str, Any], rhs: dict[str, Any]) -> bool:
    lhs_key = (
        float(lhs["mrr_at_10"]),
        float(lhs["recall_at_10"]),
        float(lhs["recall_at_5"]),
        float(lhs["precision_at_3"]),
    )
    rhs_key = (
        float(rhs["mrr_at_10"]),
        float(rhs["recall_at_10"]),
        float(rhs["recall_at_5"]),
        float(rhs["precision_at_3"]),
    )
    return lhs_key > rhs_key


def build_comparison_analysis(
    dataset_items: list[dict[str, Any]],
    per_query_payload: dict[str, list[dict[str, Any]]],
    strategy_summaries: dict[str, dict[str, Any]],
) -> dict[str, Any]:
    vector_map = {item["query_id"]: item for item in per_query_payload["vector"]}
    bm25_map = {item["query_id"]: item for item in per_query_payload["bm25"]}
    hybrid_map = {item["query_id"]: item for item in per_query_payload["hybrid_rrf"]}

    bm25_better_than_vector: list[dict[str, Any]] = []
    hybrid_better_than_vector: list[dict[str, Any]] = []

    for item in dataset_items:
        query_id = item["query_id"]
        query = item["query"]
        tags = infer_query_tags(query)

        if is_better(bm25_map[query_id], vector_map[query_id]):
            bm25_better_than_vector.append({"query_id": query_id, "query": query, "tags": tags})
        if is_better(hybrid_map[query_id], vector_map[query_id]):
            hybrid_better_than_vector.append({"query_id": query_id, "query": query, "tags": tags})

    tag_counter: dict[str, int] = {}
    for item in bm25_better_than_vector:
        for tag in item["tags"]:
            tag_counter[tag] = tag_counter.get(tag, 0) + 1

    vector_metrics = strategy_summaries["vector"]["metrics"]
    hybrid_metrics = strategy_summaries["hybrid_rrf"]["metrics"]
    metric_delta = {
        metric_name: float(hybrid_metrics[metric_name]) - float(vector_metrics[metric_name])
        for metric_name in ("Recall@5", "Recall@10", "MRR@10", "Precision@3")
    }

    return {
        "recommended_strategy": choose_recommended_strategy(strategy_summaries),
        "bm25_better_than_vector_queries": bm25_better_than_vector,
        "hybrid_better_than_vector_queries": hybrid_better_than_vector,
        "bm25_advantage_query_patterns": sorted(tag_counter.items(), key=lambda item: (-item[1], item[0])),
        "hybrid_vs_vector_metric_delta": metric_delta,
    }


def main() -> int:
    args = parse_args()
    dataset_path = PROJECT_ROOT / args.dataset
    output_dir = PROJECT_ROOT / args.output_dir
    output_dir.mkdir(parents=True, exist_ok=True)

    dataset = load_dataset(dataset_path)
    corpus = load_dataset_corpus(dataset)
    experiment = OfflineRetrievalExperiment(corpus)
    dataset_items = list(dataset.get("items") or [])

    all_strategy_metrics: dict[str, list[Any]] = {mode: [] for mode in RETRIEVAL_MODES}
    per_query_payload: dict[str, list[dict[str, Any]]] = {mode: [] for mode in RETRIEVAL_MODES}
    duration_seconds: dict[str, float] = {mode: 0.0 for mode in RETRIEVAL_MODES}

    total_started_at = time.perf_counter()
    for item in dataset_items:
        results_by_mode, timing_by_mode = experiment.retrieve_all(item["query"], top_k=args.top_k)
        for mode in RETRIEVAL_MODES:
            duration_seconds[mode] += timing_by_mode[mode]
            ranked_document_ids = [result["document_id"] for result in results_by_mode[mode]]
            metrics = evaluate_query(item["query_id"], item["relevant_document_ids"], ranked_document_ids)
            all_strategy_metrics[mode].append(metrics)
            per_query_payload[mode].append(
                {
                    "query_id": item["query_id"],
                    "query": item["query"],
                    "query_tags": infer_query_tags(item["query"]),
                    "relevant_document_ids": item["relevant_document_ids"],
                    "retrieved_document_ids": ranked_document_ids,
                    "top_documents": results_by_mode[mode],
                    **metrics.to_dict(),
                }
            )
    total_elapsed = time.perf_counter() - total_started_at

    strategy_summaries = {
        mode: {
            "metrics": summarize_query_metrics(all_strategy_metrics[mode]),
            "duration_seconds": duration_seconds[mode],
            "avg_query_ms": (duration_seconds[mode] / len(dataset_items) * 1000.0) if dataset_items else 0.0,
        }
        for mode in RETRIEVAL_MODES
    }

    comparison_analysis = build_comparison_analysis(dataset_items, per_query_payload, strategy_summaries)
    recommended_strategy = comparison_analysis["recommended_strategy"]

    result_payload = {
        "experiment_name": "retrieval_strategy_comparison",
        "baseline": "vector",
        "optimized_candidates": ["bm25", "hybrid_rrf"],
        "dataset": {
            "path": args.dataset,
            "dataset_name": dataset.get("dataset_name"),
            "knowledge_base": dataset.get("knowledge_base"),
            "query_count": len(dataset_items),
            "source_document_count": len(corpus.document_ids),
            "source_chunk_count": len(corpus.chunks),
        },
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "strategies": strategy_summaries,
        "comparison": comparison_analysis,
        "per_query": per_query_payload,
        "total_duration_seconds": total_elapsed,
        "final_choice": recommended_strategy,
    }

    output_stem = f"{dataset.get('dataset_name', 'retrieval_eval')}_retrieval_comparison"
    json_path = output_dir / f"{output_stem}.json"
    csv_path = output_dir / f"{output_stem}.csv"

    with json_path.open("w", encoding="utf-8") as handle:
        json.dump(result_payload, handle, ensure_ascii=False, indent=2)

    with csv_path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(
            handle,
            fieldnames=["strategy", "Recall@5", "Recall@10", "MRR@10", "Precision@3", "duration_seconds", "avg_query_ms"],
        )
        writer.writeheader()
        for mode in RETRIEVAL_MODES:
            metrics = strategy_summaries[mode]["metrics"]
            writer.writerow(
                {
                    "strategy": mode,
                    "Recall@5": f"{float(metrics['Recall@5']):.4f}",
                    "Recall@10": f"{float(metrics['Recall@10']):.4f}",
                    "MRR@10": f"{float(metrics['MRR@10']):.4f}",
                    "Precision@3": f"{float(metrics['Precision@3']):.4f}",
                    "duration_seconds": f"{float(strategy_summaries[mode]['duration_seconds']):.4f}",
                    "avg_query_ms": f"{float(strategy_summaries[mode]['avg_query_ms']):.2f}",
                }
            )

    print(f"Evaluation completed. JSON: {json_path}")
    print(f"Evaluation completed. CSV: {csv_path}")
    for mode in RETRIEVAL_MODES:
        metrics = strategy_summaries[mode]["metrics"]
        print(
            f"{mode}: Recall@5={float(metrics['Recall@5']):.4f}, "
            f"Recall@10={float(metrics['Recall@10']):.4f}, "
            f"MRR@10={float(metrics['MRR@10']):.4f}, "
            f"Precision@3={float(metrics['Precision@3']):.4f}, "
            f"duration={float(strategy_summaries[mode]['duration_seconds']):.2f}s"
        )
    print(f"Recommended strategy: {recommended_strategy}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
