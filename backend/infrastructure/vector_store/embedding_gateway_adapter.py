
from backend.utils.embedding_client import get_embedding_client


class EmbeddingGatewayAdapter:
    """Embedding 网关适配器，供应用层通过统一入口调用。"""

    def __init__(self, client=None):
        # 延迟初始化 embedding 客户端，避免无关接口首屏触发模型加载。
        self._client = client

    @property
    def client(self):
        if self._client is None:
            self._client = get_embedding_client()
        return self._client

    def embed_text(self, text: str):
        return self.client.embed_text(text)

    def embed_texts(self, texts: list[str]):
        return self.client.embed_texts(texts)

    def get_dimension(self) -> int:
        return self.client.get_dimension()

    @property
    def model_name(self) -> str:
        return getattr(self.client, "model_name", "")

    @property
    def last_error(self):
        return getattr(self.client, "last_error", None)

