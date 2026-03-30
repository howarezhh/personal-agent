
from backend.utils.vector_db_client import get_vector_db_client


class VectorStoreGatewayAdapter:
    """向量库网关适配器，避免应用层直接依赖底层客户端。"""

    def __init__(self, client=None):
        # 延迟初始化底层客户端，避免只做列表/状态查询时也提前拉起向量库。
        self._client = client

    @property
    def client(self):
        if self._client is None:
            self._client = get_vector_db_client()
        return self._client

    def query(self, query_embeddings, n_results: int, where: dict):
        return self.client.query(query_embeddings=query_embeddings, n_results=n_results, where=where)

    def delete_documents(self, **kwargs):
        return self.client.delete_documents(**kwargs)

    def add_documents(self, **kwargs):
        return self.client.add_documents(**kwargs)

    def reset_collection(self):
        return self.client.reset_collection()

    @property
    def last_error(self):
        return getattr(self.client, "last_error", None)
