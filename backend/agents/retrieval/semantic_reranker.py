# -*- coding: utf-8 -*-

from __future__ import annotations

"""
语义重排器模块。

该模块负责把真实的 cross-encoder / reranker 模型能力封装成统一接口，
供检索链路在重排阶段直接复用。当前优先支持本地 BGE 重排模型，
并保留在模型缺失或初始化失败时回退为 None 的能力。
"""

import math
import os
from pathlib import Path
from typing import Any, Optional, Protocol, Sequence

from backend.core.config_manager import get_config_manager
from backend.utils.logger import get_logger
from backend.utils.path_utils import find_project_root


class SemanticRerankerProtocol(Protocol):
    """语义重排器统一协议。"""

    backend_name: str

    def score(self, query: str, passages: Sequence[str]) -> list[float]:
        """为输入 query/passages 生成 0~1 区间的语义相关分。"""


class LocalCrossEncoderReranker:
    """本地 cross-encoder 重排器。

    说明：
    - 优先尝试 ONNX Runtime，以降低 CPU 推理开销；
    - 若 ONNX 不可用，则自动回退到 transformers + torch；
    - 输出分数统一经过 sigmoid 映射到 0~1 区间，便于与启发式特征融合。
    """

    backend_name = "local_cross_encoder"

    def __init__(
        self,
        model_path: str | Path,
        *,
        batch_size: int = 8,
        device: str = "auto",
        local_files_only: bool = True,
    ):
        # `self.logger`：记录模型初始化、回退与打分阶段的关键信息。
        self.logger = get_logger("semantic_reranker")
        # `self.model_path`：本地模型目录，支持相对项目根目录的路径。
        self.model_path = self._resolve_path(model_path)
        # `self.batch_size`：批量推理大小，控制吞吐与显存/内存占用平衡。
        self.batch_size = max(1, int(batch_size))
        # `self.local_files_only`：是否只从本地读取模型文件，避免运行期外网依赖。
        self.local_files_only = bool(local_files_only)
        # `self.score_mode`：记录当前推理后端，便于调试与日志定位。
        self.score_mode = "torch"

        onnx_model_path = self.model_path / "onnx" / "model.onnx"
        if onnx_model_path.exists():
            try:
                self._init_onnx_runtime(onnx_model_path)
                self.logger.info("语义重排器已启用 ONNX 后端: model_path=%s", self.model_path)
                return
            except Exception as error:
                self.logger.warning("ONNX 重排器初始化失败，已回退到 Torch: %s", error)

        self._init_torch_runtime(device)
        self.logger.info("语义重排器已启用 Torch 后端: model_path=%s, device=%s", self.model_path, self.device)

    @staticmethod
    def _resolve_path(path_value: str | Path) -> Path:
        """把相对路径解析到项目根目录。"""
        path = Path(path_value)
        if path.is_absolute():
            return path
        project_root = find_project_root(Path(__file__).parent)
        return project_root / path

    @staticmethod
    def _resolve_device(torch_module, requested_device: str) -> str:
        """解析运行设备，支持 auto/cpu/cuda。"""
        if requested_device != "auto":
            return requested_device
        return "cuda" if torch_module.cuda.is_available() else "cpu"

    def _init_onnx_runtime(self, onnx_model_path: Path) -> None:
        """初始化 ONNX Runtime 推理后端。"""
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
        """初始化 Torch 推理后端。"""
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
        """输出经过 sigmoid 归一化后的语义相关分。"""
        if not passages:
            return []
        raw_scores = self._score_with_onnx(query, passages) if self.score_mode == "onnx" else self._score_with_torch(query, passages)
        return [self._sigmoid(score) for score in raw_scores]

    def _score_with_torch(self, query: str, passages: Sequence[str]) -> list[float]:
        """使用 Torch 执行批量打分。"""
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
        """使用 ONNX Runtime 执行批量打分。"""
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

    @staticmethod
    def _sigmoid(value: float) -> float:
        """把原始 logits 映射到 0~1。"""
        if value >= 0:
            exp_value = math.exp(-value)
            return 1.0 / (1.0 + exp_value)
        exp_value = math.exp(value)
        return exp_value / (1.0 + exp_value)


class CascadedCrossEncoderReranker:
    """低置信度场景下使用二阶段 cross-encoder 精排。

    设计目标：
    - 第一阶段优先使用速度更快的基础重排模型；
    - 当第一阶段分数偏低或头部差距过小，说明结果存在歧义；
    - 仅对头部候选触发第二阶段更强模型，降低整体延迟成本。
    """

    backend_name = "local_cross_encoder_cascade"

    def __init__(
        self,
        primary_reranker: SemanticRerankerProtocol,
        secondary_reranker: SemanticRerankerProtocol,
        *,
        secondary_top_n: int = 8,
        secondary_score_weight: float = 0.75,
        secondary_trigger_min_score: float = 0.72,
        secondary_trigger_score_gap: float = 0.04,
    ):
        # `self.logger`：记录是否触发二阶段精排，便于排查延迟和效果。
        self.logger = get_logger("semantic_reranker_cascade")
        # `self.primary_reranker`：第一阶段快速模型。
        self.primary_reranker = primary_reranker
        # `self.secondary_reranker`：第二阶段高精度模型。
        self.secondary_reranker = secondary_reranker
        # `self.secondary_top_n`：第二阶段最多重排的头部候选数。
        self.secondary_top_n = max(1, int(secondary_top_n))
        # `self.secondary_score_weight`：第二阶段语义分占融合结果的比例。
        self.secondary_score_weight = max(0.0, min(float(secondary_score_weight), 1.0))
        # `self.secondary_trigger_min_score`：第一名分数低于该阈值时升级为高精度精排。
        self.secondary_trigger_min_score = max(0.0, min(float(secondary_trigger_min_score), 1.0))
        # `self.secondary_trigger_score_gap`：前两名分差过小时视为存在歧义。
        self.secondary_trigger_score_gap = max(0.0, min(float(secondary_trigger_score_gap), 1.0))
        self.backend_name = (
            f"{getattr(primary_reranker, 'backend_name', 'primary')}"
            f"+{getattr(secondary_reranker, 'backend_name', 'secondary')}"
        )

    def score(self, query: str, passages: Sequence[str]) -> list[float]:
        """对候选先做快速打分，再在低置信度时升级到高精度打分。"""
        if not passages:
            return []

        primary_scores = [float(score) for score in self.primary_reranker.score(query, passages)]
        if not self._should_use_secondary_rerank(primary_scores):
            return primary_scores

        candidate_indexes = self._select_secondary_candidate_indexes(primary_scores)
        secondary_passages = [passages[index] for index in candidate_indexes]
        secondary_scores = self.secondary_reranker.score(query, secondary_passages)
        fused_scores = list(primary_scores)

        for index, secondary_score in zip(candidate_indexes, secondary_scores):
            primary_score = float(primary_scores[index])
            fused_scores[index] = self._blend_scores(primary_score, float(secondary_score))

        top1_score, score_gap = self._get_top1_and_gap(primary_scores)
        self.logger.info(
            "检索结果低置信度，已触发二阶段精排: top1=%.4f, gap=%.4f, top_n=%s",
            top1_score,
            score_gap,
            len(candidate_indexes),
        )
        return fused_scores

    def _should_use_secondary_rerank(self, primary_scores: Sequence[float]) -> bool:
        """判断是否需要启用更强模型做二阶段精排。"""
        if not primary_scores:
            return False

        top1_score, score_gap = self._get_top1_and_gap(primary_scores)
        # 中文说明：两类情况触发升级。
        # 1. 第一名分数本身偏低，说明整体结果都不够稳；
        # 2. 第一名与第二名几乎打平，说明排序边界模糊。
        return (
            top1_score < self.secondary_trigger_min_score
            or score_gap < self.secondary_trigger_score_gap
        )

    def _select_secondary_candidate_indexes(self, primary_scores: Sequence[float]) -> list[int]:
        """选择需要送入第二阶段高精度模型的头部候选。"""
        sorted_indexes = sorted(
            range(len(primary_scores)),
            key=lambda index: float(primary_scores[index]),
            reverse=True,
        )
        return sorted_indexes[: min(len(sorted_indexes), self.secondary_top_n)]

    def _blend_scores(self, primary_score: float, secondary_score: float) -> float:
        """融合两阶段打分，避免完全替换导致分布突变。"""
        return (
            (1.0 - self.secondary_score_weight) * primary_score
            + self.secondary_score_weight * secondary_score
        )

    @staticmethod
    def _get_top1_and_gap(primary_scores: Sequence[float]) -> tuple[float, float]:
        """提取第一名得分和前两名分差。"""
        ranked_scores = sorted((float(score) for score in primary_scores), reverse=True)
        top1_score = ranked_scores[0] if ranked_scores else 0.0
        top2_score = ranked_scores[1] if len(ranked_scores) > 1 else 0.0
        return top1_score, max(0.0, top1_score - top2_score)


def _build_local_cross_encoder_reranker(
    rerank_model_config: dict[str, Any],
    *,
    model_path: str | Path,
    batch_size_key: str = "batch_size",
    device_key: str = "device",
    local_files_only_key: str = "local_files_only",
) -> LocalCrossEncoderReranker:
    """按统一配置构建本地 cross-encoder 重排器。"""
    return LocalCrossEncoderReranker(
        model_path=model_path,
        batch_size=int(rerank_model_config.get(batch_size_key, rerank_model_config.get("batch_size", 8)) or 8),
        device=str(rerank_model_config.get(device_key, rerank_model_config.get("device", "auto")) or "auto"),
        local_files_only=bool(
            rerank_model_config.get(local_files_only_key, rerank_model_config.get("local_files_only", True))
        ),
    )


def build_semantic_reranker() -> Optional[SemanticRerankerProtocol]:
    """按统一配置构建真实语义重排器。

    返回 None 表示当前环境不启用语义重排，调用方应自动回退到启发式重排。
    """
    logger = get_logger("semantic_reranker_builder")
    config_manager = get_config_manager()
    retrieval_config = config_manager.get_agent_config("retrieval")
    rerank_model_config = config_manager.get_model_config("rerank")

    enable_semantic_rerank = bool(retrieval_config.get("enable_semantic_rerank", True))
    if not enable_semantic_rerank:
        logger.info("语义重排已在检索配置中关闭")
        return None

    provider = str(rerank_model_config.get("provider", "local_cross_encoder") or "local_cross_encoder").lower()
    if provider in {"", "none", "disabled"}:
        logger.info("语义重排 provider=%s，已禁用真实重排模型", provider)
        return None

    if provider not in {"local_cross_encoder", "local", "cross_encoder"}:
        logger.warning("暂不支持的语义重排 provider=%s，已回退为启发式重排", provider)
        return None

    model_path = rerank_model_config.get("local_model_path") or rerank_model_config.get("model_name")
    if not model_path:
        logger.warning("缺少 rerank_model.local_model_path/model_name，已回退为启发式重排")
        return None

    try:
        primary_reranker = _build_local_cross_encoder_reranker(
            rerank_model_config,
            model_path=model_path,
        )
    except Exception as error:
        logger.warning("真实语义重排器初始化失败，已回退为启发式重排: %s", error)
        return None

    enable_secondary_rerank = bool(rerank_model_config.get("enable_secondary_rerank", False))
    secondary_model_path = rerank_model_config.get("secondary_local_model_path")
    if not enable_secondary_rerank or not secondary_model_path:
        return primary_reranker

    try:
        secondary_reranker = _build_local_cross_encoder_reranker(
            rerank_model_config,
            model_path=secondary_model_path,
            batch_size_key="secondary_batch_size",
            device_key="secondary_device",
            local_files_only_key="secondary_local_files_only",
        )
    except Exception as error:
        logger.warning("二阶段高精度重排器初始化失败，已保留基础重排器: %s", error)
        return primary_reranker

    return CascadedCrossEncoderReranker(
        primary_reranker=primary_reranker,
        secondary_reranker=secondary_reranker,
        secondary_top_n=int(rerank_model_config.get("secondary_top_n", 8) or 8),
        secondary_score_weight=float(rerank_model_config.get("secondary_score_weight", 0.75) or 0.75),
        secondary_trigger_min_score=float(rerank_model_config.get("secondary_trigger_min_score", 0.72) or 0.72),
        secondary_trigger_score_gap=float(rerank_model_config.get("secondary_trigger_score_gap", 0.04) or 0.04),
    )


__all__ = [
    "CascadedCrossEncoderReranker",
    "LocalCrossEncoderReranker",
    "SemanticRerankerProtocol",
    "build_semantic_reranker",
]
