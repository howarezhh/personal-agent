"""
嵌入模型客户端
封装智谱AI embedding-2模型，支持批量生成向量
"""

from typing import List, Optional
import time
from zhipuai import ZhipuAI

from backend.core.config_manager import get_config_manager
from backend.utils.logger import get_logger


class EmbeddingClient:
    """
    嵌入模型客户端

    功能：
    1. 封装智谱AI embedding-2模型
    2. 批量生成向量
    3. 错误处理和重试
    4. 从ConfigManager读取配置
    """

    def __init__(self):
        """初始化嵌入模型客户端"""
        self.logger = get_logger("embedding_client")
        self.config_manager = get_config_manager()

        # 加载配置
        self._load_config()

        # 初始化客户端
        self._init_client()

        self.logger.info(f"向量嵌入客户端初始化完成: 模型={self.model_name}")

    def _load_config(self):
        """加载嵌入模型配置"""
        embedding_config = self.config_manager.get_model_config("embedding")

        self.provider = embedding_config.get("provider", "zhipu")
        self.model_name = embedding_config.get("model_name", "embedding-2")
        self.api_key = embedding_config.get("api_key", "")
        self.dimension = embedding_config.get("dimension", 1024)
        self.batch_size = embedding_config.get("batch_size", 100)

        # 重试配置
        retry_config = self.config_manager.get("model.retry", {})
        self.max_retries = retry_config.get("max_retries", 3)
        self.retry_delay = retry_config.get("retry_delay", 1)
        self.exponential_backoff = retry_config.get("exponential_backoff", True)

        if not self.api_key:
            raise ValueError("未找到向量嵌入模型接口密钥配置")

    def _init_client(self):
        """初始化API客户端"""
        if self.provider == "zhipu":
            self.client = ZhipuAI(api_key=self.api_key)
        else:
            raise ValueError(f"不支持的向量嵌入提供商: {self.provider}")

    def embed_text(self, text: str) -> Optional[List[float]]:
        """
        为单个文本生成向量嵌入

        Args:
            text: 输入文本

        Returns:
            向量嵌入列表，失败返回None
        """
        if not text or not text.strip():
            self.logger.warning("提供的文本为空，无法生成向量嵌入")
            return None

        embeddings = self.embed_texts([text])
        result = embeddings[0] if embeddings else None

        # 添加向量信息日志
        if result:
            self.logger.debug(f"生成向量嵌入成功: 维度={len(result)}, 范数={sum(x*x for x in result)**0.5:.6f}")
        else:
            self.logger.warning("向量嵌入生成失败")

        return result

    def embed_texts(self, texts: List[str]) -> List[Optional[List[float]]]:
        """
        批量生成向量嵌入

        Args:
            texts: 文本列表

        Returns:
            向量嵌入列表，每个元素对应一个文本的向量
        """
        if not texts:
            return []

        # 过滤空文本
        valid_texts = [(i, text) for i, text in enumerate(texts) if text and text.strip()]
        if not valid_texts:
            self.logger.warning("所有文本都为空")
            return [None] * len(texts)

        # 分批处理
        all_embeddings = [None] * len(texts)

        for batch_start in range(0, len(valid_texts), self.batch_size):
            batch_end = min(batch_start + self.batch_size, len(valid_texts))
            batch = valid_texts[batch_start:batch_end]

            batch_indices = [idx for idx, _ in batch]
            batch_texts = [text for _, text in batch]

            # 生成嵌入
            batch_embeddings = self._embed_batch_with_retry(batch_texts)

            # 将结果放回原位置
            for i, embedding in enumerate(batch_embeddings):
                original_idx = batch_indices[i]
                all_embeddings[original_idx] = embedding

            self.logger.info(f"生成向量嵌入批次 {batch_start // self.batch_size + 1}")

        return all_embeddings

    def _embed_batch_with_retry(self, texts: List[str]) -> List[Optional[List[float]]]:
        """
        带重试的批量嵌入生成

        Args:
            texts: 文本列表

        Returns:
            向量嵌入列表
        """
        for attempt in range(self.max_retries):
            try:
                return self._embed_batch(texts)

            except Exception as e:
                self.logger.warning(
                    f"向量嵌入尝试 {attempt + 1}/{self.max_retries} 失败: {e}"
                )

                if attempt < self.max_retries - 1:
                    # 计算延迟时间
                    if self.exponential_backoff:
                        delay = self.retry_delay * (2 ** attempt)
                    else:
                        delay = self.retry_delay

                    self.logger.info(f"等待 {delay} 秒后重试...")
                    time.sleep(delay)
                else:
                    self.logger.error(f"所有向量嵌入尝试都失败: {e}")
                    return [None] * len(texts)

        return [None] * len(texts)

    def _embed_batch(self, texts: List[str]) -> List[List[float]]:
        """
        实际执行批量嵌入生成

        Args:
            texts: 文本列表

        Returns:
            向量嵌入列表
        """
        if self.provider == "zhipu":
            return self._embed_batch_zhipu(texts)
        else:
            raise ValueError(f"不支持的向量嵌入提供商: {self.provider}")

    def _embed_batch_zhipu(self, texts: List[str]) -> List[List[float]]:
        """
        使用智谱AI生成嵌入

        Args:
            texts: 文本列表

        Returns:
            向量嵌入列表
        """
        try:
            response = self.client.embeddings.create(
                model=self.model_name,
                input=texts
            )

            # 提取嵌入向量
            embeddings = []
            for item in response.data:
                embeddings.append(item.embedding)

            return embeddings

        except Exception as e:
            self.logger.error(f"智谱向量嵌入接口错误: {e}")
            raise

    def get_dimension(self) -> int:
        """
        获取向量维度

        Returns:
            向量维度
        """
        return self.dimension

    def __repr__(self) -> str:
        return f"EmbeddingClient(provider='{self.provider}', model='{self.model_name}')"


# 全局实例（单例模式）
_embedding_client: Optional[EmbeddingClient] = None


def get_embedding_client() -> EmbeddingClient:
    """
    获取嵌入模型客户端实例（单例）

    Returns:
        EmbeddingClient实例
    """
    global _embedding_client
    if _embedding_client is None:
        _embedding_client = EmbeddingClient()
    return _embedding_client
