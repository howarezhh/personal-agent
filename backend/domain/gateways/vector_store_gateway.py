
from typing import Any, Protocol, runtime_checkable


@runtime_checkable
class VectorStoreGatewayPort(Protocol):
    def query(self, query_embeddings: list[Any], n_results: int, where: dict[str, Any]): ...

