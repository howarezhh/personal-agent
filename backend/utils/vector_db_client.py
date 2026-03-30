"""Vector database client backed by a single Chroma collection."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, List, Optional

try:
    import chromadb
    from chromadb.config import Settings

    _CHROMADB_IMPORT_ERROR = None
except ModuleNotFoundError as error:
    chromadb = None
    Settings = None
    _CHROMADB_IMPORT_ERROR = error

from backend.core.config_manager import get_config_manager
from backend.agents.retrieval.keyword_retriever import KeywordRetriever
from backend.agents.retrieval.sparse_index_cache import get_sparse_index_cache
from backend.utils.logger import get_logger


EMPTY_QUERY_RESULT: Dict[str, List[List[Any]]] = {
    "ids": [[]],
    "documents": [[]],
    "metadatas": [[]],
    "distances": [[]],
}


class VectorDBClient:
    """Thin wrapper around Chroma used by the knowledge base flow."""

    _instance: Optional["VectorDBClient"] = None

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance

    def __init__(self):
        if hasattr(self, "_initialized"):
            return

        self._initialized = True
        self.logger = get_logger("vector_db_client")
        self.config_manager = get_config_manager()
        self.last_error: Optional[str] = None

        self._load_config()
        self._init_client()

        self.logger.info(
            "Vector DB client initialized: provider=%s, collection=%s",
            self.provider,
            self.collection_name,
        )

    def _get_sparse_index_cache(self):
        """按统一检索配置返回稀疏索引缓存实例。"""
        retrieval_config = self.config_manager.get_agent_config("retrieval")
        return get_sparse_index_cache(
            enabled=bool(retrieval_config.get("sparse_index_cache_enabled", True)),
            ttl_seconds=int(retrieval_config.get("sparse_index_cache_ttl_seconds", 1800) or 1800),
            max_entries=int(retrieval_config.get("sparse_index_cache_max_entries", 64) or 64),
        )

    def _load_corpus_for_scope(self, search_filter: Dict[str, Any]) -> tuple[Dict[str, Any], str]:
        """加载指定作用域下的完整语料，用于入库后的缓存预热。"""
        result = self.get_documents(where=search_filter, include=["documents", "metadatas"])
        ids = result.get("ids", []) if isinstance(result, dict) else []
        documents = result.get("documents", []) if isinstance(result, dict) else []
        metadatas = result.get("metadatas", []) if isinstance(result, dict) else []
        return {
            "ids": list(ids or []),
            "documents": [str(item or "") for item in list(documents or [])],
            "metadatas": [dict(item or {}) for item in list(metadatas or [])],
        }, "vector_store"

    @staticmethod
    def _build_keyword_index(corpus: Dict[str, Any]) -> Dict[str, Any]:
        """用统一关键词检索器构建 BM25 风格索引。"""
        ids = corpus.get("ids", []) or []
        documents = corpus.get("documents", []) or []
        metadatas = corpus.get("metadatas", []) or []
        if not ids or not documents:
            return {}
        return KeywordRetriever().build_index(ids, documents, metadatas)

    def _warm_sparse_indexes_for_metadatas(self, metadatas: Optional[List[Dict[str, Any]]]) -> None:
        """根据文档元数据主动预热相关作用域缓存。"""
        if not metadatas:
            return
        cache = self._get_sparse_index_cache()
        if not getattr(cache, "enabled", False):
            return

        seen_scope_keys: set[str] = set()
        for metadata in metadatas:
            if not isinstance(metadata, dict):
                continue
            user_id = metadata.get("user_id")
            knowledge_base_id = metadata.get("knowledge_base_id")
            candidate_filters = []
            if user_id and knowledge_base_id:
                candidate_filters.append({"user_id": user_id, "knowledge_base_id": knowledge_base_id})
            if user_id:
                candidate_filters.append({"user_id": user_id})
            if knowledge_base_id:
                candidate_filters.append({"knowledge_base_id": knowledge_base_id})

            for search_filter in candidate_filters:
                scope_key = cache.build_scope_key(search_filter, collection_name=self.collection_name)
                if scope_key in seen_scope_keys:
                    continue
                seen_scope_keys.add(scope_key)
                cache.warm_scope(
                    search_filter=search_filter,
                    collection_name=self.collection_name,
                    corpus_loader=self._load_corpus_for_scope,
                    keyword_index_builder=self._build_keyword_index,
                )

    def _load_config(self):
        vector_db_config = self.config_manager.get_database_config("vector_db")
        self.provider = vector_db_config.get("provider", "chroma")

        if self.provider != "chroma":
            raise ValueError(f"Unsupported vector database provider: {self.provider}")

        chroma_config = vector_db_config.get("chroma", {})
        persist_dir = chroma_config.get("persist_directory")
        if not persist_dir:
            from backend.utils.path_utils import find_project_root

            project_root = find_project_root(Path(__file__).parent)
            persist_dir = str(project_root / "data" / "vectors")

        self.persist_directory = persist_dir
        self.collection_name = str(chroma_config.get("collection_name", "knowledge_base") or "knowledge_base")
        self.collection_metadata = {"description": "Knowledge base for RAG"}

    def _init_client(self):
        try:
            if chromadb is None or Settings is None:
                raise RuntimeError(
                    "chromadb is not installed. Install with `pip install chromadb` or `pip install -r requirements.txt`."
                ) from _CHROMADB_IMPORT_ERROR

            persist_path = Path(self.persist_directory)
            persist_path.mkdir(parents=True, exist_ok=True)

            self.client = chromadb.PersistentClient(
                path=str(persist_path),
                settings=Settings(anonymized_telemetry=False, allow_reset=True),
            )
            self.collection = self.client.get_or_create_collection(
                name=self.collection_name,
                metadata=self.collection_metadata,
            )
            self.logger.info("Vector collection initialized: collection=%s", self.collection_name)
        except Exception as error:
            self.last_error = str(error)
            self.logger.error("Failed to initialize vector DB client: %s", error)
            raise

    @staticmethod
    def normalize_where_filter(where: Optional[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
        if where is None:
            return None
        if not isinstance(where, dict) or not where:
            return where
        if any(str(key).startswith("$") for key in where.keys()):
            return where
        if len(where) == 1:
            return where
        return {"$and": [{key: value} for key, value in where.items()]}

    def add_documents(
        self,
        documents: List[str],
        embeddings: List[List[float]],
        metadatas: Optional[List[Dict[str, Any]]] = None,
        ids: Optional[List[str]] = None,
    ) -> bool:
        try:
            self.last_error = None
            sanitized_metadatas = None
            if metadatas is not None:
                sanitized_metadatas = [self._sanitize_metadata_item(item) for item in metadatas]

            if ids is None:
                import uuid

                ids = [str(uuid.uuid4()) for _ in documents]

            embedding_dimension = len(embeddings[0]) if embeddings else 0
            self.logger.info(
                "Writing vectors: collection=%s, documents=%s, embedding_dimension=%s",
                self.collection_name,
                len(documents),
                embedding_dimension,
            )
            self.collection.add(
                documents=documents,
                embeddings=embeddings,
                metadatas=sanitized_metadatas,
                ids=ids,
            )
            self._warm_sparse_indexes_for_metadatas(sanitized_metadatas)
            self.logger.info("Added %s documents to vector collection: collection=%s", len(documents), self.collection_name)
            return True
        except Exception as error:
            self.last_error = str(error)
            self.logger.error("Failed to add documents: collection=%s, error=%s", self.collection_name, error)
            return False

    @staticmethod
    def _sanitize_metadata_item(metadata: Optional[Dict[str, Any]]) -> Dict[str, Any]:
        if not metadata:
            return {}

        sanitized: Dict[str, Any] = {}
        for key, value in metadata.items():
            if value is None:
                continue
            if isinstance(value, (str, bool, int, float)):
                sanitized[key] = value
                continue
            if hasattr(value, "isoformat"):
                sanitized[key] = value.isoformat()
                continue
            if isinstance(value, (dict, list, tuple, set)):
                sanitized[key] = json.dumps(value, ensure_ascii=False, sort_keys=True)
                continue
            sanitized[key] = str(value)

        return sanitized

    def query(
        self,
        query_embeddings: List[List[float]],
        n_results: int = 5,
        where: Optional[Dict[str, Any]] = None,
        where_document: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        try:
            self.last_error = None
            normalized_where = self.normalize_where_filter(where)
            self.logger.info(
                "Starting vector query: collection=%s, n_results=%s, where=%s",
                self.collection_name,
                n_results,
                normalized_where,
            )
            results = self.collection.query(
                query_embeddings=query_embeddings,
                n_results=n_results,
                where=normalized_where,
                where_document=where_document,
                include=["documents", "metadatas", "distances"],
            )
            result_count = len(results.get("ids", [[]])[0]) if results.get("ids") else 0
            self.logger.info(
                "Vector query completed: collection=%s, returned=%s",
                self.collection_name,
                result_count,
            )
            return results
        except Exception as error:
            self.last_error = str(error)
            self.logger.error("Vector query failed: collection=%s, error=%s", self.collection_name, error)
            return dict(EMPTY_QUERY_RESULT)

    def delete_documents(self, ids: Optional[List[str]] = None, where: Optional[Dict[str, Any]] = None) -> bool:
        try:
            self.last_error = None
            cache = self._get_sparse_index_cache()
            impacted = self.get_documents(ids=ids, where=where, include=["metadatas"]) if ids or where else {"metadatas": []}
            impacted_metadatas = impacted.get("metadatas", []) if isinstance(impacted, dict) else []
            normalized_where = self.normalize_where_filter(where)
            self.collection.delete(ids=ids, where=normalized_where)
            cache.invalidate_from_metadatas(metadatas=impacted_metadatas, collection_name=self.collection_name)
            self.logger.info(
                "Deleted vector documents: collection=%s, ids=%s, where=%s",
                self.collection_name,
                len(ids or []),
                normalized_where,
            )
            return True
        except Exception as error:
            self.last_error = str(error)
            self.logger.error("Failed to delete documents: collection=%s, error=%s", self.collection_name, error)
            return False

    def get_documents(
        self,
        ids: Optional[List[str]] = None,
        where: Optional[Dict[str, Any]] = None,
        include: Optional[List[str]] = None,
    ) -> Dict[str, Any]:
        try:
            self.last_error = None
            normalized_where = self.normalize_where_filter(where)
            results = self.collection.get(ids=ids, where=normalized_where, include=include)
            result_count = len(results.get("ids", [])) if isinstance(results, dict) and results.get("ids") else 0
            self.logger.info(
                "Fetched vector documents: collection=%s, ids=%s, returned=%s, where=%s",
                self.collection_name,
                len(ids or []),
                result_count,
                normalized_where,
            )
            return results
        except Exception as error:
            self.last_error = str(error)
            self.logger.error("Failed to fetch documents: collection=%s, error=%s", self.collection_name, error)
            return {"ids": [], "documents": [], "metadatas": []}

    def get_collection_count(self) -> int:
        try:
            return self.collection.count()
        except Exception as error:
            self.last_error = str(error)
            self.logger.error("Failed to get collection count: collection=%s, error=%s", self.collection_name, error)
            return 0

    def update_documents(
        self,
        ids: List[str],
        documents: Optional[List[str]] = None,
        embeddings: Optional[List[List[float]]] = None,
        metadatas: Optional[List[Dict[str, Any]]] = None,
    ) -> bool:
        try:
            self.last_error = None
            cache = self._get_sparse_index_cache()
            if metadatas:
                cache.invalidate_from_metadatas(metadatas=metadatas, collection_name=self.collection_name)
            self.collection.update(ids=ids, documents=documents, embeddings=embeddings, metadatas=metadatas)
            self._warm_sparse_indexes_for_metadatas(metadatas)
            self.logger.info("Updated %s vector documents: collection=%s", len(ids), self.collection_name)
            return True
        except Exception as error:
            self.last_error = str(error)
            self.logger.error("Failed to update documents: collection=%s, error=%s", self.collection_name, error)
            return False

    def reset_collection(self) -> bool:
        cache = self._get_sparse_index_cache()
        try:
            self.last_error = None
            self.client.delete_collection(name=self.collection_name)
        except Exception as error:
            self.logger.warning(
                "Failed to delete existing collection during reset, continuing: collection=%s, error=%s",
                self.collection_name,
                error,
            )

        try:
            self.collection = self.client.get_or_create_collection(
                name=self.collection_name,
                metadata=self.collection_metadata,
            )
            cache.clear()
            self.logger.warning("Vector collection reset: collection=%s", self.collection_name)
            return True
        except Exception as error:
            self.last_error = str(error)
            self.logger.error("Failed to reset collection: collection=%s, error=%s", self.collection_name, error)
            return False

    def get_document_by_id(self, doc_id: str) -> Optional[Dict[str, Any]]:
        try:
            result = self.collection.get(ids=[doc_id], include=["documents", "metadatas", "embeddings"])
            if result and result.get("ids"):
                return {
                    "id": result["ids"][0],
                    "document": result["documents"][0] if result.get("documents") else None,
                    "metadata": result["metadatas"][0] if result.get("metadatas") else None,
                    "embedding": result["embeddings"][0] if result.get("embeddings") else None,
                }
            return None
        except Exception as error:
            self.last_error = str(error)
            self.logger.error(
                "Failed to get document by ID: collection=%s, doc_id=%s, error=%s",
                self.collection_name,
                doc_id,
                error,
            )
            return None

    def search(
        self,
        query: str,
        n_results: int = 5,
        where: Optional[Dict[str, Any]] = None,
        where_document: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        try:
            from backend.utils.embedding_client import get_embedding_client

            self.last_error = None
            self.logger.info(
                "Starting semantic search: query=%s, n_results=%s, collection=%s",
                query[:50],
                n_results,
                self.collection_name,
            )
            embedding_client = get_embedding_client()
            # 中文说明：query 与 document 分开编码，避免把文档向量策略误用于检索 query。
            query_embedding = embedding_client.embed_query(query)
            if query_embedding is None:
                self.last_error = "failed to build query embedding"
                self.logger.error("Failed to build query embedding")
                return dict(EMPTY_QUERY_RESULT)

            results = self.query(
                query_embeddings=[query_embedding],
                n_results=n_results,
                where=where,
                where_document=where_document,
            )
            result_count = len(results.get("ids", [[]])[0]) if results.get("ids") else 0
            self.logger.info("Semantic search completed: query=%s, returned=%s", query[:50], result_count)
            return results
        except Exception as error:
            self.last_error = str(error)
            self.logger.error("Semantic search failed: error=%s", error)
            return dict(EMPTY_QUERY_RESULT)

    def as_langchain_retriever(
        self,
        *,
        n_results: int = 5,
        where: Optional[Dict[str, Any]] = None,
        where_document: Optional[Dict[str, Any]] = None,
    ):
        """Return a LangChain retriever backed by this vector client."""
        from backend.utils.vector_db_retriever import VectorDBRetriever

        return VectorDBRetriever(
            vector_client=self,
            search_kwargs={
                "n_results": n_results,
                "where": where,
                "where_document": where_document,
            },
        )

    def __repr__(self) -> str:
        return f"VectorDBClient(provider='{self.provider}', collection='{self.collection_name}')"


def get_vector_db_client() -> VectorDBClient:
    return VectorDBClient()
