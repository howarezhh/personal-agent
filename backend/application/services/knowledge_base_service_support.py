from __future__ import annotations

from backend.infrastructure.persistence import KnowledgeBaseRepositoryAdapter
from backend.utils.logger import get_logger


# 中文日志器：统一记录知识库应用服务相关日志。
logger = get_logger(__name__)

# 默认知识库名称：用于首次访问时自动创建的默认库。
DEFAULT_KNOWLEDGE_BASE_NAME = "默认知识库"
# 默认知识库描述：用于解释该知识库的来源。
DEFAULT_KNOWLEDGE_BASE_DESCRIPTION = "系统自动创建的默认知识库"


class KnowledgeBaseServiceSupport:
    """知识库应用服务共享支持层。"""

    def __init__(self, knowledge_repo=None, document_service=None, retrieval_executor=None):
        # 知识库仓储：统一封装知识库持久化访问。
        self.knowledge_repo = knowledge_repo or KnowledgeBaseRepositoryAdapter()
        # 文档服务：供删除知识库时联动删除文档。
        self.document_service = document_service
        # 检索执行器：供知识库搜索链路调用 Retrieval Agent。
        self.retrieval_executor = retrieval_executor

    def get_user_knowledge_base(self, *, user_id: str, knowledge_base_id: str):
        """按用户范围获取知识库，作为统一访问校验入口。"""
        return self.knowledge_repo.get_by_id_for_user(knowledge_base_id, user_id)
