from __future__ import annotations

import argparse
import asyncio
from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime, timezone
import json
import sys
import time
from pathlib import Path
from typing import Any, Iterable, Sequence


PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from backend.database.database_manager import get_database_manager
from backend.file_processors.parsers.parser_registry import get_parser_registry
from backend.utils.embedding_client import get_embedding_client
from evaluation.chunkers import Chunker, ExperimentChunk, FixedWindowChunker, ParagraphChunker
from evaluation.metrics import summarize_metrics


DEFAULT_DATASET_PATH = Path("evaluation/datasets/biyesheji_retrieval_eval_50.json")
DEFAULT_OUTPUT_PATH = Path("evaluation/results/chunking_biyesheji_comparison.json")
DEFAULT_REPORT_PATH = Path("evaluation/results/chunking_biyesheji_comparison.md")


@dataclass(frozen=True)
class SourceDocument:
    document_id: str
    file_name: str
    file_type: str
    storage_path: str


@dataclass(frozen=True)
class ParsedDocument:
    document_id: str
    file_name: str
    text: str
    file_type: str
    storage_path: str


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Chunk strategy comparison for retrieval evaluation.")
    parser.add_argument("--dataset", default=str(DEFAULT_DATASET_PATH), help="Path to the retrieval evaluation dataset.")
    parser.add_argument("--output", default=str(DEFAULT_OUTPUT_PATH), help="Path to write the experiment JSON result.")
    parser.add_argument("--report", default=str(DEFAULT_REPORT_PATH), help="Path to write the Markdown report.")
    parser.add_argument("--fixed-chunk-size", type=int, default=1000)
    parser.add_argument("--fixed-chunk-overlap", type=int, default=100)
    parser.add_argument("--paragraph-chunk-size", type=int, default=1000)
    parser.add_argument("--paragraph-chunk-overlap", type=int, default=100)
    parser.add_argument("--top-k", type=int, default=10, help="Maximum ranked documents kept per query detail output.")
    return parser.parse_args()


def load_dataset(dataset_path: Path) -> dict[str, Any]:
    return json.loads(dataset_path.read_text(encoding="utf-8"))


def load_source_documents(dataset: dict[str, Any]) -> list[SourceDocument]:
    source_documents = dataset.get("source_documents", [])
    document_ids = [item["document_id"] for item in source_documents]
    if not document_ids:
        raise ValueError("Dataset source_documents is empty")

    placeholders = ",".join(["%s"] * len(document_ids))
    query = (
        f"SELECT file_id, original_filename, file_type, storage_path FROM files "
        f"WHERE file_id IN ({placeholders})"
    )
    rows = get_database_manager().execute_query(query, tuple(document_ids))
    row_map = {row["file_id"]: row for row in rows or []}

    missing_ids = [document_id for document_id in document_ids if document_id not in row_map]
    if missing_ids:
        raise ValueError(f"Missing source documents in database: {missing_ids}")

    ordered_documents: list[SourceDocument] = []
    for item in source_documents:
        row = row_map[item["document_id"]]
        ordered_documents.append(
            SourceDocument(
                document_id=row["file_id"],
                file_name=row["original_filename"],
                file_type=str(row["file_type"]),
                storage_path=str(row["storage_path"]),
            )
        )
    return ordered_documents


def _parser_key_for_file_type(file_type: str) -> str:
    normalized = str(file_type or "").lower()
    if normalized == "pdf":
        return "pdf"
    if normalized == "docx":
        return "word"
    if normalized == "xlsx":
        return "excel"
    return "text"


def _load_fallback_text(document_id: str) -> str:
    rows = get_database_manager().execute_query(
        """
        SELECT content
        FROM file_chunks
        WHERE file_id = %s
        ORDER BY chunk_index ASC
        """,
        (document_id,),
    )
    return "\n\n".join(str(row.get("content", "") or "") for row in rows or []).strip()


async def parse_source_documents(source_documents: Sequence[SourceDocument]) -> list[ParsedDocument]:
    parser_registry = get_parser_registry()
    parsed_documents: list[ParsedDocument] = []

    for document in source_documents:
        parser = parser_registry.get(_parser_key_for_file_type(document.file_type))
        if parser is None:
            raise ValueError(f"No parser registered for file type: {document.file_type}")

        parse_result = await parser.safe_parse(document.storage_path)
        if parse_result["success"]:
            parsed_content = parse_result["content"]
            text = str(parsed_content.text or "").strip()
        else:
            text = _load_fallback_text(document.document_id)

        if not text:
            raise ValueError(f"Unable to load text for document {document.document_id}: {document.file_name}")

        parsed_documents.append(
            ParsedDocument(
                document_id=document.document_id,
                file_name=document.file_name,
                text=text,
                file_type=document.file_type,
                storage_path=document.storage_path,
            )
        )

    return parsed_documents


def build_experiment_chunks(documents: Sequence[ParsedDocument], chunker: Chunker) -> list[ExperimentChunk]:
    chunks: list[ExperimentChunk] = []
    for document in documents:
        metadata = {
            "file_name": document.file_name,
            "source": document.file_name,
            "file_type": document.file_type,
            "storage_path": document.storage_path,
        }
        chunks.extend(chunker.split(document.text, document_id=document.document_id, metadata=metadata))
    return chunks


def similarity_score(query_embedding: Sequence[float], chunk_embedding: Sequence[float]) -> float:
    return float(sum(left * right for left, right in zip(query_embedding, chunk_embedding)))


def rank_documents_for_query(
    *,
    query_embedding: Sequence[float],
    chunks: Sequence[ExperimentChunk],
    chunk_embeddings: Sequence[Sequence[float]],
    file_name_by_document_id: dict[str, str],
    top_k: int,
) -> dict[str, Any]:
    doc_scores: dict[str, float] = {}
    doc_best_chunk_ids: dict[str, str] = {}

    for chunk, embedding in zip(chunks, chunk_embeddings):
        score = similarity_score(query_embedding, embedding)
        current_score = doc_scores.get(chunk.document_id)
        if current_score is None or score > current_score:
            doc_scores[chunk.document_id] = score
            doc_best_chunk_ids[chunk.document_id] = chunk.chunk_id

    ranked_items = sorted(doc_scores.items(), key=lambda item: item[1], reverse=True)
    ranked_document_ids = [document_id for document_id, _ in ranked_items]
    top_documents = [
        {
            "document_id": document_id,
            "file_name": file_name_by_document_id.get(document_id, document_id),
            "score": round(score, 6),
            "best_chunk_id": doc_best_chunk_ids.get(document_id),
        }
        for document_id, score in ranked_items[:top_k]
    ]

    return {
        "ranked_document_ids": ranked_document_ids,
        "top_documents": top_documents,
    }


def evaluate_strategy(
    *,
    strategy_name: str,
    chunker: Chunker,
    parsed_documents: Sequence[ParsedDocument],
    dataset: dict[str, Any],
    query_embeddings: Sequence[Sequence[float]],
    top_k: int,
) -> dict[str, Any]:
    strategy_start = time.perf_counter()
    chunks = build_experiment_chunks(parsed_documents, chunker)
    embedding_client = get_embedding_client()
    chunk_embedding_start = time.perf_counter()
    chunk_embeddings = embedding_client.embed_texts([chunk.text for chunk in chunks])
    chunk_embedding_duration = time.perf_counter() - chunk_embedding_start

    invalid_embeddings = [index for index, embedding in enumerate(chunk_embeddings) if embedding is None]
    if invalid_embeddings:
        raise RuntimeError(f"Chunk embeddings failed for strategy {strategy_name}: indexes={invalid_embeddings[:5]}")

    file_name_by_document_id = {document.document_id: document.file_name for document in parsed_documents}
    query_rankings: list[dict[str, Any]] = []
    query_eval_start = time.perf_counter()
    for item, query_embedding in zip(dataset["items"], query_embeddings):
        ranking = rank_documents_for_query(
            query_embedding=query_embedding,
            chunks=chunks,
            chunk_embeddings=chunk_embeddings,
            file_name_by_document_id=file_name_by_document_id,
            top_k=top_k,
        )
        query_rankings.append(
            {
                "query_id": item["query_id"],
                "query": item["query"],
                "relevant_document_ids": item["relevant_document_ids"],
                "ranked_document_ids": ranking["ranked_document_ids"],
                "top_documents": ranking["top_documents"],
            }
        )
    query_eval_duration = time.perf_counter() - query_eval_start
    metrics = summarize_metrics(query_rankings)
    strategy_duration = time.perf_counter() - strategy_start

    chunk_lengths = [len(chunk.text) for chunk in chunks]
    misses_at_1 = [
        {
            "query_id": item["query_id"],
            "query": item["query"],
            "predicted_document_id": (item["ranked_document_ids"] or [None])[0],
            "predicted_file_name": ((item["top_documents"] or [{}])[0]).get("file_name"),
            "relevant_document_ids": item["relevant_document_ids"],
        }
        for item in query_rankings
        if not item["ranked_document_ids"] or item["ranked_document_ids"][0] not in set(item["relevant_document_ids"])
    ]

    return {
        "strategy_name": strategy_name,
        "chunk_config": {
            "chunk_size": chunker.chunk_size,
            "chunk_overlap": chunker.chunk_overlap,
        },
        "chunk_stats": {
            "chunk_count": len(chunks),
            "avg_chunk_length": round(sum(chunk_lengths) / len(chunk_lengths), 2) if chunk_lengths else 0.0,
            "min_chunk_length": min(chunk_lengths) if chunk_lengths else 0,
            "max_chunk_length": max(chunk_lengths) if chunk_lengths else 0,
        },
        "metrics": metrics.to_dict(),
        "timing": {
            "chunk_embedding_seconds": round(chunk_embedding_duration, 4),
            "query_evaluation_seconds": round(query_eval_duration, 4),
            "total_seconds": round(strategy_duration, 4),
        },
        "query_rankings": query_rankings,
        "top1_misses": misses_at_1[:10],
    }


def choose_recommended_strategy(strategy_results: Sequence[dict[str, Any]]) -> dict[str, Any]:
    ranked = sorted(
        strategy_results,
        key=lambda item: (
            float(item["metrics"]["MRR@10"]),
            float(item["metrics"]["HitRate@1"]),
            float(item["metrics"]["Recall@5"]),
            -int(item["chunk_stats"]["chunk_count"]),
        ),
        reverse=True,
    )
    return ranked[0]


def build_markdown_report(result: dict[str, Any]) -> str:
    lines = [
        "# Chunk 策略对比实验",
        "",
        f"- 数据集：`{result['dataset']['dataset_name']}`",
        f"- 知识库：`{result['dataset']['knowledge_base_name']}`",
        f"- 检索模式：`{result['retrieval_mode']}`",
        f"- 文档打分聚合：`{result['document_score_aggregation']}`",
        f"- Embedding 模型：`{result['embedding_model']['model_name']}`",
        "",
        "## 实验结果",
        "",
        "| 策略 | Chunk数 | 平均Chunk长度 | Recall@5 | Recall@10 | MRR@10 | HitRate@1 | HitRate@3 | 总耗时(s) |",
        "| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |",
    ]

    for strategy in result["strategies"]:
        metrics = strategy["metrics"]
        chunk_stats = strategy["chunk_stats"]
        timing = strategy["timing"]
        lines.append(
            f"| {strategy['strategy_name']} | {chunk_stats['chunk_count']} | {chunk_stats['avg_chunk_length']} | "
            f"{metrics['Recall@5']} | {metrics['Recall@10']} | {metrics['MRR@10']} | "
            f"{metrics['HitRate@1']} | {metrics['HitRate@3']} | {timing['total_seconds']} |"
        )

    recommended = result["recommendation"]
    lines.extend(
        [
            "",
            "## 结论",
            "",
            f"- 推荐策略：`{recommended['strategy_name']}`",
            f"- 推荐理由：优先比较 `MRR@10`，若接近则再看 `HitRate@1`、`Recall@5` 和 chunk 总量。",
            "",
            "## 说明",
            "",
            "- 当前实验是离线语义检索评估，直接基于本地 embedding 计算 query 与 chunk 的相似度。",
            "- 文档级排序使用每个文档命中的最高 chunk 相似度作为文档得分。",
            "- 当前评估集仅包含 7 篇制度类文档，因此 `Recall@5` 容易接近上限，更应重点关注 `MRR@10` 和 `HitRate@1`。",
        ]
    )
    return "\n".join(lines) + "\n"


def run_experiment(args: argparse.Namespace) -> dict[str, Any]:
    dataset_path = Path(args.dataset)
    output_path = Path(args.output)
    report_path = Path(args.report)
    dataset = load_dataset(dataset_path)
    source_documents = load_source_documents(dataset)
    parsed_documents = asyncio.run(parse_source_documents(source_documents))

    embedding_client = get_embedding_client()
    query_embeddings = embedding_client.embed_texts([item["query"] for item in dataset["items"]])
    invalid_query_embeddings = [index for index, embedding in enumerate(query_embeddings) if embedding is None]
    if invalid_query_embeddings:
        raise RuntimeError(f"Query embeddings failed: indexes={invalid_query_embeddings[:5]}")

    strategies = [
        FixedWindowChunker(chunk_size=args.fixed_chunk_size, chunk_overlap=args.fixed_chunk_overlap),
        ParagraphChunker(chunk_size=args.paragraph_chunk_size, chunk_overlap=args.paragraph_chunk_overlap),
    ]

    strategy_results = [
        evaluate_strategy(
            strategy_name=strategy.name,
            chunker=strategy,
            parsed_documents=parsed_documents,
            dataset=dataset,
            query_embeddings=query_embeddings,
            top_k=args.top_k,
        )
        for strategy in strategies
    ]

    recommended = choose_recommended_strategy(strategy_results)
    result = {
        "experiment_name": "chunk_strategy_comparison",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "dataset": {
            "path": str(dataset_path),
            "dataset_name": dataset["dataset_name"],
            "knowledge_base_id": dataset["knowledge_base"]["knowledge_base_id"],
            "knowledge_base_name": dataset["knowledge_base"]["knowledge_base_name"],
            "query_count": len(dataset["items"]),
            "source_document_count": len(dataset["source_documents"]),
        },
        "retrieval_mode": "offline_semantic_search",
        "document_score_aggregation": "max_chunk_similarity",
        "embedding_model": {
            "provider": embedding_client.provider,
            "model_name": embedding_client.model_name,
            "dimension": embedding_client.get_dimension(),
            "normalize_embeddings": embedding_client.normalize_embeddings,
        },
        "strategies": strategy_results,
        "recommendation": {
            "strategy_name": recommended["strategy_name"],
            "metrics": recommended["metrics"],
            "chunk_stats": recommended["chunk_stats"],
        },
    }

    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(build_markdown_report(result), encoding="utf-8")
    return result


def main() -> int:
    args = parse_args()
    result = run_experiment(args)
    summary = {
        "recommended_strategy": result["recommendation"]["strategy_name"],
        "strategies": [
            {
                "strategy_name": strategy["strategy_name"],
                **strategy["metrics"],
                **strategy["chunk_stats"],
            }
            for strategy in result["strategies"]
        ],
    }
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
