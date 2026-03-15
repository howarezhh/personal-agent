
from backend.utils.vector_db_client import get_vector_db_client


class VectorStoreGatewayAdapter:
    def __init__(self, client=None):
        self.client = client or get_vector_db_client()

    def query(self, query_embeddings, n_results: int, where: dict):
        return self.client.query(query_embeddings=query_embeddings, n_results=n_results, where=where)
