"""
检索结果仓储模块
提供检索结果数据的CRUD操作
"""

from typing import Optional, List
import json
from backend.database.repositories.user_repository import BaseRepository
from backend.models.retrieval_result import RetrievalResult, RetrievalResultCreate
from backend.utils.logger import get_logger
from backend.utils.time_utils import utc_now


logger = get_logger(__name__)


class RetrievalResultRepository(BaseRepository):
    """
    检索结果仓储类

    功能：
    1. 检索结果CRUD操作
    2. 按execution_id查询
    3. 按相关度分数排序
    """

    TABLE_NAME = "retrieval_results"

    def create_retrieval_result(self, result_create: RetrievalResultCreate) -> RetrievalResult:
        """
        创建检索结果

        Args:
            result_create: 检索结果创建数据

        Returns:
            创建的检索结果对象

        Raises:
            ValueError: 数据验证失败
            Exception: 数据库操作失败
        """
        # 验证数据
        is_valid, error_msg = result_create.validate()
        if not is_valid:
            raise ValueError(error_msg)

        # 创建检索结果对象
        result = result_create.to_retrieval_result()
        result.created_at = utc_now()

        # 插入数据库
        data = {
            "result_id": result.result_id,
            "execution_id": result.execution_id,
            "source_type": result.source_type,
            "source_id": result.source_id,
            "source_name": result.source_name,
            "content": result.content,
            "relevance_score": result.relevance_score,
            "rank_position": result.rank,
            "created_at": result.created_at,
            "metadata": json.dumps(result.metadata, ensure_ascii=False) if result.metadata else None,
        }

        self.db.insert_one(self.TABLE_NAME, data, return_id=False)

        logger.info(
            f"Retrieval result created: result_id={result.result_id}, "
            f"execution_id={result.execution_id}, score={result.relevance_score}"
        )
        return result

    def get_result_by_id(self, result_id: str) -> Optional[RetrievalResult]:
        """
        根据结果ID获取检索结果

        Args:
            result_id: 结果ID

        Returns:
            检索结果对象，如果不存在返回None
        """
        result = self.db.select_one(
            table=self.TABLE_NAME,
            where={"result_id": result_id}
        )
        return self._dict_to_model(result, RetrievalResult)

    def get_results_by_execution_id(
        self,
        execution_id: str,
        order_by_score: bool = True,
        limit: Optional[int] = None
    ) -> List[RetrievalResult]:
        """
        根据执行ID获取所有检索结果

        Args:
            execution_id: 执行ID
            order_by_score: 是否按相关度分数排序（默认True，降序）
            limit: 限制返回数量

        Returns:
            检索结果列表
        """
        order_by = "relevance_score DESC, rank_position ASC" if order_by_score else "rank_position ASC"

        results = self.db.select_many(
            table=self.TABLE_NAME,
            where={"execution_id": execution_id},
            order_by=order_by,
            limit=limit,
        )

        return self._dicts_to_models(results, RetrievalResult)

    def get_top_results_by_execution_id(
        self,
        execution_id: str,
        top_k: int = 5,
        min_score: Optional[float] = None
    ) -> List[RetrievalResult]:
        """
        获取执行ID的Top-K检索结果

        Args:
            execution_id: 执行ID
            top_k: 返回前K个结果
            min_score: 最小相关度分数阈值

        Returns:
            检索结果列表
        """
        # 构建查询条件
        where_clause = "execution_id = %s"
        params = [execution_id]

        if min_score is not None:
            where_clause += " AND relevance_score >= %s"
            params.append(min_score)

        sql = f"""
            SELECT * FROM {self.TABLE_NAME}
            WHERE {where_clause}
            ORDER BY relevance_score DESC, rank_position ASC
            LIMIT {top_k}
        """

        results = self.db.execute_query(sql, tuple(params))
        return self._dicts_to_models(results, RetrievalResult)

    def batch_create_retrieval_results(
        self,
        results_create: List[RetrievalResultCreate]
    ) -> List[RetrievalResult]:
        """
        批量创建检索结果

        Args:
            results_create: 检索结果创建数据列表

        Returns:
            创建的检索结果对象列表

        Raises:
            ValueError: 数据验证失败
            Exception: 数据库操作失败
        """
        results = []
        data_list = []

        for result_create in results_create:
            # 验证数据
            is_valid, error_msg = result_create.validate()
            if not is_valid:
                raise ValueError(f"数据验证失败: {error_msg}")

            # 创建检索结果对象
            result = result_create.to_retrieval_result()
            result.created_at = utc_now()
            results.append(result)

            # 准备插入数据
            data = {
                "result_id": result.result_id,
                "execution_id": result.execution_id,
                "source_type": result.source_type,
                "source_id": result.source_id,
                "source_name": result.source_name,
                "content": result.content,
                "relevance_score": result.relevance_score,
                "rank_position": result.rank,
                "created_at": result.created_at,
                "metadata": json.dumps(result.metadata, ensure_ascii=False) if result.metadata else None,
            }
            data_list.append(data)

        # 批量插入
        if data_list:
            self.db.insert_many(self.TABLE_NAME, data_list)
            logger.info(f"Batch created {len(results)} retrieval results")

        return results

    def delete_results_by_execution_id(self, execution_id: str) -> int:
        """
        删除指定执行ID的所有检索结果

        Args:
            execution_id: 执行ID

        Returns:
            删除的记录数量
        """
        affected_rows = self.db.delete_one(
            table=self.TABLE_NAME,
            where={"execution_id": execution_id}
        )

        logger.info(f"Deleted {affected_rows} retrieval results for execution_id={execution_id}")
        return affected_rows

    def count_results_by_execution_id(self, execution_id: str) -> int:
        """
        统计指定执行ID的检索结果数量

        Args:
            execution_id: 执行ID

        Returns:
            检索结果数量
        """
        return self.db.count(self.TABLE_NAME, {"execution_id": execution_id})

    def get_results_by_source(
        self,
        source_type: str,
        source_id: Optional[str] = None,
        limit: Optional[int] = None
    ) -> List[RetrievalResult]:
        """
        根据来源类型和来源ID获取检索结果

        Args:
            source_type: 来源类型
            source_id: 来源ID（可选）
            limit: 限制返回数量

        Returns:
            检索结果列表
        """
        where = {"source_type": source_type}
        if source_id:
            where["source_id"] = source_id

        results = self.db.select_many(
            table=self.TABLE_NAME,
            where=where,
            order_by="created_at DESC",
            limit=limit,
        )

        return self._dicts_to_models(results, RetrievalResult)

    def get_average_score_by_execution_id(self, execution_id: str) -> Optional[float]:
        """
        获取指定执行ID的平均相关度分数

        Args:
            execution_id: 执行ID

        Returns:
            平均相关度分数，如果没有结果返回None
        """
        sql = f"""
            SELECT AVG(relevance_score) as avg_score
            FROM {self.TABLE_NAME}
            WHERE execution_id = %s AND relevance_score IS NOT NULL
        """

        result = self.db.execute_query(sql, (execution_id,))
        if result and result[0].get("avg_score") is not None:
            return float(result[0]["avg_score"])
        return None

    def exists_by_id(self, result_id: str) -> bool:
        """
        检查结果ID是否存在

        Args:
            result_id: 结果ID

        Returns:
            是否存在
        """
        return self.db.exists(self.TABLE_NAME, {"result_id": result_id})


# 全局检索结果仓储实例
_retrieval_result_repository: Optional[RetrievalResultRepository] = None


def get_retrieval_result_repository() -> RetrievalResultRepository:
    """
    获取全局检索结果仓储实例（单例模式）

    Returns:
        RetrievalResultRepository实例
    """
    global _retrieval_result_repository

    if _retrieval_result_repository is None:
        _retrieval_result_repository = RetrievalResultRepository()

    return _retrieval_result_repository
