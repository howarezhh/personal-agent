
from backend.utils.embedding_client import get_embedding_client


class EmbeddingGatewayAdapter:
    def __init__(self, client=None):
        self.client = client or get_embedding_client()

    def embed_text(self, text: str):
        return self.client.embed_text(text)

