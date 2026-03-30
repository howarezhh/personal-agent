"""LangChain retriever adapter for the project's vector database client."""

from __future__ import annotations

import asyncio
from typing import Any, Dict, List, Optional

from langchain_core.documents import Document
from langchain_core.retrievers import BaseRetriever
from pydantic import ConfigDict, Field


def _flatten_collection_values(values: Any) -> List[Any]:
    if not isinstance(values, list):
        return []
    if values and isinstance(values[0], list):
        return list(values[0])
    return list(values)


class VectorDBRetriever(BaseRetriever):
    """Expose `VectorDBClient` through LangChain's retriever interface."""

    model_config = ConfigDict(arbitrary_types_allowed=True)

    vector_client: Any
    search_kwargs: Dict[str, Any] = Field(default_factory=dict)

    def _get_relevant_documents(self, query: str) -> List[Document]:
        kwargs = dict(self.search_kwargs)
        n_results = int(kwargs.pop("n_results", kwargs.pop("k", 5)) or 5)
        where = kwargs.pop("where", None)
        where_document = kwargs.pop("where_document", None)
        search_results = self.vector_client.search(
            query=query,
            n_results=n_results,
            where=where,
            where_document=where_document,
        )
        if not isinstance(search_results, dict) or "ids" not in search_results:
            return []

        ids = _flatten_collection_values(search_results.get("ids", []))
        documents = _flatten_collection_values(search_results.get("documents", []))
        distances = _flatten_collection_values(search_results.get("distances", []))
        metadatas = _flatten_collection_values(search_results.get("metadatas", []))

        retrieved_documents: List[Document] = []
        for index, document_id in enumerate(ids):
            metadata = dict(metadatas[index] if index < len(metadatas) else {})
            metadata.setdefault("document_id", document_id)
            if index < len(distances):
                metadata.setdefault("distance", distances[index])
            retrieved_documents.append(
                Document(
                    page_content=str(documents[index] if index < len(documents) else ""),
                    metadata=metadata,
                )
            )
        return retrieved_documents

    async def _aget_relevant_documents(self, query: str) -> List[Document]:
        return await asyncio.to_thread(self._get_relevant_documents, query)


__all__ = ["VectorDBRetriever"]
