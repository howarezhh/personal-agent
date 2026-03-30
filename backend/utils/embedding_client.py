"""Embedding client for remote and local embedding providers."""

from __future__ import annotations

import time
from typing import List, Optional

import torch
import torch.nn.functional as F

try:
    from zhipuai import ZhipuAI
    _ZHIPU_IMPORT_ERROR = None
except Exception as error:
    ZhipuAI = None
    _ZHIPU_IMPORT_ERROR = error

try:
    from transformers import AutoModel, AutoTokenizer
    _TRANSFORMERS_IMPORT_ERROR = None
except Exception as error:
    AutoModel = None
    AutoTokenizer = None
    _TRANSFORMERS_IMPORT_ERROR = error

from backend.core.config_manager import get_config_manager
from backend.utils.logger import get_logger


class EmbeddingClient:
    """统一封装远程与本地 embedding 能力。"""

    DEFAULT_QUERY_INSTRUCTION_FOR_RETRIEVAL = "为这个句子生成表示以用于检索相关文档："

    def __init__(self):
        self.logger = get_logger("embedding_client")
        self.config_manager = get_config_manager()

        self._load_config()
        self._init_client()

        self.logger.info(
            "向量嵌入客户端初始化完成: provider=%s, model=%s, dimension=%s, device=%s",
            self.provider,
            self.model_name,
            self.dimension,
            self.device,
        )

    def _load_config(self):
        """加载 embedding 配置。"""
        embedding_config = self.config_manager.get_model_config("embedding")

        self.provider = str(embedding_config.get("provider", "zhipu") or "zhipu")
        self.model_name = str(embedding_config.get("model_name", "BAAI/bge-small-zh-v1.5") or "BAAI/bge-small-zh-v1.5")
        self.api_key = embedding_config.get("api_key", "")
        self.dimension = int(embedding_config.get("dimension", 512) or 0)
        self.batch_size = int(embedding_config.get("batch_size", 100) or 100)
        self.device = str(embedding_config.get("device", "cpu") or "cpu")
        self.normalize_embeddings = bool(embedding_config.get("normalize_embeddings", True))
        self.local_model_path = str(embedding_config.get("local_model_path") or self.model_name)
        self.local_files_only = bool(embedding_config.get("local_files_only", True))
        self.pooling = str(embedding_config.get("pooling", "cls") or "cls").lower()
        self.max_input_tokens = int(embedding_config.get("max_input_tokens", 512) or 512)
        self.reserved_tokens = int(embedding_config.get("reserved_tokens", 32) or 32)
        # `enable_retrieval_instruction`：是否对检索 query/doc 注入模型推荐指令。
        self.enable_retrieval_instruction = bool(embedding_config.get("enable_retrieval_instruction", True))
        # `query_instruction_for_retrieval`：query 侧 instruction，默认使用 BGE 官方推荐中文模板。
        self.query_instruction_for_retrieval = str(
            embedding_config.get("query_instruction_for_retrieval")
            or self.DEFAULT_QUERY_INSTRUCTION_FOR_RETRIEVAL
        )
        # `document_instruction_for_retrieval`：文档侧 instruction，默认留空避免污染正文语义。
        self.document_instruction_for_retrieval = str(
            embedding_config.get("document_instruction_for_retrieval")
            or ""
        )

        retry_config = self.config_manager.get("model.retry", {})
        self.max_retries = int(retry_config.get("max_retries", 3) or 3)
        self.retry_delay = int(retry_config.get("retry_delay", 1) or 1)
        self.exponential_backoff = bool(retry_config.get("exponential_backoff", True))

        if self.provider == "zhipu" and not self.api_key:
            raise ValueError("未找到向量嵌入模型接口密钥配置")

        if self.pooling not in {"cls", "mean"}:
            self.logger.warning("未知 pooling=%s，已回退为 cls", self.pooling)
            self.pooling = "cls"

    def _init_client(self):
        """按 provider 初始化 embedding 客户端。"""
        if self.provider == "zhipu":
            if ZhipuAI is None:
                raise RuntimeError(
                    "zhipuai is not available. Install it before using provider='zhipu'."
                ) from _ZHIPU_IMPORT_ERROR
            self.client = ZhipuAI(api_key=self.api_key)
            return

        if self.provider in {"local", "transformers_local"}:
            self._init_local_client()
            return

        raise ValueError(f"不支持的向量嵌入提供商: {self.provider}")

    def _init_local_client(self):
        if AutoTokenizer is None or AutoModel is None:
            raise RuntimeError(
                "transformers is not available. Install dependencies for local embeddings first."
            ) from _TRANSFORMERS_IMPORT_ERROR

        if self.device.startswith("cuda") and not torch.cuda.is_available():
            self.logger.warning("配置的 device=%s 不可用，已回退为 cpu", self.device)
            self.device = "cpu"

        try:
            self.tokenizer = AutoTokenizer.from_pretrained(
                self.local_model_path,
                local_files_only=self.local_files_only,
                trust_remote_code=False,
            )
            self.model = AutoModel.from_pretrained(
                self.local_model_path,
                local_files_only=self.local_files_only,
                trust_remote_code=False,
            )
        except Exception as error:
            self.logger.error(
                "本地 embedding 模型加载失败: model_path=%s, local_files_only=%s, error=%s",
                self.local_model_path,
                self.local_files_only,
                error,
            )
            raise

        self.model.to(self.device)
        self.model.eval()
        self.client = self.model

        tokenizer_max_length = int(getattr(self.tokenizer, "model_max_length", 0) or 0)
        if tokenizer_max_length > 0 and tokenizer_max_length < 1000000:
            self.max_input_tokens = min(self.max_input_tokens, tokenizer_max_length)

        if not self.dimension:
            self.dimension = int(getattr(self.model.config, "hidden_size", 0) or 0)

    def embed_text(self, text: str) -> Optional[List[float]]:
        """为单条文本生成向量。"""
        if not text or not text.strip():
            self.logger.warning("提供的文本为空，无法生成向量嵌入")
            return None

        embeddings = self.embed_documents([text])
        result = embeddings[0] if embeddings else None

        if result:
            self.logger.debug(
                "生成向量嵌入成功: dimension=%s, norm=%.6f",
                len(result),
                sum(x * x for x in result) ** 0.5,
            )
        else:
            self.logger.warning("向量嵌入生成失败")

        return result

    def embed_query(self, query: str) -> Optional[List[float]]:
        """为检索 query 生成向量。

        中文说明：
        - BGE 类模型在 query 侧使用 retrieval instruction，通常能显著提升召回精度；
        - 文档向量保持原始正文，不与 query instruction 混用。
        """
        if not query or not query.strip():
            self.logger.warning("提供的 query 为空，无法生成检索向量")
            return None

        embeddings = self._embed_texts_with_mode([query], mode="query")
        return embeddings[0] if embeddings else None

    def embed_documents(self, texts: List[str]) -> List[Optional[List[float]]]:
        """为文档/切块生成向量。"""
        return self._embed_texts_with_mode(texts, mode="document")

    def count_tokens(self, text: str) -> int:
        """统计文本 token 数。

        优先使用底层 tokenizer 的真实切词结果；如果当前 provider 不支持，
        则回退到与历史实现兼容的轻量估算，保证调用方始终有稳定返回值。
        """
        normalized_text = str(text or "").strip()
        if not normalized_text:
            return 0

        if self.provider in {"local", "transformers_local"} and hasattr(self, "tokenizer"):
            try:
                token_ids = self.tokenizer.encode(
                    normalized_text,
                    add_special_tokens=False,
                    truncation=False,
                )
                return len(token_ids)
            except Exception as error:
                self.logger.warning("使用 tokenizer 精确计数 token 失败，回退启发式估算: %s", error)

        # 远程 provider 没暴露 tokenizer 时，优先退到 tiktoken，而不是旧的 len(split)/len//2 粗略估算。
        try:
            import tiktoken

            encoder = tiktoken.get_encoding("cl100k_base")
            return len(encoder.encode(normalized_text, disallowed_special=()))
        except Exception as error:
            self.logger.warning("使用 tiktoken 计数 token 失败，回退启发式估算: %s", error)

        return max(1, len(normalized_text.split())) if " " in normalized_text else max(1, len(normalized_text) // 2)

    def embed_texts(self, texts: List[str]) -> List[Optional[List[float]]]:
        """批量生成文档向量。

        兼容旧调用方；新代码应优先使用 `embed_query` / `embed_documents`。
        """
        return self.embed_documents(texts)

    def _embed_texts_with_mode(self, texts: List[str], *, mode: str) -> List[Optional[List[float]]]:
        """按用途批量生成向量。"""
        if not texts:
            return []

        valid_texts = [(index, text) for index, text in enumerate(texts) if text and text.strip()]
        if not valid_texts:
            self.logger.warning("所有文本都为空")
            return [None] * len(texts)

        all_embeddings: List[Optional[List[float]]] = [None] * len(texts)

        for batch_start in range(0, len(valid_texts), self.batch_size):
            batch_end = min(batch_start + self.batch_size, len(valid_texts))
            batch = valid_texts[batch_start:batch_end]
            batch_indices = [index for index, _ in batch]
            batch_texts = [self._prepare_text_for_embedding(text, mode=mode) for _, text in batch]
            batch_embeddings = self._embed_batch_with_retry(batch_texts)

            for index, embedding in enumerate(batch_embeddings):
                all_embeddings[batch_indices[index]] = embedding

            self.logger.info(
                "生成向量嵌入批次完成: batch=%s, size=%s",
                batch_start // self.batch_size + 1,
                len(batch_texts),
            )

        return all_embeddings

    def _prepare_text_for_embedding(self, text: str, *, mode: str) -> str:
        """根据用途为 embedding 模型准备输入文本。"""
        normalized_text = str(text or "").strip()
        if not normalized_text:
            return ""
        if not self._should_apply_retrieval_instruction():
            return normalized_text

        if mode == "query":
            instruction = self.query_instruction_for_retrieval.strip()
        else:
            instruction = self.document_instruction_for_retrieval.strip()

        if not instruction:
            return normalized_text
        return f"{instruction}{normalized_text}"

    def _should_apply_retrieval_instruction(self) -> bool:
        """判断当前 embedding 模型是否应启用 retrieval instruction。"""
        if not self.enable_retrieval_instruction:
            return False
        normalized_model_name = f"{self.model_name} {self.local_model_path}".lower()
        return "bge" in normalized_model_name

    def _embed_batch_with_retry(self, texts: List[str]) -> List[Optional[List[float]]]:
        """带重试的批量嵌入。"""
        for attempt in range(self.max_retries):
            try:
                return self._embed_batch(texts)
            except Exception as error:
                self.logger.warning(
                    "向量嵌入尝试失败: attempt=%s/%s, error=%s",
                    attempt + 1,
                    self.max_retries,
                    error,
                )

                if attempt < self.max_retries - 1:
                    delay = self.retry_delay * (2 ** attempt) if self.exponential_backoff else self.retry_delay
                    self.logger.info("等待 %s 秒后重试", delay)
                    time.sleep(delay)
                else:
                    self.logger.error("所有向量嵌入尝试均失败: error=%s", error)
                    return [None] * len(texts)

        return [None] * len(texts)

    def _embed_batch(self, texts: List[str]) -> List[List[float]]:
        if self.provider == "zhipu":
            return self._embed_batch_zhipu(texts)
        if self.provider in {"local", "transformers_local"}:
            return self._embed_batch_local(texts)
        raise ValueError(f"不支持的向量嵌入提供商: {self.provider}")

    def _embed_batch_zhipu(self, texts: List[str]) -> List[List[float]]:
        try:
            response = self.client.embeddings.create(model=self.model_name, input=texts)
            return [item.embedding for item in response.data]
        except Exception as error:
            self.logger.error("智谱向量嵌入接口错误: %s", error)
            raise

    def _embed_batch_local(self, texts: List[str]) -> List[List[float]]:
        try:
            encoded = self.tokenizer(
                texts,
                padding=True,
                truncation=True,
                max_length=self.max_input_tokens,
                return_tensors="pt",
            )
            encoded = {key: value.to(self.device) for key, value in encoded.items()}

            with torch.no_grad():
                outputs = self.model(**encoded)

            if self.pooling == "mean":
                attention_mask = encoded["attention_mask"].unsqueeze(-1)
                masked = outputs.last_hidden_state * attention_mask
                summed = masked.sum(dim=1)
                counts = attention_mask.sum(dim=1).clamp(min=1)
                embeddings = summed / counts
            else:
                embeddings = outputs.last_hidden_state[:, 0]

            if self.normalize_embeddings:
                embeddings = F.normalize(embeddings, p=2, dim=1)

            return embeddings.cpu().tolist()
        except Exception as error:
            self.logger.error("本地向量嵌入模型错误: %s", error)
            raise

    def get_dimension(self) -> int:
        return self.dimension

    def get_max_input_tokens(self) -> int:
        return max(1, int(self.max_input_tokens))

    def get_recommended_chunk_token_limit(self) -> int:
        return max(1, self.get_max_input_tokens() - max(0, int(self.reserved_tokens)))

    def __repr__(self) -> str:
        return f"EmbeddingClient(provider='{self.provider}', model='{self.model_name}')"


_embedding_client: Optional[EmbeddingClient] = None


def get_embedding_client() -> EmbeddingClient:
    global _embedding_client
    if _embedding_client is None:
        _embedding_client = EmbeddingClient()
    return _embedding_client
