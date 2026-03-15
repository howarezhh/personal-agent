"""Offline rerank evaluation pipeline."""

from __future__ import annotations

import argparse
import json
import os
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Sequence

from backend.agents.retrieval.reranker import Reranker
from backend.utils.vector_db_client import get_vector_db_client
from evaluation.metrics import aggregate_metrics, evaluate_ranked_documents


DEFAULT_DATASET_PATH = Path("evaluation/datasets/biyesheji_retrieval_eval_50.json")
DEFAULT_OUTPUT_PATH = Path("evaluation/results/biyesheji_retrieval_rerank_compare.json")
DEFAULT_LOCAL_RERANK_MODEL_PATH = Path("models/bge-reranker-base")


@dataclass(frozen=True)
class ExperimentSpec:
    name: str
    candidate_top_n: int
    final_top_k: int
    rerank_enabled: bool


def _project_root() -> Path:
    return Path(__file__).resolve().parents[1]


def _resolve_path(path_value: str | Path) -> Path:
    path = Path(path_value)
    if path.is_absolute():
        return path
    return _project_root() / path


def load_dataset(dataset_path: str | Path) -> dict[str, Any]:
    resolved_path = _resolve_path(dataset_path)
    with resolved_path.open("r", encoding="utf-8") as file:
        return json.load(file)


def collapse_chunk_results_to_documents(
    chunk_results: Sequence[dict[str, Any]],
    *,
    score_key: str,
    top_k: int,
) -> list[dict[str, Any]]:
    best_by_document: dict[str, dict[str, Any]] = {}

    for position, chunk_result in enumerate(chunk_results, start=1):
        document_id = str(chunk_result.get("document_id") or "")
        if not document_id:
            continue

        score = float(chunk_result.get(score_key, 0.0) or 0.0)
        existing = best_by_document.get(document_id)
        candidate = {
            **chunk_result,
            "document_id": document_id,
            "candidate_rank": position,
            "selected_score": score,
        }

        if existing is None:
            best_by_document[document_id] = candidate
            continue

        existing_score = float(existing.get("selected_score", 0.0) or 0.0)
        existing_rank = int(existing.get("candidate_rank", position))
        if score > existing_score or (score == existing_score and position < existing_rank):
            best_by_document[document_id] = candidate

    ranked_documents = sorted(
        best_by_document.values(),
        key=lambda item: (
            -float(item.get("selected_score", 0.0) or 0.0),
            int(item.get("candidate_rank", 0) or 0),
        ),
    )
    return ranked_documents[:top_k]


class LocalCrossEncoderReranker:
    backend_name = "local_cross_encoder"

    def __init__(
        self,
        model_path: str | Path,
        *,
        batch_size: int = 8,
        device: str = "auto",
        local_files_only: bool = True,
    ):
        self.model_path = _resolve_path(model_path)
        self.batch_size = batch_size
        self.local_files_only = local_files_only
        self.score_mode = "torch"

        onnx_model_path = self.model_path / "onnx" / "model.onnx"
        if onnx_model_path.exists():
            try:
                self._init_onnx_runtime(onnx_model_path)
                return
            except Exception:
                pass

        self._init_torch_runtime(device)

    @staticmethod
    def _resolve_device(torch_module, requested_device: str) -> str:
        if requested_device != "auto":
            return requested_device
        return "cuda" if torch_module.cuda.is_available() else "cpu"

    def _init_onnx_runtime(self, onnx_model_path: Path) -> None:
        import numpy as np
        import onnxruntime as ort
        from transformers import AutoTokenizer

        self._np = np
        self.backend_name = "local_cross_encoder_onnx"
        self.score_mode = "onnx"
        self.device = "cpu"
        self.tokenizer = AutoTokenizer.from_pretrained(
            str(self.model_path),
            local_files_only=self.local_files_only,
        )

        session_options = ort.SessionOptions()
        session_options.graph_optimization_level = ort.GraphOptimizationLevel.ORT_ENABLE_ALL
        session_options.intra_op_num_threads = max(1, min(8, os.cpu_count() or 1))
        session_options.inter_op_num_threads = 1
        self.session = ort.InferenceSession(
            str(onnx_model_path),
            sess_options=session_options,
            providers=["CPUExecutionProvider"],
        )
        self.session_input_names = [item.name for item in self.session.get_inputs()]

    def _init_torch_runtime(self, device: str) -> None:
        import torch
        from transformers import AutoModelForSequenceClassification, AutoTokenizer

        self._torch = torch
        self.backend_name = "local_cross_encoder_torch"
        self.score_mode = "torch"
        self.device = self._resolve_device(torch, device)
        self.tokenizer = AutoTokenizer.from_pretrained(
            str(self.model_path),
            local_files_only=self.local_files_only,
        )
        self.model = AutoModelForSequenceClassification.from_pretrained(
            str(self.model_path),
            local_files_only=self.local_files_only,
        )
        self.model.to(self.device)
        self.model.eval()

    def score(self, query: str, passages: Sequence[str]) -> list[float]:
        if not passages:
            return []

        if self.score_mode == "onnx":
            return self._score_with_onnx(query, passages)
        return self._score_with_torch(query, passages)

    def _score_with_torch(self, query: str, passages: Sequence[str]) -> list[float]:
        scores: list[float] = []
        for start in range(0, len(passages), self.batch_size):
            batch_passages = list(passages[start:start + self.batch_size])
            encoded = self.tokenizer(
                [query] * len(batch_passages),
                batch_passages,
                padding=True,
                truncation=True,
                max_length=512,
                return_tensors="pt",
            )
            encoded = {key: value.to(self.device) for key, value in encoded.items()}
            with self._torch.no_grad():
                logits = self.model(**encoded).logits.view(-1)
            scores.extend(float(value) for value in logits.detach().cpu().tolist())
        return scores

    def _score_with_onnx(self, query: str, passages: Sequence[str]) -> list[float]:
        scores: list[float] = []
        for start in range(0, len(passages), self.batch_size):
            batch_passages = list(passages[start:start + self.batch_size])
            encoded = self.tokenizer(
                [query] * len(batch_passages),
                batch_passages,
                padding=True,
                truncation=True,
                max_length=512,
                return_tensors="np",
            )
            feed = {}
            for input_name in self.session_input_names:
                value = encoded[input_name]
                if value.dtype != self._np.int64:
                    value = value.astype(self._np.int64)
                feed[input_name] = value
            logits = self.session.run(None, feed)[0].reshape(-1)
            scores.extend(float(value) for value in logits.tolist())
        return scores


class HeuristicRerankAdapter:
    backend_name = "heuristic_reranker"

    def __init__(self):
        self.reranker = Reranker(enable_rerank=True)

    def score(self, query: str, passages: Sequence[str]) -> list[float]:
        if not passages:
            return []

        synthetic_results = [
            {
                "id": f"candidate-{index}",
                "content": passage,
                "score": 0.0,
                "metadata": {},
            }
            for index, passage in enumerate(passages)
        ]
        reranked = self.reranker.rerank(synthetic_results, query=query, top_k=len(synthetic_results))
        score_map = {
            item["id"]: float(item.get("rerank_score", item.get("score", 0.0)) or 0.0)
            for item in reranked
        }
        return [score_map.get(f"candidate-{index}", 0.0) for index in range(len(passages))]


def build_reranker(
    *,
    backend: str,
    model_path: str | Path,
    batch_size: int,
    device: str,
):
    selected_backend = (backend or "auto").lower()
    resolved_model_path = _resolve_path(model_path)

    if selected_backend == "heuristic":
        return HeuristicRerankAdapter()

    if selected_backend == "auto" and not resolved_model_path.exists():
        return HeuristicRerankAdapter()

    return LocalCrossEncoderReranker(
        model_path=resolved_model_path,
        batch_size=batch_size,
        device=device,
    )


class OfflineRerankEvaluator:
    def __init__(
        self,
        dataset: dict[str, Any],
        *,
        vector_client=None,
        reranker=None,
        knowledge_base_id: str | None = None,
    ):
        self.dataset = dataset
        self.vector_client = vector_client or get_vector_db_client()
        self.reranker = reranker
        self.knowledge_base_id = knowledge_base_id or str(dataset.get("knowledge_base", {}).get("knowledge_base_id") or "")

    def run(self, experiment_specs: Sequence[ExperimentSpec]) -> dict[str, Any]:
        self._warm_up(experiment_specs)
        experiments = [self._run_single_experiment(spec) for spec in experiment_specs]
        summary = self._build_summary(experiments)

        return {
            "experiment_name": "biyesheji_rerank_comparison",
            "generated_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
            "dataset": {
                "dataset_name": self.dataset.get("dataset_name"),
                "dataset_path": str(DEFAULT_DATASET_PATH),
                "knowledge_base_id": self.knowledge_base_id,
                "knowledge_base_name": self.dataset.get("knowledge_base", {}).get("knowledge_base_name"),
                "query_count": len(self.dataset.get("items", []) or []),
                "source_document_count": len(self.dataset.get("source_documents", []) or []),
                "knowledge_base_chunk_count": self._knowledge_base_chunk_count(),
            },
            "repo_scan": {
                "current_retrieval_flow": "retrieval_agent 走 exact phrase / keyword / vector 聚合，接口级 search_knowledge 走向量检索",
                "topk_topn_controls": [
                    "backend/agents/retrieval/retrieval_agent.py:50",
                    "backend/agents/retrieval/retrieval_agent.py:53",
                    "backend/application/services/knowledge_base_application_service.py:126",
                ],
                "rerank_related_files": [
                    "backend/agents/retrieval/reranker.py",
                    "models/bge-reranker-base/config.json",
                ],
                "config_loading_files": [
                    "backend/core/config_manager.py:107",
                    "config/base/model.yaml:1",
                ],
                "evaluation_scope": "本次实验仅比较 no_rerank 与 rerank_topN，不引入 query rewrite / hybrid 扩展 / chunk 改造",
            },
            "experiments": experiments,
            "summary": summary,
        }

    def _warm_up(self, experiment_specs: Sequence[ExperimentSpec]) -> None:
        items = self.dataset.get("items", []) or []
        if not items:
            return

        first_query = str(items[0].get("query") or "")
        if not first_query:
            return

        max_candidate_top_n = max((spec.candidate_top_n for spec in experiment_specs), default=10)
        warmup_chunks = self._retrieve_candidate_chunks(first_query, max_candidate_top_n)
        if not any(spec.rerank_enabled for spec in experiment_specs):
            return
        if self.reranker is None or not warmup_chunks:
            return

        sample_passages = [item.get("content", "") for item in warmup_chunks[: min(len(warmup_chunks), 4)]]
        if sample_passages:
            self.reranker.score(first_query, sample_passages)

    def _knowledge_base_chunk_count(self) -> int:
        try:
            raw = self.vector_client.collection.get(where={"knowledge_base_id": self.knowledge_base_id}, include=[])
        except Exception:
            return 0
        return len(raw.get("ids") or [])

    def _run_single_experiment(self, spec: ExperimentSpec) -> dict[str, Any]:
        rows: list[dict[str, Any]] = []
        total_start = time.perf_counter()
        retrieval_seconds = 0.0
        rerank_seconds = 0.0

        for item in self.dataset.get("items", []) or []:
            query = str(item.get("query") or "")
            relevant_document_ids = [str(value) for value in item.get("relevant_document_ids", []) or []]

            retrieval_started = time.perf_counter()
            candidate_chunks = self._retrieve_candidate_chunks(query, spec.candidate_top_n)
            retrieval_seconds += time.perf_counter() - retrieval_started

            ranked_chunks = candidate_chunks
            score_key = "score"
            if spec.rerank_enabled:
                rerank_started = time.perf_counter()
                rerank_scores = self.reranker.score(query, [item.get("content", "") for item in candidate_chunks])
                rerank_seconds += time.perf_counter() - rerank_started

                ranked_chunks = []
                for chunk_result, rerank_score in zip(candidate_chunks, rerank_scores):
                    ranked_chunks.append({
                        **chunk_result,
                        "rerank_score": float(rerank_score),
                    })
                ranked_chunks = sorted(
                    ranked_chunks,
                    key=lambda chunk: (
                        -float(chunk.get("rerank_score", 0.0) or 0.0),
                        -float(chunk.get("score", 0.0) or 0.0),
                    ),
                )
                score_key = "rerank_score"

            ranked_documents = collapse_chunk_results_to_documents(
                ranked_chunks,
                score_key=score_key,
                top_k=spec.final_top_k,
            )
            ranked_document_ids = [document["document_id"] for document in ranked_documents]
            metrics = evaluate_ranked_documents(ranked_document_ids, relevant_document_ids)

            rows.append(
                {
                    "query_id": item.get("query_id"),
                    "query": query,
                    "relevant_document_ids": relevant_document_ids,
                    "candidate_chunk_count": len(candidate_chunks),
                    "ranked_document_ids": ranked_document_ids,
                    "ranked_documents": [
                        {
                            "document_id": document.get("document_id"),
                            "chunk_id": document.get("chunk_id"),
                            "source": document.get("metadata", {}).get("file_name")
                            or document.get("metadata", {}).get("original_filename")
                            or document.get("metadata", {}).get("source"),
                            "vector_score": float(document.get("score", 0.0) or 0.0),
                            "rerank_score": float(document.get("rerank_score", 0.0) or 0.0)
                            if spec.rerank_enabled
                            else None,
                        }
                        for document in ranked_documents
                    ],
                    "metrics": metrics,
                }
            )

        total_seconds = time.perf_counter() - total_start
        aggregated_metrics = aggregate_metrics([row["metrics"] for row in rows])
        query_count = int(aggregated_metrics.get("query_count", 0) or 0)
        return {
            "name": spec.name,
            "mode": "rerank" if spec.rerank_enabled else "baseline",
            "candidate_top_n": spec.candidate_top_n,
            "final_top_k": spec.final_top_k,
            "rerank_enabled": spec.rerank_enabled,
            "rerank_backend": getattr(self.reranker, "backend_name", None) if spec.rerank_enabled else None,
            "metrics": aggregated_metrics,
            "timings": {
                "total_seconds": total_seconds,
                "retrieval_seconds": retrieval_seconds,
                "rerank_seconds": rerank_seconds,
                "avg_query_seconds": total_seconds / query_count if query_count else 0.0,
            },
            "rows": rows,
        }

    def _retrieve_candidate_chunks(self, query: str, candidate_top_n: int) -> list[dict[str, Any]]:
        raw_results = self.vector_client.search(
            query=query,
            n_results=candidate_top_n,
            where={"knowledge_base_id": self.knowledge_base_id},
        )

        ids = (raw_results.get("ids") or [[]])[0] if raw_results.get("ids") else []
        documents = (raw_results.get("documents") or [[]])[0] if raw_results.get("documents") else []
        distances = (raw_results.get("distances") or [[]])[0] if raw_results.get("distances") else []
        metadatas = (raw_results.get("metadatas") or [[]])[0] if raw_results.get("metadatas") else []

        chunk_results: list[dict[str, Any]] = []
        for index, chunk_id in enumerate(ids):
            metadata = metadatas[index] if index < len(metadatas) and isinstance(metadatas[index], dict) else {}
            document_id = str(metadata.get("document_id") or metadata.get("file_id") or "")
            if not document_id:
                continue

            distance = float(distances[index] if index < len(distances) else 1.0)
            chunk_results.append(
                {
                    "chunk_id": str(chunk_id),
                    "document_id": document_id,
                    "content": documents[index] if index < len(documents) else "",
                    "score": 1.0 / (1.0 + distance),
                    "distance": distance,
                    "metadata": metadata,
                }
            )
        return chunk_results

    @staticmethod
    def _build_summary(experiments: Sequence[dict[str, Any]]) -> dict[str, Any]:
        baseline = next((experiment for experiment in experiments if experiment.get("name") == "no_rerank"), None)
        ranked = sorted(
            experiments,
            key=lambda experiment: (
                -float(experiment.get("metrics", {}).get("mrr@10", 0.0) or 0.0),
                -float(experiment.get("metrics", {}).get("precision@3", 0.0) or 0.0),
                float(experiment.get("timings", {}).get("total_seconds", 0.0) or 0.0),
            ),
        )
        best = ranked[0] if ranked else None
        recommended = best.get("name") if best else None

        observations: list[str] = []
        if baseline and best:
            baseline_metrics = baseline.get("metrics", {})
            best_metrics = best.get("metrics", {})
            baseline_timing = float(baseline.get("timings", {}).get("total_seconds", 0.0) or 0.0)
            best_timing = float(best.get("timings", {}).get("total_seconds", 0.0) or 0.0)
            observations.append(
                "top1 命中率变化: "
                f"{baseline_metrics.get('hit@1', 0.0):.4f} -> {best_metrics.get('hit@1', 0.0):.4f}"
            )
            observations.append(
                "top3 命中率变化: "
                f"{baseline_metrics.get('hit@3', 0.0):.4f} -> {best_metrics.get('hit@3', 0.0):.4f}"
            )
            observations.append(
                "时延变化: "
                f"{baseline_timing:.4f}s -> {best_timing:.4f}s"
            )

        return {
            "recommended_experiment": recommended,
            "best_by_mrr@10": recommended,
            "observations": observations,
        }


def build_experiment_specs(candidate_top_ns: Sequence[int], final_top_k: int) -> list[ExperimentSpec]:
    ordered_top_ns = []
    seen_top_ns: set[int] = set()
    for top_n in candidate_top_ns:
        top_n_value = int(top_n)
        if top_n_value <= 0 or top_n_value in seen_top_ns:
            continue
        seen_top_ns.add(top_n_value)
        ordered_top_ns.append(top_n_value)

    specs = [ExperimentSpec(name="no_rerank", candidate_top_n=final_top_k, final_top_k=final_top_k, rerank_enabled=False)]
    for top_n in ordered_top_ns:
        specs.append(
            ExperimentSpec(
                name=f"rerank_top{top_n}",
                candidate_top_n=max(top_n, final_top_k),
                final_top_k=final_top_k,
                rerank_enabled=True,
            )
        )
    return specs


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run offline retrieval rerank comparison.")
    parser.add_argument("--dataset", default=str(DEFAULT_DATASET_PATH), help="评估集 JSON 路径")
    parser.add_argument("--output", default=str(DEFAULT_OUTPUT_PATH), help="结果输出 JSON 路径")
    parser.add_argument("--knowledge-base-id", default=None, help="可选覆盖评估集里的 knowledge_base_id")
    parser.add_argument("--top-k", type=int, default=10, help="最终输出文档 topK")
    parser.add_argument(
        "--candidate-topns",
        type=int,
        nargs="+",
        default=[20, 50],
        help="rerank 候选规模列表，例如 20 50",
    )
    parser.add_argument(
        "--rerank-backend",
        choices=["auto", "cross_encoder", "heuristic"],
        default="auto",
        help="精排后端；auto 优先本地 cross_encoder，缺失时回退 heuristic",
    )
    parser.add_argument(
        "--rerank-model-path",
        default=str(DEFAULT_LOCAL_RERANK_MODEL_PATH),
        help="本地 rerank 模型目录",
    )
    parser.add_argument("--rerank-batch-size", type=int, default=8, help="cross encoder 批大小")
    parser.add_argument("--device", default="auto", help="cross encoder 设备，默认 auto")
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(argv)
    dataset = load_dataset(args.dataset)
    reranker = build_reranker(
        backend=args.rerank_backend,
        model_path=args.rerank_model_path,
        batch_size=args.rerank_batch_size,
        device=args.device,
    )

    evaluator = OfflineRerankEvaluator(
        dataset,
        reranker=reranker,
        knowledge_base_id=args.knowledge_base_id,
    )
    result = evaluator.run(build_experiment_specs(args.candidate_topns, args.top_k))

    output_path = _resolve_path(args.output)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")

    print(json.dumps({
        "output": str(output_path),
        "experiments": [
            {
                "name": experiment["name"],
                "metrics": experiment["metrics"],
                "timings": experiment["timings"],
            }
            for experiment in result["experiments"]
        ],
        "summary": result["summary"],
    }, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
