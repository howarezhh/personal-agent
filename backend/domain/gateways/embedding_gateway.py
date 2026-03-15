
from typing import Protocol, runtime_checkable


@runtime_checkable
class EmbeddingGatewayPort(Protocol):
    def embed_text(self, text: str): ...

