"""
向量数据库客户端
封装Chroma向量数据库操作，支持文档添加、查询、删除
"""

from typing import List, Dict, Any, Optional
from pathlib import Path

try:
    import chromadb
    from chromadb.config import Settings
    _CHROMADB_IMPORT_ERROR = None
except ModuleNotFoundError as error:
    chromadb = None
    Settings = None
    _CHROMADB_IMPORT_ERROR = error

from backend.core.config_manager import get_config_manager
from backend.utils.logger import get_logger


class VectorDBClient:
    """
    向量数据库客户端（单例模式）

    功能：
    1. 封装Chroma向量数据库操作
    2. 支持文档添加、查询、删除
    3. 支持元数据过滤
    4. 从ConfigManager读取配置
    """

    _instance: Optional['VectorDBClient'] = None

    def __new__(cls):
        """单例模式实现"""
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance

    def __init__(self):
        """初始化向量数据库客户端"""
        # 避免重复初始化
        if hasattr(self, '_initialized'):
            return

        self._initialized = True
        self.logger = get_logger("vector_db_client")
        self.config_manager = get_config_manager()

        # 加载配置
        self._load_config()

        # 初始化Chroma客户端
        self._init_client()

        self.logger.info(f"向量数据库客户端初始化完成: 提供商={self.provider}")

    def _load_config(self):
        """加载向量数据库配置"""
        vector_db_config = self.config_manager.get_database_config("vector_db")

        self.provider = vector_db_config.get("provider", "chroma")

        if self.provider == "chroma":
            chroma_config = vector_db_config.get("chroma", {})
            # 获取持久化目录，如果配置不存在则使用项目根目录下的 data/vectors
            persist_dir = chroma_config.get("persist_directory")
            if not persist_dir:
                # 动态查找项目根目录
                from backend.utils.path_utils import find_project_root
                project_root = find_project_root(Path(__file__).parent)
                persist_dir = str(project_root / "data" / "vectors")

            self.persist_directory = persist_dir
            self.collection_name = chroma_config.get("collection_name", "knowledge_base")
        else:
            raise ValueError(f"不支持的向量数据库提供商: {self.provider}")

    def _init_client(self):
        """初始化Chroma客户端"""
        try:
            if chromadb is None or Settings is None:
                raise RuntimeError(
                    "chromadb is not installed. Install with `pip install chromadb` "
                    "or `pip install -r requirements.txt`."
                ) from _CHROMADB_IMPORT_ERROR

            # 确保持久化目录存在
            persist_path = Path(self.persist_directory)
            persist_path.mkdir(parents=True, exist_ok=True)

            # 创建Chroma客户端
            self.client = chromadb.PersistentClient(
                path=str(persist_path),
                settings=Settings(
                    anonymized_telemetry=False,
                    allow_reset=True
                )
            )

            # 获取或创建集合
            self.collection = self.client.get_or_create_collection(
                name=self.collection_name,
                metadata={"description": "Knowledge base for RAG"}
            )

            self.logger.info(f"向量数据库集合 '{self.collection_name}' 已初始化")

        except Exception as e:
            self.logger.error(f"初始化向量数据库客户端失败: {e}")
            raise

    @staticmethod
    def normalize_where_filter(where: Optional[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
        """将简单字典过滤条件转换为 Chroma 兼容格式。"""
        if where is None:
            return None

        if not isinstance(where, dict) or not where:
            return where

        if any(str(key).startswith('$') for key in where.keys()):
            return where

        if len(where) == 1:
            return where

        return {"$and": [{key: value} for key, value in where.items()]}


    def add_documents(
        self,
        documents: List[str],
        embeddings: List[List[float]],
        metadatas: Optional[List[Dict[str, Any]]] = None,
        ids: Optional[List[str]] = None
    ) -> bool:
        """
        添加文档到向量数据库

        Args:
            documents: 文档内容列表
            embeddings: 向量嵌入列表
            metadatas: 元数据列表
            ids: 文档ID列表

        Returns:
            是否添加成功
        """
        try:
            # 生成ID（如果未提供）
            if ids is None:
                import uuid
                ids = [str(uuid.uuid4()) for _ in documents]

            # 添加文档
            self.collection.add(
                documents=documents,
                embeddings=embeddings,
                metadatas=metadatas,
                ids=ids
            )

            self.logger.info(f"已添加 {len(documents)} 个文档到向量数据库")
            return True

        except Exception as e:
            self.logger.error(f"添加文档失败: {e}")
            return False

    def query(
        self,
        query_embeddings: List[List[float]],
        n_results: int = 5,
        where: Optional[Dict[str, Any]] = None,
        where_document: Optional[Dict[str, Any]] = None
    ) -> Dict[str, Any]:
        """
        查询向量数据库

        Args:
            query_embeddings: 查询向量列表
            n_results: 返回结果数量
            where: 元数据过滤条件
            where_document: 文档内容过滤条件

        Returns:
            查询结果字典
        """
        try:
            normalized_where = self.normalize_where_filter(where)
            self.logger.info(f"开始查询向量数据库，期望返回 {n_results} 条结果")
            results = self.collection.query(
                query_embeddings=query_embeddings,
                n_results=n_results,
                where=normalized_where,
                where_document=where_document,
                include=["documents", "metadatas", "distances"]
            )

            result_count = len(results.get('ids', [[]])[0])

            # 添加详细的距离信息日志
            if result_count > 0 and results.get('distances'):
                distances = results['distances'][0]
                self.logger.info(f"查询完成，返回 {result_count} 条结果，距离范围: [{min(distances):.6f}, {max(distances):.6f}]")
                # 记录前3个结果的距离
                for i in range(min(3, len(distances))):
                    self.logger.debug(f"  结果{i+1}: 距离={distances[i]:.6f}")
            else:
                self.logger.info(f"查询完成，返回 {result_count} 条结果")

            return results

        except Exception as e:
            self.logger.error(f"查询向量数据库失败: {e}")
            return {"ids": [[]], "documents": [[]], "metadatas": [[]], "distances": [[]]}

    def delete_documents(
        self,
        ids: Optional[List[str]] = None,
        where: Optional[Dict[str, Any]] = None
    ) -> bool:
        """
        删除文档

        Args:
            ids: 要删除的文档ID列表
            where: 元数据过滤条件

        Returns:
            是否删除成功
        """
        try:
            normalized_where = self.normalize_where_filter(where)
            self.collection.delete(
                ids=ids,
                where=normalized_where
            )

            if ids:
                self.logger.info(f"从向量数据库删除 {len(ids)} 个文档")
            else:
                self.logger.info(f"从向量数据库根据元数据删除文档")
            return True

        except Exception as e:
            self.logger.error(f"删除文档失败: {e}")
            return False

    def get_collection_count(self) -> int:
        """
        获取集合中的文档数量

        Returns:
            文档数量
        """
        try:
            return self.collection.count()
        except Exception as e:
            self.logger.error(f"获取集合数量失败: {e}")
            return 0

    def update_documents(
        self,
        ids: List[str],
        documents: Optional[List[str]] = None,
        embeddings: Optional[List[List[float]]] = None,
        metadatas: Optional[List[Dict[str, Any]]] = None
    ) -> bool:
        """
        更新文档

        Args:
            ids: 文档ID列表
            documents: 新的文档内容列表
            embeddings: 新的向量嵌入列表
            metadatas: 新的元数据列表

        Returns:
            是否更新成功
        """
        try:
            self.collection.update(
                ids=ids,
                documents=documents,
                embeddings=embeddings,
                metadatas=metadatas
            )

            self.logger.info(f"已更新 {len(ids)} 个文档在向量数据库中")
            return True

        except Exception as e:
            self.logger.error(f"更新文档失败: {e}")
            return False

    def reset_collection(self) -> bool:
        """
        重置集合（删除所有文档）

        Returns:
            是否重置成功
        """
        try:
            self.client.delete_collection(name=self.collection_name)
            self.collection = self.client.create_collection(
                name=self.collection_name,
                metadata={"description": "Knowledge base for RAG"}
            )

            self.logger.warning(f"集合 \'{self.collection_name}\' 已重置")
            return True

        except Exception as e:
            self.logger.error(f"重置集合失败: {e}")
            return False

    def get_document_by_id(self, doc_id: str) -> Optional[Dict[str, Any]]:
        """
        根据ID获取文档

        Args:
            doc_id: 文档ID

        Returns:
            文档数据字典
        """
        try:
            result = self.collection.get(
                ids=[doc_id],
                include=["documents", "metadatas", "embeddings"]
            )

            if result and result.get("ids"):
                return {
                    "id": result["ids"][0],
                    "document": result["documents"][0] if result.get("documents") else None,
                    "metadata": result["metadatas"][0] if result.get("metadatas") else None,
                    "embedding": result["embeddings"][0] if result.get("embeddings") else None
                }

            return None

        except Exception as e:
            self.logger.error(f"根据ID获取文档失败: {e}")
            return None

    def search(
        self,
        query: str,
        n_results: int = 5,
        where: Optional[Dict[str, Any]] = None,
        where_document: Optional[Dict[str, Any]] = None
    ) -> Dict[str, Any]:
        """
        文本搜索（自动生成向量）

        Args:
            query: 查询文本
            n_results: 返回结果数量
            where: 元数据过滤条件
            where_document: 文档内容过滤条件

        Returns:
            查询结果字典
        """
        try:
            # 导入EmbeddingClient（延迟导入避免循环依赖）
            from backend.utils.embedding_client import get_embedding_client

            self.logger.info(f"开始文本搜索，查询: '{query[:50]}...'，期望返回 {n_results} 条结果")

            # 生成查询向量
            embedding_client = get_embedding_client()
            query_embedding = embedding_client.embed_text(query)

            if query_embedding is None:
                self.logger.error("生成查询向量失败")
                return {"ids": [[]], "documents": [[]], "metadatas": [[]], "distances": [[]]}

            # 使用向量查询
            results = self.query(
                query_embeddings=[query_embedding],
                n_results=n_results,
                where=where,
                where_document=where_document
            )

            result_count = len(results.get('ids', [[]])[0])
            self.logger.info(f"文本搜索完成，找到 {result_count} 条结果")
            return results

        except Exception as e:
            self.logger.error(f"文本搜索失败: {e}")
            return {"ids": [[]], "documents": [[]], "metadatas": [[]], "distances": [[]]}

    def __repr__(self) -> str:
        return f"VectorDBClient(provider='{self.provider}', collection='{self.collection_name}')"


# 全局实例获取函数
def get_vector_db_client() -> VectorDBClient:
    """
    获取向量数据库客户端实例（单例）

    Returns:
        VectorDBClient实例
    """
    return VectorDBClient()
